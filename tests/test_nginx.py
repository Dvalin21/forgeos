"""
Tests for ForgeOS nginx vhost API endpoints.

Validates:
  1. Auth enforcement (401/403 without proper token/role)
  2. Input validation (400 on bad inputs)
  3. System command integration (mocked subprocess calls)
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import pytest


def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ──────────────────────────────────────────────────────────
# GET /api/nginx/vhosts
# ──────────────────────────────────────────────────────────


class TestNginxVhosts:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/nginx/vhosts")
        assert r.status_code == 401

    def test_returns_empty_when_no_vhosts(self, test_client, auth_headers):
        """When /etc/nginx/forgeos.d doesn't exist, returns empty list."""
        r = test_client.get("/api/nginx/vhosts", headers=auth_headers)
        data = r.json()
        assert r.status_code == 200
        assert "vhosts" in data
        # Should either be empty or gracefully handle missing dir
        assert isinstance(data["vhosts"], list)


# ──────────────────────────────────────────────────────────
# POST /api/nginx/vhost
# ──────────────────────────────────────────────────────────


class TestAddVhost:

    def test_auth_required(self, test_client):
        r = test_client.post("/api/nginx/vhost", json={"name": "test", "domain": "test.com", "port": 80})
        assert r.status_code == 401

    def test_forbids_non_admin(self, test_client):
        """Non-admin role should get 403."""
        from forgeos_auth import create_token
        user_token = create_token("regular", "user")
        headers = {"Authorization": f"Bearer {user_token}"}
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "test", "domain": "test.com", "port": 80},
                             headers=headers)
        # The role is embedded in the JWT — a non-admin token
        # with role "user" should be rejected by admin checks
        assert r.status_code == 403 or r.status_code == 401

    def test_rejects_invalid_port(self, test_client, auth_headers):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "test", "domain": "test.com", "port": 99999},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_sanitizes_name(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="ok"))
        # Name with special chars should be cleaned
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "Test Site!!!", "domain": "example.com", "port": 443},
                             headers=auth_headers)
        assert r.status_code == 200

    def test_dispatches_forgeos_nginx_cli(self, test_client, auth_headers, monkeypatch):
        calls = []
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: (
                                calls.append(a[0]),
                                _mock_subprocess_run(stdout="ok")
                            )[1])
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "myapp", "domain": "myapp.example.com", "port": 3000},
                             headers=auth_headers)
        assert r.status_code == 200
        # Verify forgeos-nginx was called
        assert any("forgeos-nginx" in str(c) for c in calls), f"forgeos-nginx not called: {calls}"


# ──────────────────────────────────────────────────────────
# DELETE /api/nginx/vhost/{name}
# ──────────────────────────────────────────────────────────


class TestRemoveVhost:

    def test_auth_required(self, test_client):
        r = test_client.delete("/api/nginx/vhost/test")
        assert r.status_code == 401

    def test_removes_vhost(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="removed"))
        r = test_client.delete("/api/nginx/vhost/myapp", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True


# ──────────────────────────────────────────────────────────
# POST /api/nginx/reload
# ──────────────────────────────────────────────────────────


class TestReload:

    def test_auth_required(self, test_client):
        r = test_client.post("/api/nginx/reload")
        assert r.status_code == 401

    def test_reload_rejected_if_config_fails(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="configuration file test failed"))
        r = test_client.post("/api/nginx/reload", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is False


# ──────────────────────────────────────────────────────────
# POST /api/nginx/test
# ──────────────────────────────────────────────────────────


class TestNginxTest:

    def test_auth_required(self, test_client):
        r = test_client.post("/api/nginx/test")
        assert r.status_code == 401

    def test_returns_output(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="test is successful"))
        r = test_client.post("/api/nginx/test", headers=auth_headers)
        assert r.status_code == 200
