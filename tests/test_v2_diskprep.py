"""Tests for forgeos_diskprep — the disk safety guards.

These are the most important tests in the storage slice: they prove ForgeOS
REFUSES to destroy the system disk, mounted disks, or array members, from any
path. The disk near-miss (nearly mkfs'd the root disk) is what these prevent.
"""
from __future__ import annotations

import json

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_diskprep as dp  # noqa: E402


@pytest.fixture
def stub_tools(monkeypatch):
    # sandbox has no mkfs.btrfs; bypass the tool-presence check for logic tests
    monkeypatch.setattr(dp, "_require_tools", lambda *a: None)



def _disk(name, **kw):
    return dp.DiskInfo(name=name, path=f"/dev/{name}", **kw)


# ---- guard_destructible: the core refusals ----

def test_system_disk_never_destructible():
    d = _disk("sdb", is_system=True)
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.guard_destructible(d)
    # even with force, the system disk is untouchable
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.guard_destructible(d, force=True)


def test_mounted_disk_refused():
    d = _disk("sda", mounted=True, mountpoints=["/mnt/backup"])
    with pytest.raises(dp.DiskGuardError, match="mounted"):
        dp.guard_destructible(d)


def test_array_member_refused():
    d = _disk("sdc", in_array=True)
    with pytest.raises(dp.DiskGuardError, match="array"):
        dp.guard_destructible(d)


def test_disk_with_fs_refused_without_force():
    d = _disk("sdd", has_filesystem=True)
    with pytest.raises(dp.DiskGuardError, match="force"):
        dp.guard_destructible(d)


def test_disk_with_fs_allowed_with_force():
    d = _disk("sdd", has_filesystem=True)
    dp.guard_destructible(d, force=True)   # should NOT raise


def test_blank_disk_allowed():
    d = _disk("sde")
    dp.guard_destructible(d)               # blank → allowed
    assert d.blank is True


def test_force_cannot_override_system_even_with_other_flags():
    d = _disk("sdb", is_system=True, has_filesystem=True)
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.guard_destructible(d, force=True)


# ---- guard_pool_request: whole-request validation ----

def test_pool_name_validation():
    with pytest.raises(dp.DiskGuardError, match="pool name"):
        dp.guard_pool_request("x", "raid1", [_disk("sda"), _disk("sdc")])
    with pytest.raises(dp.DiskGuardError, match="pool name"):
        dp.guard_pool_request("bad name!", "raid1", [_disk("sda")])


def test_pool_raid_level_validation():
    with pytest.raises(dp.DiskGuardError, match="raid"):
        dp.guard_pool_request("tank", "raid99", [_disk("sda"), _disk("sdc")])


def test_pool_min_disks_enforced():
    with pytest.raises(dp.DiskGuardError, match="at least"):
        dp.guard_pool_request("tank", "raid10", [_disk("sda"), _disk("sdc")])  # needs 4


def test_pool_rejects_system_disk_in_set():
    disks = [_disk("sda"), _disk("sdb", is_system=True)]
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.guard_pool_request("tank", "raid1", disks)


def test_pool_rejects_duplicate_disks():
    disks = [_disk("sda"), _disk("sda")]
    with pytest.raises(dp.DiskGuardError, match="more than once"):
        dp.guard_pool_request("tank", "raid1", disks)


def test_pool_happy_path():
    disks = [_disk("sda"), _disk("sdc"), _disk("sdd"), _disk("sde")]
    dp.guard_pool_request("tank", "raid10", disks)   # 4 blank disks, raid10 → ok


# ---- inspection: parse lsblk JSON, derive system/mounted/array facts ----

