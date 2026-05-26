"""
Tests for ForgeOS Docker/container API endpoints.

Validates:
  1. Auth enforcement (401 without proper token)
  2. App catalog listing
  3. System service status
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
# GET /api/docker/apps
# ──────────────────────────────────────────────────────────


class TestDockerApps:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/docker/apps")
        assert r.status_code == 401

    def test_returns_app_list(self, test_client, auth_headers):
        r = test_client.get("/api/docker/apps", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "apps" in data
        assert len(data["apps"]) > 0
        # Verify well-known apps exist
        names = [a["name"] for a in data["apps"]]
        assert "nginx" in names
        assert "jellyfin" in names
        assert "portainer" in names
        assert all("image" in a for a in data["apps"])


# ──────────────────────────────────────────────────────────
# GET /api/services
# ──────────────────────────────────────────────────────────


class TestServices:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/services")
        assert r.status_code == 401

    def test_returns_service_list(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="active\n"))
        r = test_client.get("/api/services", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "services" in data
        # Should have at least the key services
        svc_names = [s["name"] for s in data["services"]]
        assert "Docker" in svc_names
        assert "nginx" in svc_names


# ──────────────────────────────────────────────────────────
# GET /api/network
# ──────────────────────────────────────────────────────────


class TestNetwork:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/network")
        assert r.status_code == 401

    def test_returns_network_info(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **kw: _mock_subprocess_run(stdout="eth0    192.168.1.100"))
        r = test_client.get("/api/network", headers=auth_headers)
        assert r.status_code == 200
