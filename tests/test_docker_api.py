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


# ──────────────────────────────────────────────────────────
# GET /api/docker/containers — truthful states + NDJSON
# ──────────────────────────────────────────────────────────


class TestListContainers:

    def _patch(self, monkeypatch, result):
        import docker_lxc_api
        monkeypatch.setattr(docker_lxc_api, "_run_docker", lambda a, timeout=30: result)

    def test_docker_absent_is_200_state_not_500(self, test_client, auth_headers,
                                                monkeypatch):
        """Regression: boxes without Docker got a 500 on every dashboard
        poll — a permanent journal storm for a perfectly normal state."""
        self._patch(monkeypatch, {"success": False,
                                  "error": "[Errno 2] No such file or directory: 'docker'"})
        r = test_client.get("/api/docker/containers", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is False and body["containers"] == []
        assert "not installed" in body["reason"]

    def test_daemon_down_is_200_state(self, test_client, auth_headers, monkeypatch):
        self._patch(monkeypatch, {"success": False, "error": "", "returncode": 1,
                                  "stdout": "",
                                  "stderr": "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"})
        r = test_client.get("/api/docker/containers", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["available"] is False
        assert "daemon" in r.json()["reason"]

    def test_genuine_failure_keeps_500_with_evidence(self, test_client,
                                                     auth_headers, monkeypatch):
        self._patch(monkeypatch, {"success": False, "error": "", "returncode": 1,
                                  "stdout": "", "stderr": "permission denied on socket"})
        r = test_client.get("/api/docker/containers", headers=auth_headers)
        assert r.status_code == 500
        # stderr used to be dropped entirely from the detail
        assert "permission denied" in r.json()["detail"]

    def test_ndjson_multi_container_parse(self, test_client, auth_headers,
                                          monkeypatch):
        """Regression: docker ps --format json is NDJSON (one object per
        line); whole-blob json.loads broke at >=2 containers and the UI
        silently showed an empty list."""
        nd = '{"Names": "web", "State": "running"}\n{"Names": "db", "State": "exited"}'
        self._patch(monkeypatch, {"success": True, "stdout": nd, "stderr": "",
                                  "returncode": 0})
        r = test_client.get("/api/docker/containers", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert [c["Names"] for c in body["containers"]] == ["web", "db"]

    def test_single_and_empty_still_work(self, test_client, auth_headers,
                                         monkeypatch):
        self._patch(monkeypatch, {"success": True, "stdout": "", "stderr": "",
                                  "returncode": 0})
        assert test_client.get("/api/docker/containers",
                               headers=auth_headers).json()["containers"] == []
        self._patch(monkeypatch, {"success": True, "returncode": 0, "stderr": "",
                                  "stdout": '{"Names": "solo"}'})
        r = test_client.get("/api/docker/containers", headers=auth_headers)
        assert [c["Names"] for c in r.json()["containers"]] == ["solo"]


# ──────────────────────────────────────────────────────────
# 0039 — truthful surface: compose -f, NDJSON class, gates
# ──────────────────────────────────────────────────────────


class TestComposeWiring:
    def test_compose_always_passes_file(self, monkeypatch):
        """Regression: _run_compose never passed -f; the service's cwd has no
        compose file, so every compose op silently targeted an empty project."""
        import docker_lxc_api as d
        seen = {}
        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(d.subprocess, "run", fake_run)
        d._run_compose(["ps"])
        assert "-f" in seen["cmd"]
        assert d.DOCKER_COMPOSE_FILE in seen["cmd"]
        i = seen["cmd"].index("-f")
        assert seen["cmd"][i + 1] == d.DOCKER_COMPOSE_FILE
        # explicit file overrides (used by the PUT validator)
        d._run_compose(["config", "-q"], compose_file="/tmp/x.yml")
        assert seen["cmd"][seen["cmd"].index("-f") + 1] == "/tmp/x.yml"

    def test_images_ndjson(self, test_client, auth_headers, monkeypatch):
        import docker_lxc_api as d
        nd = '{"Repository":"nginx","Tag":"latest"}\n{"Repository":"redis","Tag":"7"}'
        monkeypatch.setattr(d, "_run_docker",
                            lambda a, timeout=30: {"success": True, "stdout": nd,
                                                   "stderr": "", "returncode": 0})
        r = test_client.get("/api/docker/images", headers=auth_headers)
        assert [i["Repository"] for i in r.json()["images"]] == ["nginx", "redis"]


class TestAdminGates:
    """Every docker-state mutation is admin; reads stay open to any
    authenticated user."""

    MUTATIONS = [
        ("POST", "/api/docker/containers/x/start"),
        ("POST", "/api/docker/containers/x/stop"),
        ("POST", "/api/docker/containers/x/restart"),
        ("POST", "/api/docker/compose/up"),
        ("POST", "/api/docker/compose/down"),
        ("POST", "/api/docker/compose/pull"),
        ("POST", "/api/docker/compose/build"),
        ("PUT",  "/api/docker/compose-file"),
    ]

    def test_non_admin_403_on_all_mutations(self, test_client, user_headers):
        for method, path in self.MUTATIONS:
            r = test_client.request(method, path, headers=user_headers,
                                    json={"content": "x"} if method == "PUT" else None)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code}"

    def test_reads_stay_open(self, test_client, user_headers, monkeypatch):
        import docker_lxc_api as d
        monkeypatch.setattr(d, "_run_docker",
                            lambda a, timeout=30: {"success": True, "stdout": "",
                                                   "stderr": "", "returncode": 0})
        assert test_client.get("/api/docker/containers",
                               headers=user_headers).status_code == 200

    def test_logs_merge_both_streams(self, test_client, auth_headers, monkeypatch):
        """Docker writes container output to stdout AND stderr; the endpoint
        used to drop stderr — half the logs vanished."""
        import docker_lxc_api as d
        monkeypatch.setattr(d, "_run_docker",
                            lambda a, timeout=30: {"success": True,
                                                   "stdout": "out-line",
                                                   "stderr": "err-line",
                                                   "returncode": 0})
        r = test_client.get("/api/docker/containers/x/logs", headers=auth_headers)
        assert "out-line" in r.json()["logs"] and "err-line" in r.json()["logs"]


class TestComposeFilePut:
    def test_invalid_compose_rejected_live_file_untouched(self, test_client,
                                                          auth_headers,
                                                          monkeypatch, tmp_path):
        import docker_lxc_api as d
        live = tmp_path / "docker-compose.yml"
        live.write_text("services: {}\n")
        monkeypatch.setattr(d, "DOCKER_COMPOSE_FILE", str(live))
        monkeypatch.setattr(d, "_run_compose",
                            lambda a, timeout=60, compose_file=None:
                            {"success": False, "stderr": "yaml: mapping error",
                             "returncode": 1})
        r = test_client.put("/api/docker/compose-file", headers=auth_headers,
                            json={"content": "not: [valid"})
        assert r.status_code == 400 and "invalid" in r.json()["detail"]
        assert live.read_text() == "services: {}\n"      # untouched
        assert not live.with_suffix(".yml.new").exists()  # temp cleaned

    def test_valid_compose_written_atomically(self, test_client, auth_headers,
                                              monkeypatch, tmp_path):
        import docker_lxc_api as d
        live = tmp_path / "docker-compose.yml"
        live.write_text("old")
        monkeypatch.setattr(d, "DOCKER_COMPOSE_FILE", str(live))
        monkeypatch.setattr(d, "_run_compose",
                            lambda a, timeout=60, compose_file=None:
                            {"success": True, "stdout": "", "stderr": "",
                             "returncode": 0})
        r = test_client.put("/api/docker/compose-file", headers=auth_headers,
                            json={"content": "services: {web: {image: nginx}}"})
        assert r.status_code == 200
        assert "web" in live.read_text()
