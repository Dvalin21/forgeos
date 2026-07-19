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

    def test_sends_to_btrfs_device_add(self, test_client, auth_headers, tmp_path, monkeypatch):
        # Add now targets btrfs (device add on the mountpoint), not mdadm —
        # the pool must exist and be mounted first.
        import storage_api, forgeos_config as fc
        cfgfile = tmp_path / "config.json"
        monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
        monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
        cfg = fc.ForgeOSConfig()
        cfg.storage.pools.append(fc.StoragePool(
            name="main", raid_level="raid1", devices=["/dev/sdb"],
            mountpoint=str(tmp_path / "mnt"), uuid="u1"))
        fc.save(cfg, cfgfile)
        monkeypatch.setattr(storage_api.Path, "is_mount", lambda self: True)
        seen = []
        def mock_run(cmd, **kw):
            seen.append(cmd)
            return _mock_subprocess_run(returncode=0)
        monkeypatch.setattr(storage_api.subprocess, "run", mock_run)
        r = test_client.post("/api/storage/drive",
                             json={"device": "sdd", "pool": "main"},
                             headers=auth_headers)
        assert r.status_code == 200
        assert any("btrfs" in str(c) and "device" in str(c) for c in seen)
        assert not any("mdadm" in str(c) for c in seen)

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


