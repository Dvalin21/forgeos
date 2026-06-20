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
