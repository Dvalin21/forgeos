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
