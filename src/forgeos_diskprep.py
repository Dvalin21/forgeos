"""ForgeOS disk preparation — SAFETY LAYER.

Every destructive disk operation (wipe, partition, mkfs, pool create) in
ForgeOS funnels through this module. Its job is to make it IMPOSSIBLE to
destroy the system disk or an in-use disk from any path (API, CLI, installer).

Design split (deliberate):
  - INSPECTION (pure-ish, read-only): gather facts about disks from the system.
  - GUARDS (pure): decide whether a target is safe, given facts. No I/O, so
    fully unit-testable. These are the refusals.
  - ACTIONS (the only place that writes): run the destructive command ONLY
    after guards pass.

The guards refuse, by default, to touch a disk that:
  - holds the root / boot / swap filesystem (resolved from the actual system,
    not assumed to be sda — on real boxes root has been on sdb),
  - is currently mounted anywhere,
  - is part of an existing RAID/btrfs array,
  - already has a partition table or filesystem signature (unless an explicit
    force-wipe is requested AND the disk is confirmed non-system).

Devices are identified by /dev/disk/by-id/ stable names where possible, never
bare /dev/sdX (which reorders across reboots).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional


class DiskGuardError(Exception):
    """Raised when a disk operation is refused by the safety guards."""


@dataclass
class DiskInfo:
    """Facts about one block device, as gathered from the system."""
    name: str                    # e.g. "sda"
    path: str                    # e.g. "/dev/sda"
    size_bytes: int = 0
    mounted: bool = False        # is this disk or any child mounted?
    mountpoints: list[str] = field(default_factory=list)
    has_partition_table: bool = False
    has_filesystem: bool = False
    in_array: bool = False       # member of md/btrfs/lvm
    is_system: bool = False      # holds root/boot/swap
    by_id: str = ""              # stable /dev/disk/by-id/... if known
    children: list[str] = field(default_factory=list)

    @property
    def stable_path(self) -> str:
        """Prefer the by-id path; fall back to /dev/<name>."""
        return self.by_id or self.path

    @property
    def blank(self) -> bool:
        """A disk is 'blank' (safe to use without force) only if it has no
        partition table, no filesystem, isn't in an array, isn't mounted, and
        isn't a system disk."""
        return not (self.has_partition_table or self.has_filesystem
                    or self.in_array or self.mounted or self.is_system)


# ---------------------------------------------------------------------------
# GUARDS — pure decisions, no I/O. These are the refusals. Unit-tested.
# ---------------------------------------------------------------------------

def guard_destructible(disk: DiskInfo, *, force: bool = False) -> None:
    """Raise DiskGuardError unless `disk` is safe to destroy.

    The system disk is NEVER destructible, force or not. Mounted / in-array
    disks are never destructible. A disk with an existing table/filesystem is
    refused UNLESS force=True (and it's still not system/mounted/in-array).
    """
    if disk.is_system:
        raise DiskGuardError(
            f"{disk.path} holds the system (root/boot/swap) — refusing. "
            "This disk can never be used for a data pool.")
    if disk.mounted:
        raise DiskGuardError(
            f"{disk.path} is mounted at {', '.join(disk.mountpoints) or 'unknown'} "
            "— unmount it first; refusing to touch a mounted disk.")
    if disk.in_array:
        raise DiskGuardError(
            f"{disk.path} is already part of a RAID/btrfs/LVM array — refusing.")
    if (disk.has_partition_table or disk.has_filesystem) and not force:
        raise DiskGuardError(
            f"{disk.path} already has a partition table or filesystem. "
            "Refusing to wipe it without an explicit force/confirm. If you are "
            "sure it's disposable, pass force=True.")


