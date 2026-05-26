"""
Tests for ForgeOS storage API endpoints — pools, drives, snapshots.

Validates:
  1. Input validation (400 on bad inputs)
  2. Auth enforcement (401/403 without proper token/role)
  3. System command integration (mocked subprocess calls)

The test_client fixture loads forgeos-api.py fresh via importlib per fixture
call. Monkeypatch subprocess directly before the client routes to the handler.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────


def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    """Return a subprocess.run mock that succeeds."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ──────────────────────────────────────────────────────────
# GET /api/storage/pools
# ──────────────────────────────────────────────────────────


class TestStoragePools:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/storage/pools")
        assert r.status_code == 401

    def test_returns_pools(self, test_client, auth_headers, monkeypatch):
        mock_pool_json = json.dumps({
            "pools": [{"name": "main", "level": "raid5",
                       "size_bytes": 4e12, "used_bytes": 1e12,
                       "status": "clean", "drives": 3}],
            "unassigned": [],
        })
        # _run_args calls subprocess.check_output — patch it directly
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda *a, **kw: mock_pool_json.encode(),
        )
        r = test_client.get("/api/storage/pools", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "pools" in data
        assert len(data["pools"]) == 1
        assert data["pools"][0]["name"] == "main"


# ──────────────────────────────────────────────────────────
# GET /api/storage/drives
# ──────────────────────────────────────────────────────────


class TestStorageDrives:

    def test_auth_required(self, test_client):
        r = test_client.get("/api/storage/drives")
        assert r.status_code == 401

    def test_returns_drives(self, test_client, auth_headers, monkeypatch):
        mock_lsblk = json.dumps({
            "blockdevices": [
                {"name": "sda", "size": "2.0T", "type": "disk",
                 "model": "ATA TestDrive", "tran": "sata"},
                {"name": "sdb", "size": "2.0T", "type": "disk",
                 "model": "ATA TestDrive", "tran": "sata"},
            ]
        })
        mock_smart = json.dumps({"json_format_version": [1, 0],
                                 "device": {"name": "/dev/sda"},
                                 "smart_status": {"passed": True}})
        mock_temp = json.dumps({"temperature": {"current": 35}})
        call_count = [0]

        def mock_check_output(cmd, **kw):
            call_count[0] += 1
            cmd_s = " ".join(cmd) if isinstance(cmd, list) else cmd
            if "lsblk" in cmd_s:
                return mock_lsblk.encode()
            if "smartctl" in cmd_s:
                return mock_smart.encode() if call_count[0] % 2 == 1 else mock_temp.encode()
            return b""

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        r = test_client.get("/api/storage/drives", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "drives" in data
        assert len(data["drives"]) == 2


# ──────────────────────────────────────────────────────────
# POST /api/storage/pool
# ──────────────────────────────────────────────────────────


class TestCreatePool:
    VALID = {"name": "testpool", "level": 5,
             "drives": ["/dev/sda", "dev/sdb", "/dev/sdc"]}

    def test_auth_required(self, test_client):
        r = test_client.post("/api/storage/pool", json=self.VALID)
        assert r.status_code == 401

    def test_rejects_short_name(self, test_client, auth_headers):
        r = test_client.post(
            "/api/storage/pool",
            json={"name": "x", "level": 5, "drives": ["/dev/sda", "/dev/sdb"]},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_rejects_invalid_raid_level(self, test_client, auth_headers):
        r = test_client.post(
            "/api/storage/pool",
            json={"name": "pool", "level": 99, "drives": ["/dev/sda", "/dev/sdb"]},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_rejects_single_drive(self, test_client, auth_headers):
        r = test_client.post(
            "/api/storage/pool",
            json={"name": "pool", "level": 1, "drives": ["/dev/sda"]},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_sanitizes_drive_paths(self, test_client, auth_headers, monkeypatch):
        seen_cmds = []

        def mock_run(cmd, **kw):
            seen_cmds.append(" ".join(cmd))
            return _mock_subprocess_run(returncode=0)

        monkeypatch.setattr("subprocess.run", mock_run)
        r = test_client.post(
            "/api/storage/pool",
            json={"name": "pool1", "level": 5,
                  "drives": ["/dev/sda", "/dev/sdb;rm -rf /"]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        # Verify shell metacharacters are stripped; "rm" as substring is fine
        cmd_str = seen_cmds[-1] if seen_cmds else ""
        assert ";" not in cmd_str
        assert "|" not in cmd_str
        assert "`" not in cmd_str
        assert "$" not in cmd_str

    def test_rejects_non_admin(self, test_client, monkeypatch):
        from forgeos_auth import create_token
        token = create_token("regular", "user")
        r = test_client.post(
            "/api/storage/pool", json=self.VALID,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────
# POST /api/storage/drive
# ──────────────────────────────────────────────────────────


class TestAddDrive:
    VALID = {"device": "/dev/sdd", "pool": "main"}

    def test_auth_required(self, test_client):
        r = test_client.post("/api/storage/drive", json=self.VALID)
        assert r.status_code == 401

    def test_rejects_missing_pool(self, test_client, auth_headers):
        r = test_client.post(
            "/api/storage/drive", json={"device": "/dev/sdd"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_rejects_missing_device(self, test_client, auth_headers):
        r = test_client.post(
            "/api/storage/drive", json={"pool": "main"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_sends_to_mdadm(self, test_client, auth_headers, monkeypatch):
        seen_cmds = []

        def mock_run(cmd, **kw):
            seen_cmds.append(cmd)
            return _mock_subprocess_run(returncode=0)

        monkeypatch.setattr("subprocess.run", mock_run)
        r = test_client.post(
            "/api/storage/drive",
            json={"device": "/dev/sdd", "pool": "main"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert any("mdadm" in str(c) for c in seen_cmds)

    def test_rejects_non_admin(self, test_client, monkeypatch):
        from forgeos_auth import create_token
        token = create_token("regular", "user")
        r = test_client.post(
            "/api/storage/drive", json=self.VALID,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────
# GET/POST /api/storage/snapshot
# ──────────────────────────────────────────────────────────


class TestSnapshots:

    def test_list_auth(self, test_client):
        r = test_client.get("/api/storage/snapshots")
        assert r.status_code == 401

    def test_create_auth(self, test_client):
        r = test_client.post(
            "/api/storage/snapshot",
            json={"pool": "main", "description": "test"},
        )
        assert r.status_code == 401

    def test_list_with_pool(self, test_client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda *a, **kw: b"",
        )
        r = test_client.get("/api/storage/snapshots?pool=main", headers=auth_headers)
        assert r.status_code in (200, 422)

    def test_create_dispatches_snapper(self, test_client, auth_headers, monkeypatch):
        def mock_run(cmd, **kw):
            assert "snapper" in str(cmd)
            return _mock_subprocess_run(returncode=0)

        monkeypatch.setattr("subprocess.run", mock_run)
        r = test_client.post(
            "/api/storage/snapshot",
            json={"pool": "main", "description": "pre-upgrade"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_create_no_pool_runs_all(self, test_client, auth_headers, monkeypatch):
        """When pool is empty, snapshot runs on all snapper configs."""
        call_count = [0]

        def mock_check_output(cmd, **kw):
            call_count[0] += 1
            # First call (list-configs) returns string (text=True in _run_args)
            if call_count[0] == 1:
                return "Config\ndocker\n"
            return ""

        def mock_run(cmd, **kw):
            return _mock_subprocess_run(returncode=0)

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        monkeypatch.setattr("subprocess.run", mock_run)
        r = test_client.post(
            "/api/storage/snapshot",
            json={"pool": "", "description": "nightly"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
