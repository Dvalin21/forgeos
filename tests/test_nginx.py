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


@pytest.fixture
def nginx_apply(monkeypatch):
    """Inject a fake apply so tests persist to the isolated config-DB without
    writing /etc/nginx or touching systemctl. Records each applied config."""
    import nginx_api
    import forgeos_config as fc
    applied = []
    nginx_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
    yield applied
    nginx_api.set_apply(None)


# ──────────────────────────────────────────────────────────
# GET /api/nginx/vhosts  (config-DB backed)
# ──────────────────────────────────────────────────────────


class TestNginxVhosts:

    def test_auth_required(self, test_client):
        assert test_client.get("/api/nginx/vhosts").status_code == 401

    def test_returns_empty_when_no_vhosts(self, test_client, auth_headers):
        r = test_client.get("/api/nginx/vhosts", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["vhosts"], list)

    def test_lists_config_db_vhosts(self, test_client, auth_headers, nginx_apply):
        test_client.post("/api/nginx/vhost",
                         json={"name": "app", "domain": "app.lan", "upstream_port": 8080},
                         headers=auth_headers)
        names = [v["name"] for v in
                 test_client.get("/api/nginx/vhosts", headers=auth_headers).json()["vhosts"]]
        assert "app" in names


# ──────────────────────────────────────────────────────────
# POST /api/nginx/vhost  (config-DB + generator)
# ──────────────────────────────────────────────────────────