def guard_pool_request(name: str, raid_level, disks: list[DiskInfo],
                       *, force: bool = False) -> None:
    """Validate a whole pool-create request before ANY disk is touched."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,}", name or ""):
        raise DiskGuardError(
            f"invalid pool name {name!r} — use 2+ chars, letters/digits/_/-.")
    valid_levels = {"single", "raid0", "raid1", "raid10", "raid5", "raid6",
                    0, 1, 10, 5, 6}
    if raid_level not in valid_levels:
        raise DiskGuardError(f"invalid btrfs raid profile: {raid_level!r}")
    min_disks = _min_disks_for(raid_level)
    if len(disks) < min_disks:
        raise DiskGuardError(
            f"{raid_level} needs at least {min_disks} disk(s), got {len(disks)}.")
    # Every disk must individually pass the destructible guard.
    for d in disks:
        guard_destructible(d, force=force)
    # No duplicate disks in the same request.
    names = [d.name for d in disks]
    if len(set(names)) != len(names):
        raise DiskGuardError("the same disk appears more than once in the request.")


def _min_disks_for(raid_level) -> int:
    return {
        "single": 1, 0: 1, "raid0": 1,
        1: 2, "raid1": 2,
        5: 2, "raid5": 2,
        6: 3, "raid6": 3,
        10: 4, "raid10": 4,
    }.get(raid_level, 1)


# ---------------------------------------------------------------------------
# INSPECTION — read-only system facts. Injectable runner for tests.
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout


def inspect_disks(runner: Optional[Callable[[list[str]], str]] = None) -> list[DiskInfo]:
    """Enumerate whole disks (not partitions) with safety-relevant facts,
    from `lsblk -J -O`. `runner` is injectable so tests feed canned JSON."""
    run = runner or _run
    raw = run(["lsblk", "-J", "-O", "-b"])
    data = json.loads(raw) if raw else {"blockdevices": []}
    out: list[DiskInfo] = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        out.append(_disk_from_lsblk(dev))
    return out


def _disk_from_lsblk(dev: dict) -> DiskInfo:
    """Build a DiskInfo from one lsblk device node (with its children)."""
    name = dev.get("name", "")
    info = DiskInfo(name=name, path=f"/dev/{name}",
                    size_bytes=int(dev.get("size") or 0))

    def scan(node: dict):
        mp = node.get("mountpoint") or node.get("mountpoints") or None
        mps = [m for m in (mp if isinstance(mp, list) else [mp]) if m]
        for m in mps:
            info.mountpoints.append(m)
            info.mounted = True
            if m in ("/", "/boot", "/boot/efi") or m == "[SWAP]":
                info.is_system = True
        if (node.get("fstype") or "") == "swap":
            info.is_system = True
        ftype = node.get("fstype") or ""
        if ftype:
            info.has_filesystem = True
            if ftype in ("linux_raid_member", "btrfs", "LVM2_member"):
                info.in_array = True
        for child in node.get("children", []) or []:
            info.has_partition_table = True
            info.children.append(child.get("name", ""))
            scan(child)

    scan(dev)
    return info


def find_disk(disks: list[DiskInfo], ident: str) -> DiskInfo:
    """Resolve a user-supplied identifier (sda, /dev/sda, by-id) to a DiskInfo,
    or raise. Never silently picks a different disk."""
    ident_norm = ident.replace("/dev/", "").strip()
    for d in disks:
        if d.name == ident_norm or d.path == ident or d.by_id == ident:
            return d
    raise DiskGuardError(f"no such disk: {ident!r}")


# ---------------------------------------------------------------------------
# ACTIONS — the ONLY place that writes to disks. Every destructive step is
# preceded by a fresh guard check. A plan is a list of (description, argv);
# dry-run returns the plan without running it.
# ---------------------------------------------------------------------------

@dataclass
class PoolPlan:
    name: str
    raid_level: str
    devices: list[str]              # stable paths, in request order
    mountpoint: str
    steps: list[tuple[str, list[str]]] = field(default_factory=list)

    def describe(self) -> list[str]:
        return [f"{desc}: {' '.join(argv)}" for desc, argv in self.steps]


# btrfs raid profile names mkfs.btrfs understands
_BTRFS_PROFILE = {
    "single": "single", 0: "raid0", "raid0": "raid0",
    1: "raid1", "raid1": "raid1",
    10: "raid10", "raid10": "raid10",
    5: "raid5", "raid5": "raid5",
    6: "raid6", "raid6": "raid6",
}


def plan_pool(name: str, raid_level, disks: list[DiskInfo],
              *, mountpoint: str = "", force: bool = False) -> PoolPlan:
    """Validate the WHOLE request (guards), then build the ordered destructive
    plan WITHOUT running anything. Raises DiskGuardError if unsafe."""
    guard_pool_request(name, raid_level, disks, force=force)
    profile = _BTRFS_PROFILE.get(raid_level)
    if profile is None:
        raise DiskGuardError(f"unsupported btrfs profile: {raid_level!r}")
    mp = mountpoint or f"/srv/nas/{name}"
    devs = [d.stable_path for d in disks]

    plan = PoolPlan(name=name, raid_level=str(raid_level), devices=devs, mountpoint=mp)
    # mkfs.btrfs handles multi-device + raid in one shot; data AND metadata
    # profiles set so a single-disk-loss is survivable per the chosen level.
    plan.steps.append((
        "create btrfs filesystem",
        ["mkfs.btrfs", "-f", "-L", name,
         "-d", profile, "-m", profile, *devs],
    ))
    plan.steps.append(("create mountpoint", ["mkdir", "-p", mp]))
    # NOTE: the real mount is added by execute_pool once the FS UUID is known
    # (we mount by UUID, never /dev/sdX). Placeholder recorded for the plan.
    plan.steps.append(("mount by UUID (resolved after mkfs)",
                       ["mount", "UUID=<resolved>", mp]))
    return plan


def execute_pool(plan: PoolPlan, disks: list[DiskInfo], *, force: bool = False,
                 runner: Optional[Callable[[list[str]], "subprocess.CompletedProcess"]] = None,
                 blkid: Optional[Callable[[str], str]] = None) -> dict:
    """Execute a PoolPlan. RE-CHECKS the guards immediately before writing (in
    case disk state changed since planning), then runs mkfs.btrfs, makes the
    mountpoint, resolves the btrfs UUID, mounts by UUID, and appends an fstab
    entry. Returns {uuid, mountpoint, devices}. Runner/blkid injectable.
    """
    run = runner or _run_checked
    get_uuid = blkid or _btrfs_uuid

    # Fresh guard re-check — never trust a stale plan against current disks.
    guard_pool_request(plan.name, plan.raid_level, disks, force=force)

    # 1. mkfs.btrfs across all devices
    profile = _BTRFS_PROFILE.get(plan.raid_level) or plan.raid_level
    run(["mkfs.btrfs", "-f", "-L", plan.name,
         "-d", profile, "-m", profile, *plan.devices])

    # 2. mountpoint
    run(["mkdir", "-p", plan.mountpoint])

    # 3. resolve the btrfs FS UUID and mount BY UUID (never /dev/sdX)
    uuid = get_uuid(plan.devices[0])
    if not uuid:
        raise DiskGuardError("could not resolve btrfs UUID after mkfs")
    run(["mount", "-U", uuid, plan.mountpoint])

    # 4. persist to fstab by UUID so it survives reboots / device reorder
    _append_fstab(uuid, plan.mountpoint)

    return {"uuid": uuid, "mountpoint": plan.mountpoint, "devices": plan.devices}


def _run_checked(cmd: list[str]) -> "subprocess.CompletedProcess":
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise DiskGuardError(f"{cmd[0]} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r


def _btrfs_uuid(device: str) -> str:
    r = subprocess.run(["blkid", "-s", "UUID", "-o", "value", device],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def _append_fstab(uuid: str, mountpoint: str, fstab: str = "/etc/fstab") -> None:
    """Idempotently add a UUID-based btrfs mount to fstab."""
    line = f"UUID={uuid}  {mountpoint}  btrfs  defaults,compress=zstd  0  2\n"
    try:
        with open(fstab, "r") as f:
            if uuid in f.read():
                return  # already present
    except FileNotFoundError:
        pass
    with open(fstab, "a") as f:
        f.write(line)