def test_inspect_marks_root_disk_as_system():
    # mirrors Keith's real box: root on sdb, blank data disks sda/sdc/sdd/sde
    lsblk = {
        "blockdevices": [
            {"name": "sda", "type": "disk", "size": 34359738368},
            {"name": "sdb", "type": "disk", "size": 34359738368, "children": [
                {"name": "sdb1", "fstype": "ext4", "mountpoint": "/"},
                {"name": "sdb5", "fstype": "swap", "mountpoint": "[SWAP]"},
            ]},
            {"name": "sdc", "type": "disk", "size": 34359738368},
        ]
    }
    disks = dp.inspect_disks(runner=lambda cmd: json.dumps(lsblk))
    by = {d.name: d for d in disks}
    assert by["sdb"].is_system is True       # root + swap → system
    assert by["sdb"].has_partition_table is True
    assert by["sda"].is_system is False
    assert by["sda"].blank is True
    assert by["sdc"].blank is True


def test_inspect_marks_array_member():
    lsblk = {"blockdevices": [
        {"name": "sda", "type": "disk", "fstype": "btrfs"},
    ]}
    disks = dp.inspect_disks(runner=lambda cmd: json.dumps(lsblk))
    assert disks[0].in_array is True


def test_find_disk_resolves_or_raises():
    disks = [_disk("sda"), _disk("sdc")]
    assert dp.find_disk(disks, "sda").name == "sda"
    assert dp.find_disk(disks, "/dev/sdc").name == "sdc"
    with pytest.raises(dp.DiskGuardError, match="no such disk"):
        dp.find_disk(disks, "sdz")


# ---- ACTIONS: plan + execute, all guarded ----

def test_plan_pool_refuses_system_disk():
    disks = [_disk("sda"), _disk("sdb", is_system=True)]
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.plan_pool("tank", "raid1", disks)


def test_plan_pool_builds_steps_without_running(stub_tools):
    disks = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks)
    assert plan.name == "tank"
    assert plan.mountpoint == "/srv/nas/tank"
    # mkfs.btrfs is the first destructive step, across both devices
    desc = plan.describe()
    assert any("mkfs.btrfs" in s and "/dev/sda" in s and "/dev/sdc" in s for s in desc)
    assert any("raid1" in s for s in desc)


def test_execute_pool_rechecks_guards(stub_tools):
    # plan made when disk was blank; disk becomes system before execute → refuse
    disks_ok = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks_ok)
    disks_changed = [_disk("sda", is_system=True), _disk("sdc")]
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.execute_pool(plan, disks_changed,
                        runner=lambda c: None, blkid=lambda d: "U")


def test_execute_pool_mounts_by_uuid(stub_tools):
    disks = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks)
    cmds = []
    import tempfile, os
    fstab = tempfile.mktemp()
    # patch fstab target
    orig = dp._append_fstab
    dp._append_fstab = lambda uuid, mp, fstab=fstab: orig(uuid, mp, fstab)
    try:
        res = dp.execute_pool(plan, disks,
                              runner=lambda c: cmds.append(c),
                              blkid=lambda d: "ABCD-1234")
    finally:
        dp._append_fstab = orig
    assert res["uuid"] == "ABCD-1234"
    # mount used -U <uuid>, never a /dev/sdX path
    mount_cmd = [c for c in cmds if c and c[0] == "mount"][0]
    assert "-U" in mount_cmd and "ABCD-1234" in mount_cmd
    assert not any(x.startswith("/dev/sd") for x in mount_cmd)
    # fstab got a UUID line
    assert "ABCD-1234" in open(fstab).read()
    os.unlink(fstab)


def test_execute_pool_runs_mkfs_across_all_devices(stub_tools):
    disks = [_disk("sda"), _disk("sdc"), _disk("sdd")]
    plan = dp.plan_pool("tank", "raid5", disks)
    cmds = []
    dp.execute_pool(plan, disks, runner=lambda c: cmds.append(c),
                    blkid=lambda d: "U-1")
    mkfs = [c for c in cmds if c and c[0] == "mkfs.btrfs"][0]
    for dev in ("/dev/sda", "/dev/sdc", "/dev/sdd"):
        assert dev in mkfs
    assert "raid5" in mkfs


def test_missing_btrfs_tool_reported_cleanly(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda t: None)
    with pytest.raises(dp.DiskGuardError, match="btrfs-progs"):
        dp._require_tools("mkfs.btrfs")
