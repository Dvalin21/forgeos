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
    assert plan.mountpoint == "/srv/tank"
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


def test_execute_pool_mounts_by_uuid(stub_tools, tmp_path):
    disks = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks)
    cmds = []
    fstab = str(tmp_path / "fstab")
    res = dp.execute_pool(plan, disks,
                          runner=lambda c: cmds.append(c),
                          blkid=lambda d: "ABCD-1234",
                          fstab_path=fstab)
    assert res["uuid"] == "ABCD-1234"
    # mount goes through systemd-mount (PID 1, host namespace) by by-uuid,
    # never an in-sandbox `mount -U` — the API's ns/mnt differs from PID 1's,
    # so an in-process mount is invisible to samba/docker/host.
    mount_cmd = [c for c in cmds if c and c[0] == "systemd-mount"][0]
    assert "ABCD-1234" in " ".join(mount_cmd)
    assert not any(c and c[0] == "mount" for c in cmds)
    # fstab got a UUID line
    assert "ABCD-1234" in open(fstab).read()


def test_execute_pool_runs_mkfs_across_all_devices(stub_tools, tmp_path):
    disks = [_disk("sda"), _disk("sdc"), _disk("sdd")]
    plan = dp.plan_pool("tank", "raid5", disks)
    cmds = []
    dp.execute_pool(plan, disks, runner=lambda c: cmds.append(c),
                    blkid=lambda d: "U-1", fstab_path=str(tmp_path / "fstab"))
    mkfs = [c for c in cmds if c and c[0] == "mkfs.btrfs"][0]
    for dev in ("/dev/sda", "/dev/sdc", "/dev/sdd"):
        assert dev in mkfs
    assert "raid5" in mkfs


def test_execute_pool_fails_loud_if_record_fails(stub_tools, tmp_path):
    # Atomicity (Ponytail): if the FS is created but the config-DB record
    # fails, execute_pool must raise — NOT return success. This is the exact
    # bug that left a mounted pool invisible to the Storage Manager.
    disks = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks)

    def bad_record(result):
        raise RuntimeError("config-DB save did not persist the pool")

    with pytest.raises(dp.DiskGuardError, match="recording it in the config-DB FAILED"):
        dp.execute_pool(plan, disks, runner=lambda c: None,
                        blkid=lambda d: "U-2", fstab_path=str(tmp_path / "fstab"),
                        record=bad_record)


def test_execute_pool_calls_record_with_result(stub_tools, tmp_path):
    disks = [_disk("sda"), _disk("sdc")]
    plan = dp.plan_pool("tank", "raid1", disks)
    recorded = {}
    dp.execute_pool(plan, disks, runner=lambda c: None, blkid=lambda d: "U-3",
                    fstab_path=str(tmp_path / "fstab"),
                    record=lambda r: recorded.update(r))
    assert recorded["uuid"] == "U-3"
    assert recorded["mountpoint"] == "/srv/tank"


def test_missing_btrfs_tool_reported_cleanly(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda t: None)
    with pytest.raises(dp.DiskGuardError, match="btrfs-progs"):
        dp._require_tools("mkfs.btrfs")


def test_execute_pool_ignores_disks_outside_the_plan(stub_tools, tmp_path):
    """Every real box has a system disk in the fresh inspection list. The
    re-check must guard ONLY the plan's devices — guarding the whole list
    refused every pool create on real hardware (a /dev/sda request came back
    "…/dev/sde holds the system"). Found by a live clean-install box."""
    plan = dp.plan_pool("tank", "single", [_disk("sda")])
    disks = [_disk("sda"), _disk("sde", is_system=True), _disk("sr0")]
    cmds = []
    res = dp.execute_pool(plan, disks, runner=lambda c: cmds.append(c),
                          blkid=lambda d: "U-9", fstab_path=str(tmp_path / "fstab"))
    assert res["uuid"] == "U-9"
    assert any(c and c[0] == "mkfs.btrfs" for c in cmds)


def test_execute_pool_still_refuses_when_target_becomes_system(stub_tools):
    # ...and the flip side stays guarded: a plan target that became the
    # system disk between plan and execute is still refused.
    plan = dp.plan_pool("tank", "single", [_disk("sda")])
    disks = [_disk("sda", is_system=True), _disk("sde", is_system=True)]
    with pytest.raises(dp.DiskGuardError, match="system"):
        dp.execute_pool(plan, disks, runner=lambda c: None, blkid=lambda d: "U")


def test_remove_fstab_drops_the_pool_line(tmp_path):
    # a destroyed pool whose fstab line survives fails to mount every boot
    fs = tmp_path / "fstab"
    fs.write_text("UUID=keep1 / btrfs defaults 0 0\n"
                  "UUID=gone9 /srv/pool btrfs defaults,compress=zstd 0 2\n"
                  "UUID=keep2 /srv/other btrfs defaults 0 2\n")
    dp._remove_fstab("gone9", str(fs))
    left = fs.read_text()
    assert "gone9" not in left and "keep1" in left and "keep2" in left
    # idempotent
    dp._remove_fstab("gone9", str(fs))
    assert fs.read_text() == left


def test_execute_pool_cleans_nothing_on_failure(stub_tools, tmp_path):
    """A failure mid-execute (record fails) must still leave the fstab line
    for the operator to see — pools are recorded from fstab+disk evidence,
    and the loud failure is the designed behavior."""
    plan = dp.plan_pool("tank", "single", [_disk("sda")])
    fs = tmp_path / "fstab"
    def rec(r):
        raise RuntimeError("config save failed")
    with pytest.raises(dp.DiskGuardError, match="recording it in the config-DB FAILED"):
        dp.execute_pool(plan, [_disk("sda")],
                        runner=lambda c: None, blkid=lambda d: "U-x",
                        fstab_path=str(fs), record=rec)
    assert "U-x" in fs.read_text()


def test_plan_pool_accepts_ui_integer_levels(stub_tools):
    """The web UI sends parseInt(level) — 0/1/5/6/10. Those integers must
    normalize to btrfs profile names: str(1) == "1" is not a valid profile,
    and the plan carries raid_level into execute_pool's guard re-check, so
    every RAID create from the UI 400'd (only "single" — a string — worked).
    The create form has no 'single' option at all."""
    for lvl, canon in [(1, "raid1"), (5, "raid5"), (6, "raid6"),
                       (10, "raid10"), (0, "raid0")]:
        plan = dp.plan_pool("tank", lvl, [_disk("sda"), _disk("sdb"),
                                          _disk("sdc"), _disk("sdd")])
        assert plan.raid_level == canon, (lvl, plan.raid_level)
        mkfs = plan.steps[0][1]
        assert f"-d {canon}" in " ".join(mkfs) or canon in mkfs


def test_execute_pool_recheck_passes_with_ui_integer_level(stub_tools, tmp_path):
    # end-to-end shape of the bug: plan from the UI's integer level, fresh
    # inspection that (like every real box) also contains the system disk.
    plan = dp.plan_pool("tank", 1, [_disk("sda"), _disk("sdc")])
    dp.execute_pool(plan, [_disk("sda"), _disk("sdc"), _disk("sde", is_system=True)],
                    runner=lambda c: None, blkid=lambda d: "U-i",
                    fstab_path=str(tmp_path / "fstab"))
