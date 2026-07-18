"""Data Connect: config model, avahi generator, and API."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.avahi import AvahiGenerator, AVAHI_SERVICE  # noqa: E402


class TestModel:
    def test_managed_db_valid(self):
        d = fc.ManagedDatabase(name="pos", kind="file", data_path="/srv/nas/pos", app="Atrex")
        assert d.name == "pos" and d.kind == "file"

    def test_rejects_relative_path(self):
        with pytest.raises(Exception):
            fc.ManagedDatabase(name="x", kind="file", data_path="relative/path")

    def test_rejects_bad_name(self):
        with pytest.raises(Exception):
            fc.ManagedDatabase(name="bad name", kind="file", data_path="/x")

    def test_duplicate_names_rejected(self):
        with pytest.raises(Exception):
            fc.DataConnectConfig(databases=[
                fc.ManagedDatabase(name="a", kind="file", data_path="/x"),
                fc.ManagedDatabase(name="A", kind="file", data_path="/y"),
            ])

    def test_toggle_renamed(self):
        assert hasattr(fc.TogglesConfig(), "data_connect")
        assert not hasattr(fc.TogglesConfig(), "forgefiledb")

    def test_migration_renames_toggle(self):
        d = fc.migrate({"version": 8, "toggles": {"forgefiledb": True}})
        assert d["toggles"]["data_connect"] is True
        assert "forgefiledb" not in d["toggles"]
        assert d["version"] == fc.SCHEMA_VERSION


class TestAvahiGenerator:
    def test_broadcast_on_emits_service(self):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        cfg.data_connect.broadcast = True
        files = AvahiGenerator().render(cfg)
        assert files and files[0].path == AVAHI_SERVICE
        assert "_data-connect._tcp" in files[0].content

    def test_broadcast_off_emits_nothing(self):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        cfg.data_connect.broadcast = False
        assert AvahiGenerator().render(cfg) == []

    def test_disabled_emits_nothing(self):
        cfg = fc.ForgeOSConfig()   # enabled defaults False
        assert AvahiGenerator().render(cfg) == []


@pytest.fixture(autouse=True)
def _dc_apply_seam():
    """All data-connect API writes go through the seam — no /etc, no systemctl."""
    import data_connect_api
    applied = []
    data_connect_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
    yield applied
    data_connect_api.set_apply(None)


class TestAPI:
    def test_import_and_list(self, test_client, auth_headers, tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        dbdir = tmp_path / "pos"; dbdir.mkdir()
        (dbdir / "data.edb").write_text("x")   # ElevateDB file -> detection
        r = test_client.post("/api/data-connect/import", headers=auth_headers, json={
            "name": "pos", "data_path": str(dbdir), "app": "Atrex"})
        assert r.status_code == 200, r.text
        assert r.json()["db_type"] == "ElevateDB"
        lst = test_client.get("/api/data-connect", headers=auth_headers).json()
        assert any(d["name"] == "pos" and d["app"] == "Atrex" for d in lst["databases"])

    def test_import_requires_admin(self, test_client, user_headers, tmp_path):
        r = test_client.post("/api/data-connect/import", headers=user_headers, json={
            "name": "x", "data_path": str(tmp_path)})
        assert r.status_code == 403

    def test_import_rejects_traversal(self, test_client, auth_headers, tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        r = test_client.post("/api/data-connect/import", headers=auth_headers, json={
            "name": "x", "data_path": "/etc"})
        assert r.status_code == 400

    def test_broadcast_toggle(self, test_client, auth_headers):
        r = test_client.post("/api/data-connect/broadcast", headers=auth_headers,
                             json={"broadcast": False})
        assert r.status_code == 200 and r.json()["broadcast"] is False

    def test_remove(self, test_client, auth_headers, tmp_path, monkeypatch):
        import data_connect_api, forgeos_config as fcfg
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "db2"; d.mkdir()
        test_client.post("/api/data-connect/import", headers=auth_headers,
                         json={"name": "db2", "data_path": str(d)})
        r = test_client.delete("/api/data-connect/db2", headers=auth_headers)
        assert r.status_code == 200
        assert not any(x.name == "db2" for x in fcfg.load().data_connect.databases)


class TestDbFamilyExtensions:
    def test_inverse_of_families(self):
        assert fc.db_family_extensions("ElevateDB") == [".edb", ".edbi", ".edbl", ".edbt"]
        for ext in fc.db_family_extensions("SQLite"):
            assert fc.DB_FAMILIES[ext] == "SQLite"

    def test_unknown_family_empty(self):
        assert fc.db_family_extensions("") == []
        assert fc.db_family_extensions("NoSuchDB") == []


class TestProtectedShareRendering:
    """Patch 2: file DBs render as Samba shares with the corruption-safe
    locking recipe. cfg.data_connect is the single source of truth — nothing
    is mirrored into cfg.samba.shares."""

    RECIPE = ["oplocks = no", "level2 oplocks = no", "locking = yes",
              "strict locking = yes", "strict sync = yes", "sync always = yes"]

    def _shares_text(self, cfg):
        from generators.samba import SHARES_FILE, SambaGenerator
        files = SambaGenerator().render(cfg)
        return next(f.content for f in files if f.path == SHARES_FILE)

    def _cfg(self, **db):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        cfg.data_connect.databases.append(fc.ManagedDatabase(**db))
        return cfg

    def test_file_db_renders_protected_share(self):
        cfg = self._cfg(name="pos", kind="file", data_path="/srv/nas/pos",
                        app="Atrex", db_type="ElevateDB")
        text = self._shares_text(cfg)
        assert "[pos]" in text and "path = /srv/nas/pos" in text
        section = text[text.index("[pos]"):]
        for directive in self.RECIPE:
            assert directive in section, directive
        assert "veto oplock files = /*.edb/*.edbi/*.edbl/*.edbt/" in section
        assert "guest ok = no" in section

    def test_unknown_family_no_veto_still_protected(self):
        cfg = self._cfg(name="mystery", kind="file", data_path="/srv/nas/m")
        section = self._shares_text(cfg)
        assert "[mystery]" in section
        assert "veto oplock files" not in section
        for directive in self.RECIPE:
            assert directive in section, directive

    def test_server_db_renders_no_share(self):
        # postgres/mysql data dirs must NEVER be on an SMB share.
        cfg = self._cfg(name="pg", kind="postgres",
                        data_path="/var/lib/postgresql", port=5432)
        assert "[pg]" not in self._shares_text(cfg)

    def test_data_connect_disabled_renders_no_share(self):
        cfg = self._cfg(name="pos", kind="file", data_path="/srv/nas/pos")
        cfg.data_connect.enabled = False
        assert "[pos]" not in self._shares_text(cfg)

    def test_name_collision_with_samba_share_fails_loud(self):
        from generators import GeneratorError
        from generators.samba import SambaGenerator
        cfg = self._cfg(name="pos", kind="file", data_path="/srv/nas/pos")
        cfg.samba.shares.append(fc.SambaShare(name="POS", path="/srv/nas/other"))
        with pytest.raises(GeneratorError, match="collides"):
            SambaGenerator().render(cfg)

    def test_kernel_oplocks_never_in_share_scope(self):
        # `kernel oplocks` is a GLOBAL parameter; inside a share section smbd
        # ignores it. It used to be emitted by the legacy database type.
        cfg = self._cfg(name="pos", kind="file", data_path="/srv/nas/pos",
                        db_type="ElevateDB")
        cfg.samba.shares.append(
            fc.SambaShare(name="legacy", path="/srv/nas/l", type="database"))
        assert "kernel oplocks" not in self._shares_text(cfg)

    def test_legacy_database_type_gets_full_recipe(self):
        cfg = fc.ForgeOSConfig()
        cfg.samba.shares.append(
            fc.SambaShare(name="legacy", path="/srv/nas/l", type="database"))
        text = self._shares_text(cfg)
        section = text[text.index("[legacy]"):]
        for directive in self.RECIPE:
            assert directive in section, directive


class TestApiProtectionGuards:
    def test_import_refused_when_samba_disabled(self, test_client, auth_headers,
                                                tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "db"; d.mkdir()
        cfg = fc.load(); cfg.samba.enabled = False; fc.save(cfg)
        try:
            r = test_client.post("/api/data-connect/import", headers=auth_headers,
                                 json={"name": "db", "data_path": str(d)})
            assert r.status_code == 409
            assert "Samba" in r.json()["detail"]
        finally:
            cfg = fc.load(); cfg.samba.enabled = True; fc.save(cfg)

    def test_import_refuses_samba_share_collision(self, test_client, auth_headers,
                                                  tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "media"; d.mkdir()
        cfg = fc.load()
        cfg.samba.shares.append(fc.SambaShare(name="media", path="/srv/nas/media"))
        fc.save(cfg)
        try:
            r = test_client.post("/api/data-connect/import", headers=auth_headers,
                                 json={"name": "MEDIA", "data_path": str(d)})
            assert r.status_code == 409
        finally:
            cfg = fc.load()
            cfg.samba.shares = [s for s in cfg.samba.shares if s.name != "media"]
            fc.save(cfg)

    def test_import_refuses_reserved_names(self, test_client, auth_headers,
                                           tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "homes"; d.mkdir()
        r = test_client.post("/api/data-connect/import", headers=auth_headers,
                             json={"name": "homes", "data_path": str(d)})
        assert r.status_code == 400

    def test_import_remove_broadcast_all_apply(self, test_client, auth_headers,
                                               tmp_path, monkeypatch, _dc_apply_seam):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "adb"; d.mkdir()
        assert test_client.post("/api/data-connect/import", headers=auth_headers,
                                json={"name": "adb", "data_path": str(d)}).status_code == 200
        assert test_client.post("/api/data-connect/broadcast", headers=auth_headers,
                                json={"broadcast": True}).status_code == 200
        assert test_client.delete("/api/data-connect/adb",
                                  headers=auth_headers).status_code == 200
        assert len(_dc_apply_seam) == 3   # every write regenerated, none save-only

    def test_list_reports_protected(self, test_client, auth_headers,
                                    tmp_path, monkeypatch):
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "pdb"; d.mkdir()
        test_client.post("/api/data-connect/import", headers=auth_headers,
                         json={"name": "pdb", "data_path": str(d)})
        try:
            lst = test_client.get("/api/data-connect", headers=auth_headers).json()
            row = next(x for x in lst["databases"] if x["name"] == "pdb")
            assert row["protected"] is True and lst["samba_enabled"] is True
        finally:
            test_client.delete("/api/data-connect/pdb", headers=auth_headers)


class TestDbServerGenerator:
    """Patch 3: durability drop-ins + integrity-timer management."""

    def _cfg(self, *kinds):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        for i, k in enumerate(kinds):
            cfg.data_connect.databases.append(fc.ManagedDatabase(
                name=f"db{i}", kind=k,
                data_path="/var/lib/x" if k != "file" else "/srv/nas/x",
                port={"postgres": 5432, "mysql": 3306}.get(k, 0)))
        return cfg

    def test_postgres_dropin_per_cluster(self, monkeypatch):
        from generators import dbserver
        monkeypatch.setattr(dbserver, "_pg_confdirs",
                            lambda: ["/etc/postgresql/17/main/conf.d"])
        files = dbserver.DbServerGenerator().render(self._cfg("postgres"))
        assert [f.path for f in files] == ["/etc/postgresql/17/main/conf.d/forgeos.conf"]
        for directive in ("fsync = on", "synchronous_commit = on",
                          "full_page_writes = on"):
            assert directive in files[0].content, directive

    def test_mysql_dropin(self, monkeypatch):
        from generators import dbserver
        monkeypatch.setattr(dbserver, "_pg_confdirs", lambda: [])
        files = dbserver.DbServerGenerator().render(self._cfg("mysql"))
        assert [f.path for f in files] == [dbserver.MYSQL_DROPIN]
        assert "innodb_flush_log_at_trx_commit = 1" in files[0].content
        assert "[mysqld]" in files[0].content

    def test_file_dbs_render_nothing(self, monkeypatch):
        from generators import dbserver
        monkeypatch.setattr(dbserver, "_pg_confdirs",
                            lambda: ["/etc/postgresql/17/main/conf.d"])
        assert dbserver.DbServerGenerator().render(self._cfg("file")) == []
        assert dbserver.DbServerGenerator().render(fc.ForgeOSConfig()) == []

    def test_apply_enables_timer_and_reloads_pg(self, monkeypatch, tmp_path):
        from generators import dbserver
        confd = tmp_path / "17" / "main" / "conf.d"
        monkeypatch.setattr(dbserver, "_pg_confdirs", lambda: [str(confd)])
        monkeypatch.setattr(dbserver, "MYSQL_DROPIN", str(tmp_path / "99-forgeos.cnf"))
        calls = []
        gen = dbserver.DbServerGenerator()
        monkeypatch.setattr(gen, "_run",
                            lambda cmd, check=True: calls.append(cmd) or
                            __import__("types").SimpleNamespace(returncode=0))
        gen.apply(self._cfg("postgres", "mysql"))
        assert (confd / "forgeos.conf").exists()
        assert ["systemctl", "reload", "postgresql"] in calls
        assert ["systemctl", "enable", "--now", dbserver.DBCHECK_TIMER] in calls

    def test_apply_removes_stale_and_disables_timer(self, monkeypatch, tmp_path):
        from generators import dbserver
        confd = tmp_path / "17" / "main" / "conf.d"
        confd.mkdir(parents=True)
        stale = confd / "forgeos.conf"; stale.write_text("old")
        monkeypatch.setattr(dbserver, "_pg_confdirs", lambda: [str(confd)])
        monkeypatch.setattr(dbserver, "MYSQL_DROPIN", str(tmp_path / "99-forgeos.cnf"))
        calls = []
        gen = dbserver.DbServerGenerator()
        monkeypatch.setattr(gen, "_run",
                            lambda cmd, check=True: calls.append(cmd) or
                            __import__("types").SimpleNamespace(returncode=0))
        gen.apply(fc.ForgeOSConfig())      # nothing tracked -> cleanup
        assert not stale.exists()
        assert ["systemctl", "disable", "--now", dbserver.DBCHECK_TIMER] in calls


class TestUfwDataConnectRules:
    def test_server_db_ports_allowed_lan_scoped(self):
        from generators.ufw import UfwGenerator
        cfg = fc.ForgeOSConfig()
        cfg.security.lan_cidr = "10.0.0.0/24"
        cfg.data_connect.enabled = True
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name="pg", kind="postgres", data_path="/var/lib/postgresql", port=5432))
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name="files", kind="file", data_path="/srv/nas/f"))
        rules = UfwGenerator()._data_connect_rules(cfg)
        assert len(rules) == 1
        r = rules[0]
        assert "5432" in r and "10.0.0.0/24" in r and "allow" in r

    def test_no_rules_when_disabled(self):
        from generators.ufw import UfwGenerator
        assert UfwGenerator()._data_connect_rules(fc.ForgeOSConfig()) == []


class TestAvahiServerRecords:
    def test_engine_records_broadcast(self):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        cfg.data_connect.broadcast = True
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name="pg", kind="postgres", data_path="/var/lib/postgresql", port=5432))
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name="m", kind="mysql", data_path="/var/lib/mysql", port=3306))
        xml = AvahiGenerator().render(cfg)[0].content
        assert "_postgresql._tcp" in xml and "<port>5432</port>" in xml
        assert "_mysql._tcp" in xml and "<port>3306</port>" in xml
        assert xml.rstrip().endswith("</service-group>")

    def test_file_only_no_engine_records(self):
        cfg = fc.ForgeOSConfig()
        cfg.data_connect.enabled = True
        cfg.data_connect.broadcast = True
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name="f", kind="file", data_path="/srv/nas/f"))
        xml = AvahiGenerator().render(cfg)[0].content
        assert "_postgresql._tcp" not in xml and "_mysql._tcp" not in xml


class TestRegisterServerApi:
    @pytest.fixture(autouse=True)
    def _run_seam(self):
        import data_connect_api
        self.cmds = []
        def fake(cmd, timeout):
            self.cmds.append(cmd)
            import types
            # dpkg -s: engine "installed" by default in these tests
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        data_connect_api.set_run(fake)
        yield
        data_connect_api.set_run(None)

    def test_unknown_engine_400(self, test_client, auth_headers):
        r = test_client.post("/api/data-connect/register-server",
                             headers=auth_headers,
                             json={"name": "x", "engine": "oracle"})
        assert r.status_code == 400

    def test_requires_admin(self, test_client, user_headers):
        r = test_client.post("/api/data-connect/register-server",
                             headers=user_headers,
                             json={"name": "x", "engine": "postgres"})
        assert r.status_code == 403

    def test_register_tracks_and_starts_engine(self, test_client, auth_headers):
        r = test_client.post("/api/data-connect/register-server",
                             headers=auth_headers,
                             json={"name": "pgmain", "engine": "postgres",
                                   "app": "Inventory"})
        assert r.status_code == 200, r.text
        assert r.json()["port"] == 5432
        try:
            assert ["systemctl", "enable", "--now", "postgresql"] in self.cmds
            # no apt when engine already installed
            assert not any("apt-get" in c for c in self.cmds)
            lst = test_client.get("/api/data-connect", headers=auth_headers).json()
            row = next(d for d in lst["databases"] if d["name"] == "pgmain")
            assert row["kind"] == "postgres" and row["protected"] is True
            assert row["data_path"] == "/var/lib/postgresql"
        finally:
            test_client.delete("/api/data-connect/pgmain", headers=auth_headers)

    def test_not_installed_409_without_install_flag(self, test_client, auth_headers):
        import data_connect_api, types
        def fake(cmd, timeout):
            self.cmds.append(cmd)
            rc = 1 if cmd[:2] == ["dpkg", "-s"] else 0
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="")
        data_connect_api.set_run(fake)
        r = test_client.post("/api/data-connect/register-server",
                             headers=auth_headers,
                             json={"name": "m1", "engine": "mysql"})
        assert r.status_code == 409
        assert "mariadb-server" in r.json()["detail"]

    def test_install_is_async_202_then_completes(self, test_client, auth_headers):
        """Install must NEVER block the request (nginx would 504). First call
        starts a named transient unit and returns 202; the poll retry
        completes registration once dpkg sees the package."""
        import data_connect_api, types
        state = {"installed": False, "unit_active": False}
        def fake(cmd, timeout):
            self.cmds.append(cmd)
            if cmd[:2] == ["dpkg", "-s"]:
                return types.SimpleNamespace(
                    returncode=0 if state["installed"] else 1, stdout="", stderr="")
            if cmd[:2] == ["systemctl", "is-active"]:
                return types.SimpleNamespace(
                    returncode=0 if state["unit_active"] else 1, stdout="", stderr="")
            if cmd[0] == "systemd-run":
                state["unit_active"] = True
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        data_connect_api.set_run(fake)
        body = {"name": "m2", "engine": "mysql", "install": True}
        r1 = test_client.post("/api/data-connect/register-server",
                              headers=auth_headers, json=body)
        assert r1.status_code == 202 and r1.json()["installing"] is True
        sd = next(c for c in self.cmds if c[0] == "systemd-run")
        # apt runs OUTSIDE the API sandbox, as a NAMED unit, WITHOUT --wait
        assert "apt-get" in sd and "mariadb-server" in sd
        assert "--wait" not in sd and any(a.startswith("--unit=") for a in sd)
        # poll while install still running: 202 again, and NO second unit
        r2 = test_client.post("/api/data-connect/register-server",
                              headers=auth_headers, json=body)
        assert r2.status_code == 202
        assert sum(1 for c in self.cmds if c[0] == "systemd-run") == 1
        # install finishes -> retry completes registration
        state["installed"] = True
        r3 = test_client.post("/api/data-connect/register-server",
                              headers=auth_headers, json=body)
        assert r3.status_code == 200, r3.text
        try:
            assert ["systemctl", "enable", "--now", "mariadb"] in self.cmds
        finally:
            test_client.delete("/api/data-connect/m2", headers=auth_headers)

    def test_apply_failures_are_logged(self, test_client, auth_headers,
                                       tmp_path, monkeypatch, caplog):
        """Regression: a failed generator apply must leave a log line, not
        vanish (the read-only /etc/postgresql bug was invisible for exactly
        this reason)."""
        import logging
        import data_connect_api
        monkeypatch.setattr(data_connect_api, "WATCH_ROOT", tmp_path)
        d = tmp_path / "ldb"; d.mkdir()
        # real _apply_data_connect, but with the registry faked to fail
        data_connect_api.set_apply(None)
        from generators import registry as reg

        class FakeResult:
            ok = False
            error = "read-only file system"
        monkeypatch.setattr(reg, "apply_one",
                            lambda n, cfg=None, do_reload=True: FakeResult())
        monkeypatch.setattr(data_connect_api.fc, "save", lambda cfg: None)
        with caplog.at_level(logging.ERROR):
            r = test_client.post("/api/data-connect/import", headers=auth_headers,
                                 json={"name": "ldb", "data_path": str(d)})
        assert r.status_code == 200
        assert any("read-only" in rec.message for rec in caplog.records)

    def test_duplicate_name_409(self, test_client, auth_headers):
        test_client.post("/api/data-connect/register-server", headers=auth_headers,
                         json={"name": "dup", "engine": "postgres"})
        try:
            r = test_client.post("/api/data-connect/register-server",
                                 headers=auth_headers,
                                 json={"name": "DUP", "engine": "mysql"})
            assert r.status_code == 409
        finally:
            test_client.delete("/api/data-connect/dup", headers=auth_headers)


# ──────────────────────────────────────────────────────────
# Managed database provisioning (create DB + user in engine)
# ──────────────────────────────────────────────────────────


class TestDbProvisionUnit:
    """db_provision: the injection boundary and show-once secret model."""

    def setup_method(self):
        import db_provision, tempfile, pathlib
        db_provision.SECRETS_FILE = pathlib.Path(tempfile.mktemp(suffix=".json"))
        self.sql = []
        db_provision.set_run(self._fake)

    def teardown_method(self):
        import db_provision
        db_provision.set_run(None)

    def _fake(self, cmd, sql, timeout):
        import types
        self.sql.append(sql)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_identifier_rejects_injection(self):
        import db_provision as dp
        assert dp.valid_identifier("app_db") and dp.valid_identifier("_x1")
        for bad in ["a b", "a-b", "1abc", "", "a;b", "a`b",
                    "app'x", 'app"x', "drop;--", "a" * 64]:
            assert not dp.valid_identifier(bad), bad

    def test_provision_creates_and_hashes_showonce(self):
        import db_provision as dp
        pw = dp.provision("postgres", "appdb", "appuser", "trackkey")
        assert len(pw) >= 24
        assert any("CREATE DATABASE" in s for s in self.sql)
        assert any("CREATE USER" in s for s in self.sql)
        # returned plaintext verifies; wrong does not; plaintext is NOT stored
        assert dp.verify_password("trackkey", pw)
        assert not dp.verify_password("trackkey", "nope")
        raw = dp.SECRETS_FILE.read_text()
        assert pw not in raw and "$2b$" in raw          # only the hash persisted

    def test_secrets_file_is_0600(self):
        import db_provision as dp, os
        dp.provision("mysql", "d", "u", "k")
        assert oct(os.stat(dp.SECRETS_FILE).st_mode)[-3:] == "600"

    def test_reset_invalidates_old(self):
        import db_provision as dp
        p1 = dp.provision("postgres", "d", "u", "k")
        p2 = dp.reset_password("postgres", "u", "k")
        assert p1 != p2
        assert dp.verify_password("k", p2) and not dp.verify_password("k", p1)

    def test_deprovision_drops_and_forgets(self):
        import db_provision as dp
        pw = dp.provision("mysql", "d", "u", "k")
        self.sql.clear()
        dp.deprovision("mysql", "d", "u", "k")
        assert any("DROP DATABASE" in s for s in self.sql)
        assert any("DROP USER" in s for s in self.sql)
        assert not dp.verify_password("k", pw)          # secret gone

    def test_provision_bad_identifier_raises_before_sql(self):
        import db_provision as dp, pytest
        with pytest.raises(dp.ProvisionError):
            dp.provision("postgres", "bad name", "u", "k")
        assert self.sql == []                           # nothing executed

    def test_engine_failure_rolls_back_database(self):
        import db_provision as dp, types
        # CREATE DATABASE ok, CREATE USER fails -> DROP DATABASE must run
        seq = iter([0, 1])
        def flaky(cmd, sql, timeout):
            self.sql.append(sql)
            rc = 0 if "CREATE DATABASE" in sql or "DROP" in sql else 1
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="boom")
        dp.set_run(flaky)
        with pytest.raises(dp.ProvisionError):
            dp.provision("postgres", "d", "u", "k")
        assert any("DROP DATABASE" in s for s in self.sql)


class TestManagedDatabaseApi:
    @pytest.fixture(autouse=True)
    def _seams(self, monkeypatch, tmp_path):
        import data_connect_api, db_provision
        # engine "installed" + started
        self.cmds = []
        def fake_run(cmd, timeout):
            self.cmds.append(cmd)
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        data_connect_api.set_run(fake_run)
        # provisioning SQL faked
        self.sql = []
        def fake_sql(cmd, sql, timeout):
            import types
            self.sql.append(sql)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        db_provision.set_run(fake_sql)
        import pathlib
        db_provision.SECRETS_FILE = tmp_path / "db-secrets.json"
        # apply seam so nothing touches /etc or systemctl beyond config
        applied = []
        data_connect_api.set_apply(lambda cfg: applied.append(cfg) or __import__("forgeos_config").save(cfg))
        yield
        data_connect_api.set_run(None); db_provision.set_run(None)
        data_connect_api.set_apply(None)

    def test_register_with_create_db_returns_password_once(self, test_client, auth_headers):
        r = test_client.post("/api/data-connect/register-server", headers=auth_headers,
                             json={"name": "shop", "engine": "postgres", "create_db": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["managed"] is True
        creds = body["credentials"]
        assert creds["database"] == "shop" and creds["user"] == "shop"
        assert len(creds["password"]) >= 24
        try:
            # connection endpoint returns everything EXCEPT the password
            c = test_client.get("/api/data-connect/shop/connection", headers=auth_headers).json()
            assert "password" not in c and c["user"] == "shop"
        finally:
            test_client.post("/api/data-connect/shop/delete-database",
                             headers=auth_headers, json={"confirm": "shop"})

    def test_register_invalid_identifier_400(self, test_client, auth_headers):
        r = test_client.post("/api/data-connect/register-server", headers=auth_headers,
                             json={"name": "ok", "engine": "postgres",
                                   "create_db": True, "db_name": "bad name"})
        assert r.status_code == 400

    def test_delete_database_requires_typed_confirmation(self, test_client, auth_headers):
        test_client.post("/api/data-connect/register-server", headers=auth_headers,
                         json={"name": "gone", "engine": "mysql", "create_db": True})
        try:
            bad = test_client.post("/api/data-connect/gone/delete-database",
                                   headers=auth_headers, json={"confirm": "wrong"})
            assert bad.status_code == 400
        finally:
            ok = test_client.post("/api/data-connect/gone/delete-database",
                                  headers=auth_headers, json={"confirm": "gone"})
            assert ok.status_code == 200
            assert any("DROP DATABASE" in s for s in self.sql)

    def test_delete_database_refuses_unmanaged(self, test_client, auth_headers):
        # track-only (no create_db) -> delete-database must refuse
        test_client.post("/api/data-connect/register-server", headers=auth_headers,
                         json={"name": "trackonly", "engine": "postgres"})
        try:
            r = test_client.post("/api/data-connect/trackonly/delete-database",
                                 headers=auth_headers, json={"confirm": "trackonly"})
            assert r.status_code == 409
        finally:
            test_client.delete("/api/data-connect/trackonly", headers=auth_headers)

    def test_reset_password_new_creds_once(self, test_client, auth_headers):
        reg = test_client.post("/api/data-connect/register-server", headers=auth_headers,
                               json={"name": "rot", "engine": "postgres", "create_db": True})
        first = reg.json()["credentials"]["password"]
        try:
            r = test_client.post("/api/data-connect/rot/reset-password", headers=auth_headers)
            assert r.status_code == 200
            assert r.json()["credentials"]["password"] != first
        finally:
            test_client.post("/api/data-connect/rot/delete-database",
                             headers=auth_headers, json={"confirm": "rot"})

    def test_stop_tracking_leaves_engine_untouched(self, test_client, auth_headers):
        test_client.post("/api/data-connect/register-server", headers=auth_headers,
                         json={"name": "keepdb", "engine": "mysql", "create_db": True})
        self.sql.clear()
        r = test_client.delete("/api/data-connect/keepdb", headers=auth_headers)
        assert r.status_code == 200
        # stop-tracking must NOT issue DROP — the DB stays in the engine
        assert not any("DROP" in s for s in self.sql)
