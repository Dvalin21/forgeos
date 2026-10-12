"""ForgeOS LHSR — Execution layer.

Takes a computed layout and partitions disks, creates btrfs filesystems
per tier, and uses mergerfs to span them into a single mountpoint.

This is the DESTRUCTIVE counterpart to forgeos_lhsr.py.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from forgeos_lhsr import Layout

logger = logging.getLogger("forgeos-lhsr-exec")


class LhsrExecError(Exception):
    """Raised when LHSR execution fails."""
    pass


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command, raising LhsrExecError on failure."""
    logger.debug("exec: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise LhsrExecError(
            f"{cmd[0]} failed (exit {r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    return r


def _get_part_dev(base_dev: str, part_num: int) -> str:
    """Build partition device path."""
    if base_dev[-1].isdigit():
        return f"{base_dev}p{part_num}"
    return f"{base_dev}{part_num}"


def _wait_for_part(dev: str, part_num: int, timeout_ms: int = 5000) -> None:
    """Wait for a partition device to appear."""
    path = _get_part_dev(dev, part_num)
    waited = 0
    while waited < timeout_ms:
        if Path(path).is_block_device():
            return
        time.sleep(0.1)
        waited += 100
    raise LhsrExecError(f"{path} did not appear after {timeout_ms}ms")


def _partition_disk(dev: str, layout: Layout, disk_idx: int) -> list[str]:
    """Partition a single disk. Returns list of partition device paths."""
    _run(["sgdisk", "--zap-all", dev])

    parts = [p for p in layout.partitions if p.disk_idx == disk_idx]
    if not parts:
        return []

    created = []
    for i, part in enumerate(parts, 1):
        _run([
            "sgdisk",
            f"--new={i}:0:+{part.size_sectors}s",
            f"--typecode={i}:fd00",
            dev,
        ])
        created.append(_get_part_dev(dev, i))

    return created


def _reread_partitions(dev: str) -> None:
    """Re-read partition table."""
    for cmd in [["partprobe", dev], ["blockdev", "--rereadpt", dev], ["partx", "-a", dev]]:
        try:
            _run(cmd, timeout=10)
            return
        except (LhsrExecError, subprocess.TimeoutExpired):
            continue


def execute_layout(
    layout: Layout,
    *,
    force: bool = False,
    runner: Optional[Callable] = None,
) -> dict:
    """Execute an LHSR layout: partition, mkfs, mergerfs span.

    Args:
        layout: Computed layout from forgeos_lhsr.plan_layout().
        force: Skip safety warnings.
        runner: Optional command runner for testing.

    Returns:
        dict with execution results.
    """
    run = runner or _run

    # Step 0: refuse to touch a disk that isn't ours to destroy.
    # `sgdisk --zap-all` below is unconditional, so WITHOUT this guard a
    # mistyped --dev path (or the system disk) gets wiped. `force` only waives
    # the "already has a partition table" refusal — it never waives the
    # system/mounted/in-array guards, which are absolute.
    from forgeos_diskprep import DiskGuardError, guard_destructible, inspect_disks
    by_path = {d.path: d for d in inspect_disks()}
    for disk in layout.disks:
        info = by_path.get(disk.path)
        if info is None:
            raise LhsrExecError(
                f"{disk.path} was not found as a block device — refusing to "
                f"partition it. Check the device list."
            )
        try:
            guard_destructible(info, force=force)
        except DiskGuardError as exc:
            raise LhsrExecError(f"REFUSED: {exc}") from exc

    # Step 1: Partition all disks
    logger.info("Step 1: Partitioning disks")
    tier_partitions: dict[int, list[str]] = {}

    for disk_idx, disk in enumerate(layout.disks):
        logger.info("  Partitioning %s...", disk.path)
        created = _partition_disk(disk.path, layout, disk_idx)
        if created:
            _reread_partitions(disk.path)
            for i, _ in enumerate(created, 1):
                _wait_for_part(disk.path, i)
        for part in layout.partitions:
            if part.disk_idx == disk_idx:
                tier_partitions.setdefault(part.tier, []).append(
                    _get_part_dev(disk.path, part.tier + 1)
                )

    # Step 2: Create btrfs per tier
    logger.info("Step 2: Creating btrfs filesystems per tier")
    tier_mountpoints: dict[int, str] = {}

    for tier in layout.tiers:
        tier_idx = tier.tier_idx
        parts = tier_partitions.get(tier_idx, [])
        if not parts:
            raise LhsrExecError(f"No partitions for tier {tier_idx}")

        mp = f"/srv/nas/lhsr_tier_{tier_idx}"
        Path(mp).mkdir(parents=True, exist_ok=True)

        profile = {"raid5": "raid5", "raid6": "raid6", "raid1": "raid1", "single": "single"}.get(tier.raid_type, "raid1")

        run(["mkfs.btrfs", "-f", "-L", f"lhsr_tier_{tier_idx}", "-d", profile, "-m", profile, *parts])
        run(["mount", parts[0], mp])

        for part in parts[1:]:
            run(["btrfs", "device", "add", part, mp])

        tier_mountpoints[tier_idx] = mp
        time.sleep(1)

    # Step 3: mergerfs spanning
    logger.info("Step 3: Setting up mergerfs spanning")

    # Check mergerfs installed
    try:
        run(["which", "mergerfs"], timeout=5)
    except LhsrExecError:
        logger.info("  Installing mergerfs...")
        run(["apt-get", "install", "-y", "mergerfs"])

    combined_mp = "/srv/nas/lhsr"
    Path(combined_mp).mkdir(parents=True, exist_ok=True)

    # Mount with mergerfs. The tier filesystems STAY MOUNTED — mergerfs merges
    # the branch mountpoints, so unmounting them first would hand it empty
    # directories and the span would serve nothing (the tier data would be
    # unmounted and unreachable). This was inverted and is the single most
    # destructive thing this function did.
    tier_mounts = [tier_mountpoints[i] for i in range(layout.tier_count)]
    source_str = ":".join(tier_mounts)
    run([
        "mergerfs", source_str, combined_mp,
        "-o", "defaults,allow_other,use_ino,category.create=mfs,moveonenospc=true,minfreespace=20G",
    ])

    # Step 4: fstab
    logger.info("Step 4: Persisting to fstab")
    tier_uuids = []
    for tier_idx in range(layout.tier_count):
        parts = tier_partitions.get(tier_idx, [])
        if parts:
            r = run(["blkid", "-s", "UUID", "-o", "value", parts[0]])
            tier_uuids.append(r.stdout.strip())

    fstab_lines = ["\n# ForgeOS LHSR"]
    for i, uuid in enumerate(tier_uuids):
        if uuid:
            fstab_lines.append(f"UUID={uuid}  /srv/nas/lhsr_tier_{i}  btrfs  defaults,noatime  0  0")
        else:
            # An empty UUID would write a poison `UUID=` line that breaks boot.
            logger.warning("Tier %d has no UUID — leaving it out of fstab", i)

    tier_mounts_str = ":".join([f"/srv/nas/lhsr_tier_{i}" for i in range(layout.tier_count)])
    fstab_lines.append(f"{tier_mounts_str}  /srv/nas/lhsr  fuse.mergerfs  defaults,allow_other,use_ino,category.create=mfs  0  0")

    # Idempotent: strip any previous ForgeOS LHSR block before appending, so a
    # re-run replaces the stanza instead of stacking a second copy (the tier
    # list grows when disks are added and stale lines keep dead UUIDs).
    block = "\n".join(fstab_lines) + "\n"
    try:
        with open("/etc/fstab") as f:
            existing = f.read()
        if "# ForgeOS LHSR" in existing:
            head = existing.split("# ForgeOS LHSR")[0].rstrip("\n")
            block = head + "\n" + block
        with open("/etc/fstab", "w") as f:
            f.write(block)
    except OSError as exc:
        raise LhsrExecError(f"Could not update /etc/fstab: {exc}")

    return {
        "mountpoint": combined_mp,
        "tiers": [
            {
                "index": t.tier_idx,
                "raid_type": t.raid_type,
                "mountpoint": f"/srv/nas/lhsr_tier_{t.tier_idx}",
                "usable_bytes": t.usable_sectors * 512,
            }
            for t in layout.tiers
        ],
    }
