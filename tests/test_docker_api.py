"""
Tests for ForgeOS Docker/container API endpoints.

Validates:
  1. Auth enforcement (401 without proper token)
  2. App catalog listing
  3. System service status
  4. Admin gate: only admin tokens may reach docker routes (non-admin -> 403)
     (router-level require_admin added after review found verify_token-only gate)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


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


# ──────────────────────────────────────────────────────────
# Admin gate (router-level require_admin)
# ──────────────────────────────────────────────────────────


class TestAdminGate:

    def test_non_admin_forbidden(self, test_client: TestClient, user_headers):
        # Both docker routers are admin-gated; non-admin must be rejected (403)
        # before any docker/lxc command runs.
        # install runs `docker run` as root (docker_api.py)
        assert test_client.post("/api/docker/install?app=nginx",
                                headers=user_headers).status_code == 403
        # prune / container / compose mutations (docker_lxc_api.py)
        assert test_client.post("/api/docker/prune/system",
                                headers=user_headers).status_code == 403
        assert test_client.post("/api/docker/containers/c/start",
                                headers=user_headers).status_code == 403
        assert test_client.put("/api/docker/compose-file", json={"content": "x"},
                               headers=user_headers).status_code == 403

    def test_admin_passes_gate(self, test_client: TestClient, auth_headers):
        # Admin reaches the handler; without docker installed the call may fail
        # for a tooling reason, but it must NOT be rejected at the auth gate.
        r = test_client.post("/api/docker/prune/system", headers=auth_headers)
        assert r.status_code not in (401, 403)
