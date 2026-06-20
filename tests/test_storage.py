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

    def test_returns_pools_from_config_db(self, test_client, auth_headers, tmp_path, monkeypatch):
        # Pools come from the config-DB now — ONE entry per pool (the old path
        # listed a raid pool once per device, causing the double-display bug).
        import forgeos_config as fc
        cfgfile = tmp_path / "config.json"
        monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
        monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
        cfg = fc.ForgeOSConfig()
        cfg.storage.pools.append(fc.StoragePool(
            name="tank", raid_level="raid1",
            devices=["/dev/sdb", "/dev/sdd"], mountpoint="/srv/nas/tank",
            uuid="abc-123"))
        fc.save(cfg, cfgfile)

        r = test_client.get("/api/storage/pools", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # raid1 across 2 devices, but EXACTLY ONE pool entry (no doubling)
        assert len(data["pools"]) == 1
        assert data["pools"][0]["name"] == "tank"
        assert data["pools"][0]["devices"] == ["/dev/sdb", "/dev/sdd"]


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
    VALID = {"name": "testpool", "level": "raid1", "drives": ["sda", "sdc"]}

    def test_auth_required(self, test_client):
        r = test_client.post("/api/storage/pool", json=self.VALID)
        assert r.status_code == 401

    def test_rejects_non_admin(self, test_client):
        from forgeos_auth import create_token
        token = create_token("regular", "user")
        r = test_client.post("/api/storage/pool", json=self.VALID,
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def _fake_disks(self, monkeypatch, system="sdc"):
        import storage_api
        import forgeos_diskprep as dp

        def make(name):
            return dp.DiskInfo(name=name, path=f"/dev/{name}",
                               is_system=(name == system))
        disks = [make("sda"), make("sdc"), make("sdd")]
        monkeypatch.setattr(storage_api.dp, "inspect_disks", lambda *a, **k: disks)
        monkeypatch.setattr(storage_api.dp, "_require_tools", lambda *a: None)
        return disks

    def test_refuses_system_disk(self, test_client, auth_headers, monkeypatch):
        # the GUARD: trying to pool the system disk (sdc) must be refused 400
        self._fake_disks(monkeypatch, system="sdc")
        r = test_client.post("/api/storage/pool",
                             json={"name": "tank", "level": "raid1", "drives": ["sda", "sdc"]},
                             headers=auth_headers)
        assert r.status_code == 400
        assert "system" in r.json()["detail"].lower()

    def test_rejects_short_name(self, test_client, auth_headers, monkeypatch):
        self._fake_disks(monkeypatch)
        r = test_client.post("/api/storage/pool",
                             json={"name": "x", "level": "raid1", "drives": ["sda", "sdd"]},
                             headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_too_few_drives(self, test_client, auth_headers, monkeypatch):
        self._fake_disks(monkeypatch)
        r = test_client.post("/api/storage/pool",
                             json={"name": "tank", "level": "raid10", "drives": ["sda", "sdd"]},
                             headers=auth_headers)
        assert r.status_code == 400  # raid10 needs 4


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