class TestStorageDf:
    """Capacity/volumes endpoint: ONE row per mountpoint, regardless of how
    many times the same filesystem is reflected in the service's mount table.
    """

    DF_TABLE = (
        "Filesystem 1B-blocks Used Available Use% Mounted on\n"
        "/dev/sdb 34359738368 5914624 33276559360 1% /srv/nas/tank\n"
    )

    def test_auth_required(self, test_client):
        assert test_client.get("/api/storage/df").status_code == 401

    def test_dedupes_namespace_double_mount(self, test_client, auth_headers, monkeypatch):
        # Regression: ProtectSystem=strict + ReadWritePaths=/srv reflects the
        # btrfs submount twice in the service namespace, so findmnt returns two
        # identical lines for ONE filesystem. The endpoint must collapse to one.
        def mock_check_output(args, **kwargs):
            if "findmnt" in args:
                return "/srv/nas/tank /dev/sdb\n/srv/nas/tank /dev/sdb\n"
            if "df" in args:
                return self.DF_TABLE
            return ""

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        r = test_client.get("/api/storage/df", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1                      # not 2
        assert data[0]["mount"] == "/srv/nas/tank"
        assert data[0]["total"] == 34359738368
        assert data[0]["used"] == 5914624

    def test_keeps_distinct_mountpoints(self, test_client, auth_headers, monkeypatch):
        # Dedup must not over-collapse: two real, different mounts stay two rows.
        def mock_check_output(args, **kwargs):
            if "findmnt" in args:
                return "/srv/nas/tank /dev/sdb\n/srv/nas/media /dev/sdc\n"
            if "df" in args:
                mp = args[-1]
                dev = "/dev/sdb" if "tank" in mp else "/dev/sdc"
                return (
                    "Filesystem 1B-blocks Used Available Use% Mounted on\n"
                    f"{dev} 100 10 90 10% {mp}\n"
                )
            return ""

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        r = test_client.get("/api/storage/df", headers=auth_headers)
        assert r.status_code == 200
        assert sorted(x["mount"] for x in r.json()) == ["/srv/nas/media", "/srv/nas/tank"]

    def test_single_mount_unchanged(self, test_client, auth_headers, monkeypatch):
        # The common case (one findmnt line) still returns exactly one row.
        def mock_check_output(args, **kwargs):
            if "findmnt" in args:
                return "/srv/nas/tank /dev/sdb\n"
            if "df" in args:
                return self.DF_TABLE
            return ""

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        r = test_client.get("/api/storage/df", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestBtrfsDriveActions:
    """The four drive/pool mutation endpoints must issue BTRFS commands, not
    mdadm. The bug: create made btrfs pools but add/replace/scrub targeted
    /dev/md/<pool>, which never exists for btrfs — every one failed on a real
    (btrfs) pool. These tests assert the correct command reaches the shell.
    """
    import types

    def _btrfs_pool(self, tmp_path, monkeypatch):
        import forgeos_config as fc
        cfgfile = tmp_path / "config.json"
        monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
        monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
        cfg = fc.ForgeOSConfig()
        cfg.storage.pools.append(fc.StoragePool(
            name="tank", raid_level="raid1",
            devices=["/dev/sdb", "/dev/sdd"],
            mountpoint=str(tmp_path / "mnt"), uuid="abc-123"))
        fc.save(cfg, cfgfile)
        # pretend the mountpoint is a real mount so _pool_mount passes
        import storage_api
        monkeypatch.setattr(storage_api.Path, "is_mount", lambda self: True)
        return str(tmp_path / "mnt")

    def _capture_run(self, monkeypatch, module):
        calls = []
        def fake(args, timeout=15, **k):
            calls.append(args)
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(module, "_run", fake)
        return calls

    def test_rebuild_runs_btrfs_scrub(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_pages_api
        mount = self._btrfs_pool(tmp_path, monkeypatch)
        calls = self._capture_run(monkeypatch, forgeos_pages_api)
        r = test_client.post("/api/storage/pool/rebuild",
                             json={"pool": "tank"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert calls == [["btrfs", "scrub", "start", mount]]
        assert not any("mdadm" in c for c in calls)

    def test_replace_present_disk_runs_btrfs_replace(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_pages_api
        mount = self._btrfs_pool(tmp_path, monkeypatch)
        calls = self._capture_run(monkeypatch, forgeos_pages_api)
        # old device present on disk
        monkeypatch.setattr(forgeos_pages_api.Path, "exists", lambda self: True)
        r = test_client.post("/api/storage/drive/replace",
                             json={"pool": "tank", "old": "sdb", "new": "sde"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        assert calls[0] == ["btrfs", "replace", "start", "-B",
                            "/dev/sdb", "/dev/sde", mount]

    def test_replace_missing_disk_uses_devid_and_r(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_pages_api
        mount = self._btrfs_pool(tmp_path, monkeypatch)
        calls = self._capture_run(monkeypatch, forgeos_pages_api)
        # numeric 'old' = devid path for a missing disk -> -r rebuild
        r = test_client.post("/api/storage/drive/replace",
                             json={"pool": "tank", "old": "1", "new": "sde"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        assert calls[0] == ["btrfs", "replace", "start", "-B",
                            "-r", "1", "/dev/sde", mount]

    def test_fail_endpoint_refuses_with_guidance(self, test_client, auth_headers):
        # btrfs has no 'fail' step; endpoint should 409 with guidance, not run mdadm
        r = test_client.post("/api/storage/drive/fail",
                             json={"pool": "tank", "device": "sdb"},
                             headers=auth_headers)
        assert r.status_code == 409

    def test_add_drive_runs_btrfs_device_add(self, test_client, auth_headers, tmp_path, monkeypatch):
        import storage_api
        mount = self._btrfs_pool(tmp_path, monkeypatch)
        calls = []
        def fake_run(args, capture_output=True, text=True, timeout=60, **k):
            calls.append(args)
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(storage_api.subprocess, "run", fake_run)
        r = test_client.post("/api/storage/drive",
                             json={"pool": "tank", "device": "sde"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        assert calls == [["btrfs", "device", "add", "-f", "/dev/sde", mount]]

    def test_unmounted_pool_rejected(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_pages_api, storage_api, forgeos_config as fc
        cfgfile = tmp_path / "config.json"
        monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
        monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
        cfg = fc.ForgeOSConfig()
        cfg.storage.pools.append(fc.StoragePool(
            name="tank", raid_level="raid1", devices=["/dev/sdb"],
            mountpoint=str(tmp_path / "mnt"), uuid="x"))
        fc.save(cfg, cfgfile)
        monkeypatch.setattr(storage_api.Path, "is_mount", lambda self: False)
        r = test_client.post("/api/storage/pool/rebuild",
                             json={"pool": "tank"}, headers=auth_headers)
        assert r.status_code == 409

    def test_unknown_pool_404(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_config as fc
        cfgfile = tmp_path / "config.json"
        monkeypatch.setenv("FORGEOS_CONFIG_JSON", str(cfgfile))
        monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
        fc.save(fc.ForgeOSConfig(), cfgfile)
        r = test_client.post("/api/storage/pool/rebuild",
                             json={"pool": "ghost"}, headers=auth_headers)
        assert r.status_code == 404