class TestAddVhost:

    def test_auth_required(self, test_client):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "t", "domain": "t.com", "upstream_port": 80})
        assert r.status_code == 401

    def test_forbids_non_admin(self, test_client, user_headers):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "t", "domain": "t.com", "upstream_port": 80},
                             headers=user_headers)
        assert r.status_code == 403

    def test_creates_with_advanced_fields(self, test_client, auth_headers, nginx_apply):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "app", "domain": "app.lan", "upstream_port": 8080,
                                   "websocket": True, "hsts": False, "gzip": True,
                                   "client_max_body_size": "50m",
                                   "block_common_exploits": True,
                                   "allow_ips": ["10.0.0.0/24"]},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        v = r.json()["vhost"]
        assert v["websocket"] is True and v["gzip"] is True and v["hsts"] is False
        assert v["client_max_body_size"] == "50m"
        assert v["allow_ips"] == ["10.0.0.0/24"]
        assert len(nginx_apply) == 1          # generator apply invoked once

    def test_rejects_invalid_port(self, test_client, auth_headers, nginx_apply):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "t", "domain": "t.com", "upstream_port": 99999},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_bad_name(self, test_client, auth_headers, nginx_apply):
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "bad name!", "domain": "t.com", "upstream_port": 80},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_domain_injection(self, test_client, auth_headers, nginx_apply):
        # a domain that could break out of server_name must be rejected
        r = test_client.post("/api/nginx/vhost",
                             json={"name": "evil",
                                   "domain": "x; } location / { deny all; }",
                                   "upstream_port": 80},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_duplicate(self, test_client, auth_headers, nginx_apply):
        body = {"name": "dup", "domain": "dup.lan", "upstream_port": 80}
        assert test_client.post("/api/nginx/vhost", json=body,
                                headers=auth_headers).status_code == 200
        assert test_client.post("/api/nginx/vhost", json=body,
                                headers=auth_headers).status_code == 409


# ──────────────────────────────────────────────────────────
# PUT /api/nginx/vhost/{name}
# ──────────────────────────────────────────────────────────


class TestUpdateVhost:

    def test_forbids_non_admin(self, test_client, user_headers):
        r = test_client.put("/api/nginx/vhost/app",
                            json={"domain": "app.lan", "upstream_port": 80},
                            headers=user_headers)
        assert r.status_code == 403

    def test_updates_existing(self, test_client, auth_headers, nginx_apply):
        test_client.post("/api/nginx/vhost",
                         json={"name": "app", "domain": "app.lan", "upstream_port": 8080},
                         headers=auth_headers)
        r = test_client.put("/api/nginx/vhost/app",
                            json={"domain": "app.lan", "upstream_port": 9090, "gzip": True},
                            headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["vhost"]["upstream_port"] == 9090
        assert r.json()["vhost"]["gzip"] is True

    def test_missing_is_404(self, test_client, auth_headers, nginx_apply):
        r = test_client.put("/api/nginx/vhost/nope",
                            json={"domain": "n.lan", "upstream_port": 80},
                            headers=auth_headers)
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────
# DELETE /api/nginx/vhost/{name}
# ──────────────────────────────────────────────────────────


class TestRemoveVhost:

    def test_auth_required(self, test_client):
        assert test_client.delete("/api/nginx/vhost/test").status_code == 401

    def test_refuses_to_delete_ui_vhost(self, test_client, auth_headers):
        # lockout protection — the UI's own front door is never deletable
        r = test_client.delete("/api/nginx/vhost/forgeos-ui", headers=auth_headers)
        assert r.status_code == 403

    def test_removes_existing(self, test_client, auth_headers, nginx_apply):
        test_client.post("/api/nginx/vhost",
                         json={"name": "gone", "domain": "gone.lan", "upstream_port": 80},
                         headers=auth_headers)
        r = test_client.delete("/api/nginx/vhost/gone", headers=auth_headers)
        assert r.status_code == 200 and r.json()["ok"] is True
        names = [v["name"] for v in
                 test_client.get("/api/nginx/vhosts", headers=auth_headers).json()["vhosts"]]
        assert "gone" not in names

    def test_missing_is_404(self, test_client, auth_headers, nginx_apply):
        r = test_client.delete("/api/nginx/vhost/nope", headers=auth_headers)
        assert r.status_code == 404


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


class TestRawConfigRollback:
    """nginx_save_raw must NOT leave a broken config persisted if the live
    nginx -t fails after writing (review Finding #1)."""

    def test_live_test_failure_restores_previous_config(self, test_client, auth_headers, tmp_path, monkeypatch):
        import nginx_api
        conf = tmp_path / "nginx.conf"
        conf.write_text("# GOOD PREVIOUS CONFIG\n")
        monkeypatch.setattr(nginx_api, "NGINX_CONF", conf)
        # temp-file test passes; live test FAILS
        calls = {"n": 0}
        def fake_run(args, timeout=None):
            # first call: nginx -t -c <tmp>  -> success
            # second call: nginx -t (live)   -> failure
            calls["n"] += 1
            if calls["n"] == 1:
                return "nginx: configuration file test is successful"
            return "nginx: [emerg] bad directive\nconfiguration file test failed"
        monkeypatch.setattr(nginx_api, "_run_args", fake_run)
        r = test_client.put("/api/nginx/raw", headers=auth_headers,
                            json={"config": "BROKEN CONFIG THAT FAILS LIVE TEST"})
        assert r.status_code == 400
        # the previous good config must be restored, NOT the broken one
        assert conf.read_text() == "# GOOD PREVIOUS CONFIG\n"

    def test_live_test_success_persists_and_reloads(self, test_client, auth_headers, tmp_path, monkeypatch):
        import nginx_api
        conf = tmp_path / "nginx.conf"
        conf.write_text("# old\n")
        monkeypatch.setattr(nginx_api, "NGINX_CONF", conf)
        reloaded = {"yes": False}
        def fake_run(args, timeout=None):
            if args[:2] == ["systemctl", "reload"]:
                reloaded["yes"] = True
                return ""
            return "nginx: configuration file test is successful"
        monkeypatch.setattr(nginx_api, "_run_args", fake_run)
        r = test_client.put("/api/nginx/raw", headers=auth_headers,
                            json={"config": "# NEW GOOD CONFIG\n"})
        assert r.status_code == 200, r.text
        assert conf.read_text() == "# NEW GOOD CONFIG\n"   # persisted
        assert reloaded["yes"]                              # reloaded
