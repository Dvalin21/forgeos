"""Scheduled data scrub (btrfs scrub): config migration, unit rendering,
runner behaviour and the API surface.

Scrubbing is what makes the storage promise real — it verifies the checksums
btrfs writes and repairs from the good copy on a redundant profile. ForgeOS
could always run one from a button; these tests cover the scheduler that makes
it automatic, because a scheduler nobody exercises is a scheduler that silently
never fires.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc
import forgeos_scrub as fs


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestScheduleTranslation:
    def test_words_map_to_calendar(self):
        assert fs.oncalendar("daily") == "*-*-* 02:30:00"
        assert fs.oncalendar("weekly") == "Sun *-*-* 02:30:00"
        assert fs.oncalendar("monthly") == "*-*-01 02:30:00"

    def test_case_insensitive(self):
        assert fs.oncalendar("Monthly") == "*-*-01 02:30:00"

    def test_raw_oncalendar_passes_through(self):
        # an operator can pick a time the UI does not offer
        assert fs.oncalendar("Mon *-*-* 03:15:00") == "Mon *-*-* 03:15:00"


class TestUnitRendering:
    def test_timer_is_persistent_and_scheduled(self):
        unit = fs.render_timer_unit("*-*-01 02:30:00")
        assert "OnCalendar=*-*-01 02:30:00" in unit
        # Persistent=true is what makes a missed run (box was off) happen on
        # next boot instead of silently skipping a month.
        assert "Persistent=true" in unit
        assert "WantedBy=timers.target" in unit

    def test_service_runs_the_cli(self):
        unit = fs.render_service_unit()
        assert "ExecStart=forgeos-storage scrub run" in unit
        assert "Type=oneshot" in unit
        # Blocking form: we need the exit status, which -B would not give us.
        assert "-B" not in unit.split("ExecStart")[1]


class TestScrubRunner:
    def _runner(self, rc=0, stderr="", audit=None, notify=None):
        calls = []
        audits = []
        notices = []

        def run(cmd, timeout=60):
            calls.append(cmd)
            return FakeCompleted(returncode=rc, stderr=stderr)

        def audit(who, action, status, detail=None):
            audits.append((who, action, status, detail))

        def notify(level, title, message):
            notices.append((level, title, message))

        return fs.ScrubRunner(run=run, audit=audit, notify=notify), calls, audits, notices

    def test_clean_scrub_is_recorded_once(self):
        r, calls, audits, notices = self._runner(rc=0)
        out = r.scrub_pools([("tank", "/srv/nas/tank")])
        assert out["ok"] is True
        assert out["checked"] == ["tank"] and out["failed"] == []
        assert calls == [["btrfs", "scrub", "start", "/srv/nas/tank"]]
        assert len(audits) == 1 and audits[0][2] == "success"
        # a clean run must not page anybody
        assert notices == []

    def test_non_zero_exit_is_reported_not_raised(self):
        r, calls, audits, notices = self._runner(rc=1, stderr="ERROR: scrub errors found")
        out = r.scrub_pools([("tank", "/srv/nas/tank")])
        assert out["ok"] is False
        assert out["failed"] == ["tank"]
        assert "scrub errors found" in out["errors"]["tank"]
        assert audits[0][2] == "warning"
        assert notices and notices[0][0] == "critical"

    def test_one_bad_pool_does_not_stop_the_others(self):
        calls = []

        def run(cmd, timeout=60):
            calls.append(cmd)
            if cmd[3] == "/srv/nas/bad":
                return FakeCompleted(returncode=1, stderr="csum mismatch")
            return FakeCompleted(returncode=0)

        r = fs.ScrubRunner(run=run, audit=lambda *a: None, notify=lambda *a: None)
        out = r.scrub_pools([("bad", "/srv/nas/bad"), ("tank", "/srv/nas/tank")])
        assert out["checked"] == ["bad", "tank"]
        assert out["failed"] == ["bad"]
        # both were actually attempted
        assert len(calls) == 2

    def test_no_pools_is_not_an_error(self):
        r, calls, audits, notices = self._runner()
        out = r.scrub_pools([])
        assert out["ok"] is True and calls == []


class TestTargetResolution:
    def _cfg(self, pools, scrub_pools=None):
        return fc.ForgeOSConfig.model_validate({
            "storage": {
                "pools": pools,
                "scrub": {"pools": scrub_pools or []},
            }
        })

    def test_empty_list_means_every_pool(self):
        cfg = self._cfg([{"name": "tank"}, {"name": "archive"}])
        got = fs.target_pools(cfg, resolver=lambda n: "/srv/nas/" + n)
        assert [n for n, _ in got] == ["tank", "archive"]

    def test_explicit_list_filters(self):
        cfg = self._cfg([{"name": "tank"}, {"name": "archive"}], scrub_pools=["tank"])
        got = fs.target_pools(cfg, resolver=lambda n: "/srv/nas/" + n)
        assert [n for n, _ in got] == ["tank"]

    def test_unmounted_pool_is_skipped_not_scrubbed(self):
        # btrfs needs a live path; scrubbing an unmounted pool would fail and
        # report a false problem.
        cfg = self._cfg([{"name": "tank"}])
        got = fs.target_pools(cfg, resolver=lambda n: "")
        assert got == []


class TestConfigMigration:
    def test_v12_config_gains_scrub_defaults(self):
        cfg = fc.ForgeOSConfig.model_validate(
            fc.migrate({"version": 12, "storage": {"pools": [{"name": "tank"}]}}))
        assert cfg.storage.scrub.enabled is False
        assert cfg.storage.scrub.schedule == "monthly"
        assert cfg.storage.scrub.pools == []

    def test_schema_version_bumped(self):
        # Assert the migration PATH, not an absolute version: later features
        # add schema blocks and a hardcoded == 13 breaks for them. A v12 file
        # must still reach the current version.
        assert 12 in fc._MIGRATIONS
        assert fc.migrate({"version": 12})["version"] == fc.SCHEMA_VERSION
        assert fc.SCHEMA_VERSION >= 13

    def test_existing_scrub_settings_survive_migration(self):
        raw = {"version": 12, "storage": {"scrub": {"enabled": True, "schedule": "weekly"}}}
        cfg = fc.ForgeOSConfig.model_validate(fc.migrate(raw))
        assert cfg.storage.scrub.enabled is True
        assert cfg.storage.scrub.schedule == "weekly"

    def test_pool_names_are_sanitised(self):
        cfg = fc.ScrubConfig(pools=["tank; rm -rf /"])
        assert cfg.pools == ["tankrm-rf"]

    def test_empty_schedule_rejected(self):
        with pytest.raises(ValueError):
            fc.ScrubConfig(schedule="  ")


class TestScrubScheduleApi:
    """The two endpoints behind the Storage page's schedule control."""

    @pytest.fixture
    def cfgfile(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        cfg = fc.ForgeOSConfig.model_validate({
            "storage": {"pools": [{"name": "tank", "raid_level": "raid1"}]}})
        fc.save(cfg, path)
        monkeypatch.setattr(fc, "CONFIG_PATH", path)
        return path

    def test_get_reports_defaults(self, test_client, auth_headers, cfgfile,
                                  monkeypatch):
        import forgeos_scrub as fsr
        monkeypatch.setattr(fsr.ScrubRunner, "timer_status",
                            lambda self: {"active": False, "state": "inactive"})
        monkeypatch.setattr("storage_api._any_scrub_running", lambda: False)
        r = test_client.get("/api/storage/scrub-schedule", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["enabled"] is False
        assert d["schedule"] == "monthly"
        assert d["calendar"] == "*-*-01 02:30:00"
        assert d["scrub_running"] is False
        assert "last_scrub" in d

    def test_post_enables_and_installs_timer(self, test_client, auth_headers,
                                             cfgfile, monkeypatch):
        import forgeos_scrub as fsr
        seen = []

        def fake_setup(self, calendar, **kw):
            seen.append(calendar)

        monkeypatch.setattr(fsr.ScrubRunner, "setup_timer", fake_setup)
        monkeypatch.setattr(fsr.ScrubRunner, "timer_status",
                            lambda self: {"active": True, "state": "active"})
        r = test_client.post("/api/storage/scrub-schedule", headers=auth_headers,
                             json={"enabled": True, "schedule": "weekly"})
        assert r.status_code == 200
        assert seen == ["Sun *-*-* 02:30:00"]
        saved = fc.load(cfgfile)
        assert saved.storage.scrub.enabled is True
        assert saved.storage.scrub.schedule == "weekly"

    def test_post_disables_timer(self, test_client, auth_headers, cfgfile,
                                 monkeypatch):
        import forgeos_scrub as fsr
        called = []
        monkeypatch.setattr(fsr.ScrubRunner, "disable_timer",
                            lambda self: called.append(True))
        r = test_client.post("/api/storage/scrub-schedule", headers=auth_headers,
                             json={"enabled": False})
        assert r.status_code == 200
        assert called == [True]
        assert fc.load(cfgfile).storage.scrub.enabled is False

    def test_non_admin_cannot_change_the_schedule(self, test_client, user_headers,
                                                   cfgfile):
        r = test_client.post("/api/storage/scrub-schedule", headers=user_headers,
                             json={"enabled": True})
        assert r.status_code == 403

    def test_unknown_pool_is_rejected(self, test_client, auth_headers, cfgfile):
        r = test_client.post("/api/storage/scrub-schedule", headers=auth_headers,
                             json={"enabled": True, "pools": ["ghost"]})
        assert r.status_code == 400
        assert "ghost" in r.json()["detail"]

class TestLastScrubDerivation:
    """/api/storage/scrub-schedule derives "last checked" per pool from the
    audit trail. Two writers produce two detail shapes; if either stops
    parsing, every pool silently reads as never-checked."""

    def _rows(self, conn, rows):
        import sqlite3
        conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                     " timestamp TEXT, who TEXT, action TEXT, status TEXT, detail TEXT)")
        for ts, detail in rows:
            conn.execute("INSERT INTO audit_log (timestamp, who, action, status, detail)"
                         " VALUES (?,?,?,?,?)", (ts, "system", "storage.pool.scrub_done", "success", detail))

    def _parse(self, conn):
        import storage_api
        storage_api._get_db = lambda: conn
        try:
            return storage_api._last_scrub_times()
        finally:
            storage_api._get_db = None

    def test_manual_scrub_detail(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "a.db"), check_same_thread=False)
        self._rows(conn, [("2026-10-12T04:00:00", "tank scrub finished — no errors found")])
        assert "tank" in self._parse(conn)

    def test_scheduled_scrub_detail(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "b.db"), check_same_thread=False)
        self._rows(conn, [("2026-10-12T04:00:00", "scrubbed: tank, archive; problems: archive")])
        got = self._parse(conn)
        assert "tank" in got and "archive" in got

    def test_newest_wins(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "c.db"), check_same_thread=False)
        self._rows(conn, [("2026-10-01T00:00:00", "tank scrub finished"),
                          ("2026-10-12T00:00:00", "tank scrub finished")])
        assert self._parse(conn)["tank"].startswith("2026-10-12")

    def test_scheduled_run_names_its_pools(self, tmp_path):
        """The scheduled runner must name pools, or 'last checked' is empty."""
        import sqlite3
        audits = []
        r = fs.ScrubRunner(run=lambda cmd, timeout=60: FakeCompleted(),
                           audit=lambda *a: audits.append(a), notify=lambda *a: None)
        r.scrub_pools([("tank", "/srv/nas/tank")])
        detail = audits[0][3]
        assert "tank" in detail


