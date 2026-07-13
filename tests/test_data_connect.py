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
