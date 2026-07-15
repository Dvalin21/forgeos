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


# ──────────────────────────────────────────────────────────
# 0040 — update-check / update / wipe / run lifecycle
# ──────────────────────────────────────────────────────────


def _docker_fake(monkeypatch, containers=None, images=None, fail=()):
    """Command-dispatching fake for _run_docker. `containers`/`images` map
    name -> inspect dict. Records every call in the returned list."""
    import docker_lxc_api as d
    calls = []
    containers = containers or {}
    images = images or {}

    def fake(args, timeout=30):
        calls.append(args)
        key = args[0]
        if tuple(args[:2]) in fail or key in fail:
            return {"success": False, "stdout": "", "stderr": "boom", "returncode": 1}
        if key == "ps":
            rows = "\n".join(json.dumps({"Names": n, "Image":
                             c.get("Config", {}).get("Image", "")})
                             for n, c in containers.items())
            return {"success": True, "stdout": rows, "stderr": "", "returncode": 0}
        if key == "container" and args[1] == "inspect":
            c = containers.get(args[2])
            return ({"success": True, "stdout": json.dumps([c]), "stderr": "",
                     "returncode": 0} if c else
                    {"success": False, "stdout": "", "stderr": "no such", "returncode": 1})
        if key == "image" and args[1] == "inspect":
            i = images.get(args[2])
            return ({"success": True, "stdout": json.dumps([i]), "stderr": "",
                     "returncode": 0} if i else
                    {"success": False, "stdout": "", "stderr": "no such", "returncode": 1})
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(d, "_run_docker", fake)
    return calls


import json


class TestUpdateCheck:
    def test_reports_stale_and_current(self, test_client, auth_headers, monkeypatch):
        import docker_lxc_api as d
        containers = {
            "fresh": {"Image": "sha256:aaa", "Config": {"Image": "nginx:1"}},
            "stale": {"Image": "sha256:bbb", "Config": {"Image": "redis:7"}},
        }
        _docker_fake(monkeypatch, containers=containers)
        monkeypatch.setattr(d, "_remote_config_digest",
                            lambda img: {"nginx:1": "sha256:aaa",
                                         "redis:7": "sha256:ccc"}.get(img))
        r = test_client.get("/api/docker/update-check", headers=auth_headers)
        got = {c["name"]: c["update_available"] for c in r.json()["containers"]}
        assert got == {"fresh": False, "stale": True}

    def test_unknown_remote_is_null_not_guess(self, test_client, auth_headers,
                                              monkeypatch):
        import docker_lxc_api as d
        _docker_fake(monkeypatch, containers={
            "priv": {"Image": "sha256:aaa", "Config": {"Image": "private/img:1"}}})
        monkeypatch.setattr(d, "_remote_config_digest", lambda img: None)
        r = test_client.get("/api/docker/update-check", headers=auth_headers)
        assert r.json()["containers"][0]["update_available"] is None