class TestDefaultAudit:
    """The runner's DEFAULT audit must write a row.

    Found on the VM: a real scheduled scrub ran, reported "clean", and left
    NO audit row — because the default was a no-op lambda. The Storage page
    derives "last checked" from these rows, so the panel stayed frozen at the
    last manual scrub. Tests that inject a fake audit never see it."""

    def test_default_audit_is_not_a_noop(self, tmp_path, monkeypatch):
        import sqlite3
        from datetime import datetime
        monkeypatch.setenv("FORGEOS_DATA_DIR", str(tmp_path))
        db = tmp_path / "forgeos.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                     " timestamp TEXT, who TEXT, action TEXT, status TEXT, detail TEXT)")
        conn.commit()
        conn.close()

        # no injected audit/notify: exactly what `forgeos-storage scrub run` does
        r = fs.ScrubRunner(run=lambda cmd, timeout=60: FakeCompleted())
        r.scrub_pools([("tank", "/srv/nas/tank")])

        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT action, status, detail FROM audit_log").fetchall()
        conn.close()
        assert len(rows) == 1, f"expected exactly one audit row, got {rows}"
        action, status, detail = rows[0]
        assert action == "storage.pool.scrub_scheduled"
        assert status == "success"
        assert "tank" in detail, "the detail must NAME the pool for last-checked"
