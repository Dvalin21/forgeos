"""
Tests for filedb_api.py — ForgeFileDB REST API proxy.
"""

from __future__ import annotations

import pytest


class TestFiledbMockMode:
    """ForgeFileDB API in mock mode (no daemon needed)."""

    @pytest.fixture(autouse=True)
    def _enable_mock_mode(self, monkeypatch):
        monkeypatch.setenv("MOCK_FILEDB", "true")

    def test_status_returns_mock_data(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/status", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["daemon_running"] is True
        assert data["mock_mode"] is True

    def test_clients_returns_list(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/clients", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "clients" in data
        assert len(data["clients"]) == 3

    def test_databases_returns_grouped(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/databases", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "databases" in data
        assert len(data["databases"]) > 0

    def test_locks_returns_lock_info(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/locks", headers=auth_headers)
        assert r.status_code == 200
        # In mock mode, locks returns status with lock_details

    def test_snapshots_returns_list(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/snapshots", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "snapshots" in data

    def test_snapshots_filtered_by_dir(self, test_client, auth_headers):
        r = test_client.get(
            "/api/filedb/snapshots?db_dir=/data/databases/finance",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        for snap in data["snapshots"]:
            assert snap["db_dir"] == "/data/databases/finance"

    def test_create_snapshot(self, test_client, auth_headers):
        r = test_client.post(
            "/api/filedb/snapshots",
            json={"db_dir": "/data/databases/finance"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

    def test_create_snapshot_no_dir(self, test_client, auth_headers):
        r = test_client.post(
            "/api/filedb/snapshots",
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_restore_snapshot(self, test_client, auth_headers):
        r = test_client.post(
            "/api/filedb/restore",
            json={"snap_ts": "20260428T153000", "db_dir": "/data/databases/finance"},
            headers=auth_headers,
        )
        assert r.status_code == 200

    def test_restore_snapshot_no_ts(self, test_client, auth_headers):
        r = test_client.post(
            "/api/filedb/restore",
            json={"db_dir": "/data/databases/finance"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_settings_get(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/settings", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "snapshot_debounce_sec" in data

    def test_settings_update(self, test_client, auth_headers):
        r = test_client.put(
            "/api/filedb/settings",
            json={"snapshot_debounce_sec": 15},
            headers=auth_headers,
        )
        assert r.status_code == 200

    def test_settings_update_unknown_keys_ignored(self, test_client, auth_headers):
        """Only whitelisted keys should pass through."""
        r = test_client.put(
            "/api/filedb/settings",
            json={"evil_key": "rm -rf /", "snapshot_debounce_sec": 30},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "evil_key" not in data.get("settings", {})

    def test_log_returns_lines(self, test_client, auth_headers):
        r = test_client.get("/api/filedb/log?lines=3", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "lines" in data

    def test_auth_required(self, test_client):
        """Without auth header, all endpoints should return 401."""
        r = test_client.get("/api/filedb/status")
        assert r.status_code == 401 or r.status_code == 403


class TestFiledbProductionMode:
    """ForgeFileDB API in production mode (daemon may or may not be running).

    Note: because Python caches module imports, MOCK_MODE is evaluated
    at import time. To test production mode we must clear the module
    cache so filedb_api re-evaluates with MOCK_FILEDB=false.
    """

    @pytest.fixture(autouse=True)
    def _disable_mock_mode(self, monkeypatch, request):
        import sys

        # Clear cached modules so filedb_api re-imports with new env
        for modname in list(sys.modules.keys()):
            if "filedb_api" in modname or "forgeos_api" in modname:
                del sys.modules[modname]
        monkeypatch.setenv("MOCK_FILEDB", "false")
        monkeypatch.setenv("FILEDB_DAEMON_URL", "http://127.0.0.1:12010")
        # Clear cached api module reference on test_client fixture
        # (app fixture will re-import via importlib)
        modname = "forgeos_api_module"
        if modname in sys.modules:
            del sys.modules[modname]

    def test_status_returns_503_when_daemon_down(self, test_client, auth_headers):
        """Without a running daemon, production mode returns 503."""
        r = test_client.get("/api/filedb/status", headers=auth_headers)
        assert r.status_code == 503
        assert "daemon" in r.json()["detail"].lower()


class TestFiledbProductionStatus:
    """Production path: the real daemon's /api/status omits daemon_running, so
    the proxy must inject it (reaching the daemon proves it is up). Regression
    for the 'daemon running but UI shows stopped' bug."""

    @pytest.fixture(autouse=True)
    def _disable_mock(self, monkeypatch):
        monkeypatch.setenv("MOCK_FILEDB", "false")

    def _patch_daemon(self, monkeypatch, payload):
        import filedb_api

        async def fake_proxy(path):
            return dict(payload)

        monkeypatch.setattr(filedb_api, "_proxy_get", fake_proxy)

    def test_status_injects_daemon_running(self, test_client, auth_headers, monkeypatch):
        # exact shape the real daemon returns — note: NO daemon_running key
        self._patch_daemon(monkeypatch, {
            "connected_clients": 0, "open_databases": 2, "snapshots_today": 0,
            "total_snapshots": 5, "total_opens": 0, "total_conflicts": 0,
            "clients": [], "lock_details": {},
        })
        r = test_client.get("/api/filedb/status", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["daemon_running"] is True      # injected by the proxy
        assert data["open_databases"] == 2          # passthrough preserved

    def test_locks_injects_daemon_running(self, test_client, auth_headers, monkeypatch):
        self._patch_daemon(monkeypatch, {"connected_clients": 1,
                                         "lock_details": {"files": {}}})
        r = test_client.get("/api/filedb/locks", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["daemon_running"] is True
