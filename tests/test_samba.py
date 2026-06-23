"""Tests for ForgeOS Samba share API — now wired to the v2 config-DB + generator.

Validates:
  1. Auth enforcement (401/403)
  2. Shares are read from the config-DB
  3. Create/delete mutate the config-DB and trigger apply (save+generate+reload)
  4. Validation (bad path, duplicate name, missing fields)
"""
from __future__ import annotations

import pytest


@pytest.fixture
def samba_cfg(tmp_path, monkeypatch):
    """Point the config-DB at a temp file + capture apply() calls so the test
    never writes /etc or runs systemctl."""
    import forgeos_config as fc
    import samba_api

    cfgfile = tmp_path / "config.json"
    monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
    monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
    fc.save(fc.ForgeOSConfig(), cfgfile)

    applied = []
    # apply still persists to the (temp) config-DB so reads see the change,
    # but skips generate+reload (no /etc writes, no systemctl).
    samba_api.set_apply(lambda cfg: fc.save(cfg, cfgfile) or applied.append(cfg))
    yield {"file": cfgfile, "applied": applied}
    samba_api.set_apply(None)


class TestSambaShares:
    def test_auth_required(self, test_client):
        assert test_client.get("/api/samba/shares").status_code == 401

    def test_lists_shares_from_config_db(self, test_client, auth_headers, samba_cfg):
        import forgeos_config as fc
        cfg = fc.load(samba_cfg["file"])
        cfg.samba.shares.append(fc.SambaShare(name="media", path="/srv/nas/media"))
        fc.save(cfg, samba_cfg["file"])
        r = test_client.get("/api/samba/shares", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert any(s["name"] == "media" for s in data["shares"])


class TestCreateShare:
    def test_auth_required(self, test_client):
        r = test_client.post("/api/samba/share", json={"name": "t", "path": "/srv/nas/t"})
        assert r.status_code == 401

    def test_forbids_non_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.post("/api/samba/share", json={"name": "t", "path": "/srv/nas/t"}, headers=h)
        assert r.status_code == 403

    def test_creates_and_applies(self, test_client, auth_headers, samba_cfg):
        r = test_client.post("/api/samba/share",
                             json={"name": "docs", "path": "/srv/nas/docs", "writable": True},
                             headers=auth_headers)
        assert r.status_code == 200
        # persisted to config-DB
        import forgeos_config as fc
        cfg = fc.load(samba_cfg["file"])
        assert any(s.name == "docs" for s in cfg.samba.shares)
        # apply (generate+reload) was triggered
        assert len(samba_cfg["applied"]) == 1

    def test_rejects_relative_path(self, test_client, auth_headers, samba_cfg):
        r = test_client.post("/api/samba/share",
                             json={"name": "bad", "path": "relative/path"},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_duplicate(self, test_client, auth_headers, samba_cfg):
        body = {"name": "dup", "path": "/srv/nas/dup"}
        assert test_client.post("/api/samba/share", json=body, headers=auth_headers).status_code == 200
        r = test_client.post("/api/samba/share", json=body, headers=auth_headers)
        assert r.status_code == 409


class TestDeleteShare:
    def test_forbids_non_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        assert test_client.delete("/api/samba/share/x", headers=h).status_code == 403

    def test_deletes_and_applies(self, test_client, auth_headers, samba_cfg):
        test_client.post("/api/samba/share",
                         json={"name": "tmp", "path": "/srv/nas/tmp"}, headers=auth_headers)
        samba_cfg["applied"].clear()
        r = test_client.delete("/api/samba/share/tmp", headers=auth_headers)
        assert r.status_code == 200
        import forgeos_config as fc
        cfg = fc.load(samba_cfg["file"])
        assert not any(s.name == "tmp" for s in cfg.samba.shares)
        assert len(samba_cfg["applied"]) == 1

    def test_delete_missing_404(self, test_client, auth_headers, samba_cfg):
        assert test_client.delete("/api/samba/share/nope", headers=auth_headers).status_code == 404


class TestCreateShareAdvanced:
    """The Shares page POSTs every advanced option — verify they persist through
    the create endpoint into the config-DB rather than being silently dropped."""

    def test_advanced_fields_persist(self, test_client, auth_headers, samba_cfg):
        import forgeos_config as fc
        body = {
            "name": "vault", "path": "/srv/nas/vault", "type": "standard",
            "writable": False, "valid_users": ["keith", "lorri"],
            "comment": "Family vault",
            "browseable": True, "guest_ok": True, "hide_dot_files": False,
            "recycle_bin": True, "force_user": "keith", "force_group": "family",
            "permissions": "private", "write_list": ["keith"],
        }
        r = test_client.post("/api/samba/share", json=body, headers=auth_headers)
        assert r.status_code == 200, r.text
        cfg = fc.load(samba_cfg["file"])
        s = [x for x in cfg.samba.shares if x.name == "vault"][0]
        assert s.browseable is True
        assert s.guest_ok is True
        assert s.hide_dot_files is False
        assert s.recycle_bin is True
        assert s.force_user == "keith" and s.force_group == "family"
        assert s.permissions == "private"
        assert s.write_list == ["keith"]
        assert s.writable is False
        assert s.valid_users == ["keith", "lorri"]

    def test_browseable_defaults_off_when_omitted(self, test_client, auth_headers, samba_cfg):
        import forgeos_config as fc
        r = test_client.post("/api/samba/share",
                             json={"name": "hid", "path": "/srv/nas/hid"},
                             headers=auth_headers)
        assert r.status_code == 200
        cfg = fc.load(samba_cfg["file"])
        s = [x for x in cfg.samba.shares if x.name == "hid"][0]
        assert s.browseable is False          # never auto-visible
        assert s.permissions == "group"       # safe default preserved

    def test_bad_force_user_rejected(self, test_client, auth_headers, samba_cfg):
        r = test_client.post("/api/samba/share",
                             json={"name": "x", "path": "/srv/nas/x",
                                   "force_user": "bad user"},
                             headers=auth_headers)
        assert r.status_code == 400
class TestRawCustomConfig:
    """S1b: raw .conf editing via a custom include the generator never overwrites."""

    def test_get_auth_required(self, test_client):
        assert test_client.get("/api/samba/config").status_code == 401

    def test_get_empty_when_missing(self, test_client, auth_headers, tmp_path, monkeypatch):
        import samba_api
        monkeypatch.setattr(samba_api, "CUSTOM_FILE", str(tmp_path / "nope.conf"))
        r = test_client.get("/api/samba/config", headers=auth_headers)
        assert r.status_code == 200 and r.json()["config"] == ""

    def test_get_returns_content(self, test_client, auth_headers, tmp_path, monkeypatch):
        import samba_api
        f = tmp_path / "custom.conf"; f.write_text("[scratch]\n   path = /srv/nas/scratch\n")
        monkeypatch.setattr(samba_api, "CUSTOM_FILE", str(f))
        assert "[scratch]" in test_client.get("/api/samba/config", headers=auth_headers).json()["config"]

    def test_put_forbids_non_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('reg', 'user')}"}
        assert test_client.put("/api/samba/config", json={"config": "x"}, headers=h).status_code == 403

    def test_put_writes_and_reloads(self, test_client, auth_headers, tmp_path, monkeypatch, samba_cfg):
        import samba_api
        f = tmp_path / "custom.conf"
        monkeypatch.setattr(samba_api, "CUSTOM_FILE", str(f))
        monkeypatch.setattr(samba_api, "_audit", lambda *a, **k: None)
        body = {"config": "[scratch]\n   path = /srv/nas/scratch\n   browseable = no\n"}
        r = test_client.put("/api/samba/config", json=body, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert f.read_text() == body["config"]            # written verbatim
        assert len(samba_cfg["applied"]) == 1             # regenerated smb.conf + reloaded

    def test_put_rejects_invalid_config(self, test_client, auth_headers, tmp_path, monkeypatch):
        import samba_api
        from generators import GeneratorError
        f = tmp_path / "custom.conf"
        monkeypatch.setattr(samba_api, "CUSTOM_FILE", str(f))
        monkeypatch.setattr(samba_api, "_audit", lambda *a, **k: None)
        def boom(self, cfg, text): raise GeneratorError("testparm: bad line 2")
        monkeypatch.setattr(samba_api.SambaGenerator, "validate_custom", boom)
        r = test_client.put("/api/samba/config", json={"config": "garbage"}, headers=auth_headers)
        assert r.status_code == 400
        assert not f.exists()                                        # never persisted
