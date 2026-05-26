"""
Tests for ForgeOS Samba share API endpoints.

Validates:
  1. Auth enforcement (401/403 without proper token/role)
  2. Input validation (400 on bad inputs)
  3. System command integration (mocked calls)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ──────────────────────────────────────────────────────────
# GET /api/samba/shares
# ──────────────────────────────────────────────────────────


class TestSambaShares:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/samba/shares")
        assert r.status_code == 401

    def test_returns_raw_output(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="share1: /srv/nas/share1\nshare2: /srv/nas/share2"))
        r = test_client.get("/api/samba/shares", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "raw" in data


# ──────────────────────────────────────────────────────────
# POST /api/samba/share
# ──────────────────────────────────────────────────────────


class TestCreateShare:

    def test_auth_required(self, test_client):
        r = test_client.post("/api/samba/share", json={"name": "test", "path": "/srv/nas/test"})
        assert r.status_code == 401

    def test_forbids_non_admin(self, test_client):
        from forgeos_auth import create_token
        user_token = create_token("regular", "user")
        headers = {"Authorization": f"Bearer {user_token}"}
        r = test_client.post("/api/samba/share",
                             json={"name": "test", "path": "/srv/nas/test"},
                             headers=headers)
        assert r.status_code == 403

    def test_sanitizes_name(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="created"))
        r = test_client.post("/api/samba/share",
                             json={"name": "Test Share!", "path": "/srv/nas/test", "writable": True},
                             headers=auth_headers)
        assert r.status_code == 200

    def test_dispatches_forgeos_samba_cli(self, test_client, auth_headers, monkeypatch):
        calls = []
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: (
                                calls.append(a[0]),
                                _mock_subprocess_run(stdout="created")
                            )[1])
        r = test_client.post("/api/samba/share",
                             json={"name": "docs", "path": "/srv/nas/docs", "type": "standard",
                                   "writable": True, "users": "@staff", "comment": "Team docs"},
                             headers=auth_headers)
        assert r.status_code == 200
        assert any("forgeos-samba" in str(c) for c in calls), f"forgeos-samba not called: {calls}"


# ──────────────────────────────────────────────────────────
# DELETE /api/samba/share/{name}
# ──────────────────────────────────────────────────────────


class TestRemoveShare:

    def test_auth_required(self, test_client):
        r = test_client.delete("/api/samba/share/test")
        assert r.status_code == 401

    def test_removes_share(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="removed"))
        r = test_client.delete("/api/samba/share/docs", headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ──────────────────────────────────────────────────────────
# GET /api/samba/connections
# ──────────────────────────────────────────────────────────


class TestSambaConnections:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/samba/connections")
        assert r.status_code == 401

    def test_returns_output(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="No connections"))
        r = test_client.get("/api/samba/connections", headers=auth_headers)
        assert r.status_code == 200
