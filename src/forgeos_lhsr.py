"""ForgeOS LHSR — Hybrid RAID layout engine.

Ported from the LHSR kernel project's greedy tiering algorithm.
Computes optimal partition layouts for mixed-size disks, creating
equal-sized RAID tiers that are then combined into a single LVM volume.

This module is PURE COMPUTATION — no disk I/O, no side effects.
The execution layer (partitioning, mkfs, LVM) lives in forgeos_diskprep.

Naming: LHSR1 = single parity (RAID5-like), LHSR2 = dual parity (RAID6-like).
No Synology SHR naming anywhere in ForgeOS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Defaults matching LHSR's userspace tools
ALIGNMENT_SECTORS = 2048  # 1 MB alignment for 4K-native drives
MIN_PARTITION_SECTORS = 1048576  # 512 MB minimum partition
MAX_DISKS = 32
MAX_TIERS = 32
MAX_PARTITIONS = 256


@dataclass
class Partition:
    """One partition on one disk. All partitions in a tier have equal size."""
    disk_idx: int
    offset_sectors: int
    size_sectors: int
    tier: int


@dataclass
class Tier:
    """One RAID tier. All partitions are same size, same RAID level."""
    partition_count: int
    raid_type: str  # "raid5", "raid6", "raid1", "single"
    parity_per_tier: int  # 1 for LHSR1, 2 for LHSR2
    partition_size: int  # sectors per partition
    usable_sectors: int  # partition_size * data_members
    tier_idx: int = 0


@dataclass
class Disk:
    """One physical disk in the LHSR layout."""
    path: str
    total_sectors: int
    available_sectors: int = 0
    partition_count: int = 0


@dataclass
class Layout:
    """The complete LHSR layout for a set of mixed-size disks."""
    disk_count: int
    tier_count: int
    parity_per_tier: int  # 1 or 2
    alignment: int
    min_partition: int
    disks: list[Disk] = field(default_factory=list)
    tiers: list[Tier] = field(default_factory=list)
    partitions: list[Partition] = field(default_factory=list)
    total_raw_sectors: int = 0
    total_usable_sectors: int = 0
    vg_name: str = "lhsr_vg"
    lv_name: str = "lhsr_vol"


def plan_layout(
    disks: list[tuple[str, int]],
    parity: int = 1,
    alignment: int = ALIGNMENT_SECTORS,
    min_partition: int = MIN_PARTITION_SECTORS,
) -> Layout:
    """Compute the optimal LHSR partition layout for a set of disks.

    Args:
        disks: List of (path, total_sectors) tuples.
        parity: 1 for LHSR1 (single parity), 2 for LHSR2 (dual parity).
        alignment: Sector alignment (default 1 MB).
        min_partition: Minimum partition size in sectors (default 512 MB).

    Returns:
        A complete Layout object with all partitions and tiers computed.

    Raises:
        ValueError if the layout cannot be computed (too few disks, etc).
    """
    if parity not in (1, 2):
        raise ValueError(f"parity must be 1 (LHSR1) or 2 (LHSR2), got {parity}")

    min_disks = 3 if parity == 1 else 4
    if len(disks) < min_disks:
        raise ValueError(
            f"LHSR{parity} requires at least {min_disks} disks, got {len(disks)}"
        )

    if len(disks) > MAX_DISKS:
        raise ValueError(f"too many disks ({len(disks)}, max {MAX_DISKS})")

    # Sort disks by size ascending (smallest first for capacity calc)
    sorted_disks = sorted(disks, key=lambda d: d[1])

    layout = Layout(
        disk_count=len(sorted_disks),
        tier_count=0,
        parity_per_tier=parity,
        alignment=alignment,
        min_partition=min_partition,
    )

    # Initialize disk info
    disk_offset = []
    for path, total_sectors in sorted_disks:
        # Reserve GPT at front AND back (alignment sectors each)
        available = max(0, total_sectors - alignment * 2)
        layout.disks.append(Disk(
            path=path,
            total_sectors=total_sectors,
            available_sectors=available,
        ))
        disk_offset.append(alignment)
        layout.total_raw_sectors += total_sectors

    # Check each disk has room after alignment
    for i, d in enumerate(layout.disks):
        if d.available_sectors < min_partition:
            raise ValueError(
                f"Disk {i} ({d.path}) too small ({d.available_sectors} sectors "
                f"after alignment, need {min_partition})"
            )

    # Greedy tier allocation
    active = [True] * len(layout.disks)
    active_count = len(layout.disks)
    tier_idx = 0

    while active_count >= 2:
        # Choose the RAID type this tier can support
        if parity == 2:
            if active_count < 4:
                break
            raid_type = "raid6"
            data_members = active_count - 2
        elif active_count >= 3:
            raid_type = "raid5"
            data_members = active_count - 1
        else:
            raid_type = "raid1"
            data_members = 1

        # Find smallest available among active disks
        min_avail = min(
            layout.disks[i].available_sectors
            for i in range(len(layout.disks))
            if active[i]
        )

        # Round partition size down to alignment
        part_size = min_avail - (min_avail % alignment)

        if part_size < min_partition:
            break

        # Create tier
        tier = Tier(
            partition_count=active_count,
            raid_type=raid_type,
            parity_per_tier=1 if raid_type == "raid1" else parity,
            partition_size=part_size,
            usable_sectors=part_size * data_members,
            tier_idx=tier_idx,
        )
        layout.tiers.append(tier)

        # Allocate partitions on each active disk
        for i in range(len(layout.disks)):
            if not active[i]:
                continue

            # If disk has less than part_size left, allocate what's left
            if layout.disks[i].available_sectors < part_size:
                this_part_size = layout.disks[i].available_sectors
                this_part_size -= this_part_size % alignment
            else:
                this_part_size = part_size

            # This disk is saturated
            if this_part_size < min_partition:
                active[i] = False
                active_count -= 1
                continue

            # Record partition
            if len(layout.partitions) >= MAX_PARTITIONS:
                raise ValueError(f"too many partitions ({MAX_PARTITIONS} max)")

            layout.partitions.append(Partition(
                disk_idx=i,
                offset_sectors=disk_offset[i],
                size_sectors=this_part_size,
                tier=tier_idx,
            ))

            # Advance
            disk_offset[i] += this_part_size
            layout.disks[i].available_sectors -= this_part_size
            layout.disks[i].partition_count += 1

            # Check if disk is exhausted
            if layout.disks[i].available_sectors < min_partition:
                active[i] = False
                active_count -= 1

        tier_idx += 1

    layout.tier_count = tier_idx

    # Compute total usable capacity
    layout.total_usable_sectors = sum(t.usable_sectors for t in layout.tiers)

    return layout


def format_size(sectors: int) -> str:
    """Convert sectors (512-byte) to human-readable size."""
    bytes_val = sectors * 512
    if bytes_val >= 10**15:
        return f"{bytes_val / 10**15:.2f} PB"
    if bytes_val >= 10**12:
        return f"{bytes_val / 10**12:.2f} TB"
    if bytes_val >= 10**9:
        return f"{bytes_val / 10**9:.2f} GB"
    if bytes_val >= 10**6:
        return f"{bytes_val / 10**6:.0f} MB"
    return f"{bytes_val} B"


def print_layout(layout: Layout) -> str:
    """Format the layout as a human-readable string."""
    lines = []
    lines.append("")
    lines.append("LHSR Layout Plan")
    lines.append("================")
    lines.append(f"Mode: LHSR{layout.parity_per_tier} ({layout.parity_per_tier} parity per tier)")
    lines.append(f"Alignment: {layout.alignment} sectors ({layout.alignment // 2} KB)")
    lines.append(f"Min partition: {layout.min_partition} sectors ({format_size(layout.min_partition)})")
    lines.append(f"Total raw capacity: {format_size(layout.total_raw_sectors)}")
    lines.append(f"Total usable capacity: {format_size(layout.total_usable_sectors)}")
    lines.append(f"Tiers: {layout.tier_count}")
    lines.append("")

    # Disk summary
    lines.append("Disks")
    lines.append("-----")
    lines.append(f"{'#':>3}  {'Device':<20}  {'Size':>12}  {'Tiers':>8}  {'Partitions':>10}")
    for i, d in enumerate(layout.disks):
        parts_on_disk = sum(1 for p in layout.partitions if p.disk_idx == i)
        tiers_on_disk = len(set(
            p.tier for p in layout.partitions if p.disk_idx == i
        ))
        unused = d.available_sectors - layout.alignment
        unused_str = f"  ({format_size(unused)} unused)" if unused > layout.alignment else ""
        lines.append(
            f"{i:>3}  {d.path:<20}  {format_size(d.total_sectors):>12}  "
            f"{tiers_on_disk:>8}  {parts_on_disk:>10}{unused_str}"
        )

    # Tier breakdown
    lines.append("")
    lines.append("Tiers")
    lines.append("-----")
    lines.append(
        f"{'Tier':>5}  {'Type':<10}  {'Members':>10}  {'PartSz':>10}  {'Usable':>10}  Disks"
    )
    for t in layout.tiers:
        members_str = f"{t.partition_count} disks"
        disk_list = ",".join(
            f"d{p.disk_idx}"
            for p in layout.partitions
            if p.tier == t.tier_idx
        )
        lines.append(
            f"{t.tier_idx:>5}  {t.raid_type.upper():<10}  {members_str:>10}  "
            f"{format_size(t.partition_size):>10}  {format_size(t.usable_sectors):>10}  {disk_list}"
        )

    # Per-disk partition map
    lines.append("")
    lines.append("Partition Map")
    lines.append("-------------")
    for i, d in enumerate(layout.disks):
        lines.append(f"Disk {i} ({d.path}):")
        has_parts = False
        for p in layout.partitions:
            if p.disk_idx != i:
                continue
            has_parts = True
            lines.append(
                f"  Partition {p.tier + 1:>2}: offset={p.offset_sectors:>12}  "
                f"size={p.size_sectors:>12}  ({format_size(p.size_sectors)})"
            )
        if not has_parts:
            lines.append("  (no partitions)")

    # Unused space summary
    total_unused = sum(
        max(0, d.available_sectors - layout.alignment)
        for d in layout.disks
    )
    if total_unused > 0:
        lines.append("")
        lines.append(f"Unused Capacity: {format_size(total_unused)}")
        lines.append("  Disks smaller than the largest tier cannot contribute")
        lines.append("  further space once their remaining capacity drops below")
        lines.append("  the minimum partition threshold.")

    lines.append("")
    return "\n".join(lines)