class TestUpdate:
    def test_compose_managed_refused_with_hint(self, test_client, auth_headers,
                                               monkeypatch):
        _docker_fake(monkeypatch, containers={"web": {
            "Image": "sha256:aaa",
            "Config": {"Image": "nginx:1",
                       "Labels": {"com.docker.compose.project": "p"}}}})
        r = test_client.post("/api/docker/containers/web/update",
                             headers=auth_headers)
        assert r.status_code == 200 and r.json()["compose_managed"] is True

    def test_already_current_no_recreate(self, test_client, auth_headers,
                                         monkeypatch):
        import docker_lxc_api as d
        calls = _docker_fake(
            monkeypatch,
            containers={"web": {"Image": "sha256:aaa",
                                "Config": {"Image": "nginx:1", "Labels": {}}}},
            images={"nginx:1": {"Id": "sha256:aaa", "Config": {}}})
        monkeypatch.setattr(d, "_remote_config_digest", lambda img: "sha256:aaa")
        r = test_client.post("/api/docker/containers/web/update",
                             headers=auth_headers)
        assert r.status_code == 200 and r.json()["updated"] is False
        assert not any(c[0] == "rename" for c in calls)

    def test_recreate_preserves_config_and_removes_old(self, test_client,
                                                       auth_headers, monkeypatch):
        import docker_lxc_api as d
        info = {
            "Image": "sha256:OLD",
            "State": {"Running": True},
            "Config": {"Image": "nginx:1", "Labels": {},
                       "Env": ["A=1"], "Cmd": None, "Entrypoint": None},
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"},
                           "NetworkMode": "bridge",
                           "PortBindings": {"80/tcp": [{"HostPort": "8080"}]},
                           "Binds": ["/srv/data:/data"]},
            "Mounts": [{"Type": "volume", "Name": "webvol",
                        "Destination": "/var/lib/web"}],
        }
        calls = _docker_fake(monkeypatch,
                             containers={"web": info},
                             images={"nginx:1": {"Id": "sha256:NEW", "Config": {}}})
        monkeypatch.setattr(d, "_remote_config_digest", lambda img: "sha256:NEW")
        r = test_client.post("/api/docker/containers/web/update",
                             headers=auth_headers)
        assert r.status_code == 200 and r.json()["updated"] is True, r.text
        run = next(c for c in calls if c[0] == "run")
        joined = " ".join(run)
        for frag in ("--restart unless-stopped", "-e A=1", "-p 8080:80/tcp",
                     "-v /srv/data:/data", "-v webvol:/var/lib/web"):
            assert frag in joined, frag
        assert ["rename", "web", "web-forgeos-old"] in calls
        assert ["rm", "web-forgeos-old"] in calls

    def test_recreate_failure_rolls_back(self, test_client, auth_headers,
                                         monkeypatch):
        import docker_lxc_api as d
        info = {"Image": "sha256:OLD", "State": {"Running": True},
                "Config": {"Image": "nginx:1", "Labels": {}, "Env": [],
                           "Cmd": None, "Entrypoint": None},
                "HostConfig": {}, "Mounts": []}
        calls = _docker_fake(monkeypatch, containers={"web": info},
                             images={"nginx:1": {"Id": "sha256:NEW", "Config": {}}},
                             fail=("run",))
        monkeypatch.setattr(d, "_remote_config_digest", lambda img: "sha256:NEW")
        r = test_client.post("/api/docker/containers/web/update",
                             headers=auth_headers)
        assert r.status_code == 500 and "rolled back" in r.json()["detail"]
        assert ["rename", "web-forgeos-old", "web"] in calls   # restored
        assert ["start", "web"] in calls                       # restarted

    def test_missing_image_202_and_pull_started(self, test_client, auth_headers,
                                                monkeypatch):
        import docker_lxc_api as d
        info = {"Image": "sha256:OLD", "State": {"Running": True},
                "Config": {"Image": "nginx:1", "Labels": {}}, "HostConfig": {},
                "Mounts": []}
        _docker_fake(monkeypatch, containers={"web": info})   # image absent
        monkeypatch.setattr(d, "_remote_config_digest", lambda img: "sha256:NEW")
        started = []
        monkeypatch.setattr(d, "_start_pull", lambda img, bt: started.append(img))
        r = test_client.post("/api/docker/containers/web/update",
                             headers=auth_headers)
        assert r.status_code == 202 and r.json()["pulling"] is True
        assert started == ["nginx:1"]


class TestWipe:
    def test_wipe_sequence(self, test_client, auth_headers, monkeypatch):
        calls = _docker_fake(monkeypatch, containers={"web": {
            "Image": "sha256:aaa", "Config": {"Image": "nginx:1", "Labels": {}}}})
        r = test_client.post("/api/docker/wipe", headers=auth_headers,
                             json={"name": "web"})
        assert r.status_code == 200 and r.json()["image_removed"] is True
        assert ["rm", "-v", "web"] in calls
        assert ["rmi", "sha256:aaa"] in calls

    def test_wipe_unknown_404(self, test_client, auth_headers, monkeypatch):
        _docker_fake(monkeypatch)
        r = test_client.post("/api/docker/wipe", headers=auth_headers,
                             json={"name": "ghost"})
        assert r.status_code == 404


class TestRun:
    def test_validation_rejects_garbage(self, test_client, auth_headers,
                                        monkeypatch):
        _docker_fake(monkeypatch)
        bad = [
            {"name": "x", "image": "-rm"},
            {"name": "x", "image": "nginx", "ports": ["80;rm -rf /:80"]},
            {"name": "x", "image": "nginx", "env": ["1BAD=v"]},
            # ../etc is neither an absolute path nor a valid volume name
            {"name": "x", "image": "nginx", "volumes": ["../etc:/x"]},
            {"name": "x", "image": "nginx", "volumes": ["/srv/a:/b:rwx"]},
            {"name": "x", "image": "nginx", "restart": "sometimes"},
        ]
        for b in bad:
            r = test_client.post("/api/docker/run", headers=auth_headers, json=b)
            assert r.status_code == 400, b

    def test_duplicate_name_409(self, test_client, auth_headers, monkeypatch):
        _docker_fake(monkeypatch, containers={"web": {"Config": {}}})
        r = test_client.post("/api/docker/run", headers=auth_headers,
                             json={"name": "web", "image": "nginx:1"})
        assert r.status_code == 409

    def test_missing_image_202(self, test_client, auth_headers, monkeypatch):
        import docker_lxc_api as d
        _docker_fake(monkeypatch)
        started = []
        monkeypatch.setattr(d, "_start_pull", lambda img, bt: started.append(img))
        r = test_client.post("/api/docker/run", headers=auth_headers,
                             json={"name": "new", "image": "nginx:1"})
        assert r.status_code == 202 and started == ["nginx:1"]

    def test_create_builds_correct_args(self, test_client, auth_headers,
                                        monkeypatch):
        calls = _docker_fake(monkeypatch,
                             images={"nginx:1": {"Id": "sha256:x", "Config": {}}})
        r = test_client.post("/api/docker/run", headers=auth_headers, json={
            "name": "web", "image": "nginx:1", "restart": "always",
            "ports": ["8080:80"], "volumes": ["/srv/w:/data:ro"],
            "env": ["A=1"], "command": "nginx -g 'daemon off;'"})
        assert r.status_code == 200, r.text
        run = next(c for c in calls if c[0] == "run")
        joined = " ".join(run)
        for frag in ("--restart always", "-p 8080:80", "-v /srv/w:/data:ro",
                     "-e A=1", "nginx:1 nginx -g daemon off;"):
            assert frag in joined, (frag, joined)


