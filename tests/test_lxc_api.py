"""Tests for the SEPARATED LXC API + Docker hardening.

Docker and LXC are now distinct modules. Validates:
  - LXC routes live under /api/lxc (separate from /api/docker)
  - name validation rejects argument-injection attempts
  - destructive/exec ops require admin
"""
from __future__ import annotations

import pytest


class TestLxcSeparation:
    def test_lxc_routes_under_own_prefix(self, test_client):
        # /api/lxc/containers exists (auth required => 401, not 404)
        assert test_client.get("/api/lxc/containers").status_code == 401

    def test_old_docker_lxc_path_gone(self, test_client, auth_headers):
        # the tangled /api/docker/lxc/containers must no longer exist
        r = test_client.get("/api/docker/lxc/containers", headers=auth_headers)
        assert r.status_code == 404


class TestLxcHardening:
    def test_invalid_name_rejected(self, test_client, auth_headers):
        # a name starting with '-' could be read as a flag => reject 400
        r = test_client.post("/api/lxc/containers/-evil/start", headers=auth_headers)
        assert r.status_code == 400

    def test_destroy_requires_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.post("/api/lxc/containers/web/destroy", headers=h)
        assert r.status_code == 403

    def test_exec_requires_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.post("/api/lxc/containers/web/exec",
                             json={"command": "ls"}, headers=h)
        assert r.status_code == 403


class TestDockerHardening:
    def test_invalid_container_name_rejected(self, test_client, auth_headers):
        r = test_client.post("/api/docker/containers/-evil/start", headers=auth_headers)
        assert r.status_code == 400

    def test_prune_requires_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.post("/api/docker/prune/system", headers=h)
        assert r.status_code == 403

    def test_exec_requires_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.post("/api/docker/containers/web/exec",
                             json={"command": "ls"}, headers=h)
        assert r.status_code == 403

    def test_remove_container_requires_admin(self, test_client):
        from forgeos_auth import create_token
        h = {"Authorization": f"Bearer {create_token('regular', 'user')}"}
        r = test_client.delete("/api/docker/containers/web", headers=h)
        assert r.status_code == 403
