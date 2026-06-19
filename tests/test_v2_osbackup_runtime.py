"""Tests for the OS-backup (ReaR) runtime — timer units, run, notify."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_osbackup as ob  # noqa: E402


class R:
    def __init__(self, rc=0, err=""):
        self.returncode = rc
        self.stdout = ""
        self.stderr = err


# ---- unit rendering (pure) ----

def test_service_unit_runs_rear_mkbackup():
    u = ob.render_service_unit()
    assert "ExecStart=/usr/sbin/rear -v mkbackup" in u
    assert "Type=oneshot" in u


def test_timer_unit_has_oncalendar():
    u = ob.render_timer_unit("Sun *-*-* 02:30:00")
    assert "OnCalendar=Sun *-*-* 02:30:00" in u
    assert "WantedBy=timers.target" in u
    assert "Persistent=true" in u


# ---- timer setup/disable ----

def test_setup_timer_writes_units_and_enables():
    cmds = []
    writes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: cmds.append(cmd) or R()
    runner.setup_timer(
        "daily *-*-* 02:30:00",
        write=lambda p, c, m: writes.append((p, m)),
    )
    paths = [p for p, _ in writes]
    assert ob.SERVICE_UNIT in paths
    assert ob.TIMER_UNIT in paths
    joined = [" ".join(c) for c in cmds]
    assert any("daemon-reload" in j for j in joined)
    assert any("enable --now forgeos-osbackup.timer" in j for j in joined)


def test_disable_timer():
    cmds = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: cmds.append(cmd) or R()
    runner.disable_timer()
    assert any("disable --now forgeos-osbackup.timer" in " ".join(c) for c in cmds)


# ---- backup run + notify ----

def test_run_backup_success_notifies_info():
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: R(0)
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    ok = runner.run_backup()
    assert ok is True
    assert any(lvl == "info" and "complete" in t for lvl, t in notes)


def test_run_backup_failure_notifies_critical():
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: R(1, "disk full")
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    ok = runner.run_backup()
    assert ok is False
    assert any(lvl == "critical" and "FAILED" in t for lvl, t in notes)


def test_run_backup_cloud_sync_called():
    cmds = []
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: cmds.append(cmd) or R(0)
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    runner.find_artifacts = lambda p: (200 * 1024 * 1024, 1024 * 1024 * 1024)  # valid
    ok = runner.run_backup(cloud_sync=True, cloud_remote="b2", backup_path="/mnt/backup/osbackup")
    assert ok is True
    assert any("rclone" in " ".join(c) and "sync" in " ".join(c) for c in cmds)


def test_run_backup_rejects_missing_iso():
    # rear exits 0 but no real ISO landed -> must NOT report success
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: R(0)
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    runner.find_artifacts = lambda p: (4096, 1024 * 1024 * 1024)  # ISO too small
    ok = runner.run_backup(backup_path="/mnt/backup/osbackup")
    assert ok is False
    assert any(lvl == "critical" and "INCOMPLETE" in t for lvl, t in notes)


def test_run_backup_rejects_missing_archive():
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: R(0)
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    runner.find_artifacts = lambda p: (200 * 1024 * 1024, 4096)  # archive too small
    ok = runner.run_backup(backup_path="/mnt/backup/osbackup")
    assert ok is False
    assert any(lvl == "critical" and "INCOMPLETE" in t for lvl, t in notes)


def test_run_backup_accepts_valid_artifacts():
    notes = []
    runner = ob.OsBackupRunner()
    runner.run = lambda cmd: R(0)
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    runner.find_artifacts = lambda p: (171 * 1024 * 1024, 1100 * 1024 * 1024)  # real sizes
    ok = runner.run_backup(backup_path="/mnt/backup/osbackup")
    assert ok is True
    assert any(lvl == "info" and "complete" in t for lvl, t in notes)


def test_find_artifacts_skips_old_rotation(tmp_path):
    # the .old copy must NOT count — we verify the CURRENT backup
    cur = tmp_path / "forgeos"
    old = tmp_path / "forgeos.old"
    cur.mkdir(); old.mkdir()
    (cur / "rear-forgeos.iso").write_bytes(b"x" * (30 * 1024 * 1024))
    (cur / "backup.tar.zst").write_bytes(b"x" * (60 * 1024 * 1024))
    (old / "rear-forgeos.iso").write_bytes(b"x" * (999 * 1024 * 1024))
    iso, arch = ob.OsBackupRunner._default_find_artifacts(str(tmp_path))
    assert iso == 30 * 1024 * 1024      # current, not the 999M old one
    assert arch == 60 * 1024 * 1024


def test_run_backup_cloud_sync_failure_still_local_ok():
    notes = []
    runner = ob.OsBackupRunner()
    # rear ok, rclone fails
    def run(cmd):
        if cmd[0] == "rclone":
            return R(1, "auth error")
        return R(0)
    runner.run = run
    runner.notify = lambda lvl, t, m: notes.append((lvl, t))
    runner.find_artifacts = lambda p: (200 * 1024 * 1024, 1024 * 1024 * 1024)
    ok = runner.run_backup(cloud_sync=True, cloud_remote="b2", backup_path="/mnt/backup/osbackup")
    assert ok is True   # local backup succeeded
    assert any(lvl == "warning" for lvl, t in notes)


def test_atomic_write_creates_parents(tmp_path):
    target = tmp_path / "etc" / "systemd" / "system" / "x.timer"
    ob._atomic_write(str(target), "content", 0o644)
    assert target.exists()
    assert target.read_text() == "content"