# ──────────────────────────────────────────────────────────
# 0041 — apps_root settings, port intelligence, prunes
# ──────────────────────────────────────────────────────────


class TestDockerSettings:
    def test_get_returns_default(self, test_client, auth_headers):
        r = test_client.get("/api/docker/settings", headers=auth_headers)
        assert r.status_code == 200 and r.json()["apps_root"] == "/srv/apps"

    def test_put_validates_and_persists(self, test_client, auth_headers,
                                        monkeypatch, tmp_path):
        import docker_lxc_api as d
        for bad in ("relative/path", "/", "/etc", ""):
            r = test_client.put("/api/docker/settings", headers=auth_headers,
                                json={"apps_root": bad})
            assert r.status_code == 400, bad
        root = str(tmp_path / "apps")
        r = test_client.put("/api/docker/settings", headers=auth_headers,
                            json={"apps_root": root})
        assert r.status_code == 200
        try:
            assert (tmp_path / "apps").is_dir()          # mkdir'd
            g = test_client.get("/api/docker/settings", headers=auth_headers)
            assert g.json()["apps_root"] == root         # persisted
        finally:
            test_client.put("/api/docker/settings", headers=auth_headers,
                            json={"apps_root": "/srv/apps"})

    def test_put_admin_only(self, test_client, user_headers):
        r = test_client.put("/api/docker/settings", headers=user_headers,
                            json={"apps_root": "/srv/x"})
        assert r.status_code == 403

    def test_migration_v9_to_v10(self):
        import forgeos_config as fc
        d = fc.migrate({"version": 9})
        assert d["version"] == 10 and "docker" in d


class TestPortIntelligence:
    def test_free_ports_skip_used(self, test_client, auth_headers, monkeypatch):
        import docker_lxc_api as d
        monkeypatch.setattr(d, "_used_host_ports", lambda: {8080, 8081, 9000})
        r = test_client.get("/api/docker/ports/free?ports=8080,9000,7000",
                            headers=auth_headers)
        assert r.json()["ports"] == {"8080": 8082, "9000": 9001, "7000": 7000}

    def test_free_ports_no_duplicate_suggestions(self, test_client, auth_headers,
                                                 monkeypatch):
        import docker_lxc_api as d
        monkeypatch.setattr(d, "_used_host_ports", lambda: {8080})
        r = test_client.get("/api/docker/ports/free?ports=8080,8081",
                            headers=auth_headers)
        got = r.json()["ports"]
        # 8080 -> 8081 would collide with the second request; must not
        assert len(set(got.values())) == 2

    def test_run_rejects_conflicting_port_with_suggestion(self, test_client,
                                                          auth_headers, monkeypatch):
        import docker_lxc_api as d
        _docker_fake(monkeypatch,
                     images={"nginx:1": {"Id": "sha256:x", "Config": {}}})
        monkeypatch.setattr(d, "_used_host_ports", lambda: {8080, 8081})
        r = test_client.post("/api/docker/run", headers=auth_headers,
                             json={"name": "w2", "image": "nginx:1",
                                   "ports": ["8080:80"]})
        assert r.status_code == 409
        assert "8082" in r.json()["detail"]      # concrete suggestion

    def test_used_ports_include_stopped_containers(self, monkeypatch):
        """A stopped container's ports return the moment it starts — they are
        NOT free."""
        import docker_lxc_api as d
        rows = ('{"Names":"a","Ports":"0.0.0.0:8080->80/tcp"}\n'
                '{"Names":"b","Ports":"[::]:9090->90/tcp"}')
        def fake(args, timeout=30):
            assert "-a" in args                   # must list stopped ones too
            return {"success": True, "stdout": rows, "stderr": "", "returncode": 0}
        monkeypatch.setattr(d, "_run_docker", fake)
        monkeypatch.setattr(d.subprocess, "run",
                            lambda *a, **k: type("R", (), {"stdout": ""})())
        used = d._used_host_ports()
        assert {8080, 9090} <= used


class TestPruneContainers:
    def test_route_and_gate(self, test_client, auth_headers, user_headers,
                            monkeypatch):
        calls = _docker_fake(monkeypatch)
        assert test_client.post("/api/docker/prune/containers",
                                headers=user_headers).status_code == 403
        r = test_client.post("/api/docker/prune/containers", headers=auth_headers)
        assert r.status_code == 200
        assert ["container", "prune", "-f"] in calls
