"""ForgeOS LHSR — API endpoints for hybrid RAID management.

Provides REST API for:
  - Computing LHSR layouts (plan)
  - Creating LHSR pools (partition, mkfs, LVM)
  - Monitoring disk health with predictive failure
  - SMART trend database and predictive failure
  - Managing tiers (expand, replace, scrub, rebuild)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token
from forgeos_lhsr import plan_layout, format_size, Layout
from forgeos_lhsr_health import DiskHealth, compute_health_score, health_label, health_color

logger = logging.getLogger("forgeos-api")

router = APIRouter()


@router.post("/api/lhsr/plan")
async def lhsr_plan(body: dict, user=Depends(verify_token)):
    """Compute an LHSR layout for the given disks without making changes.

    Request body:
        disks: list of {"path": "/dev/sdb", "size_sectors": 12345678}
        parity: 1 (LHSR1) or 2 (LHSR2), default 1

    Returns:
        Layout plan with partitions, tiers, and capacity breakdown.
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")

    disks_raw = body.get("disks", [])
    parity = int(body.get("parity", 1))

    if not disks_raw:
        raise HTTPException(400, "No disks specified")

    if parity not in (1, 2):
        raise HTTPException(400, "parity must be 1 (LHSR1) or 2 (LHSR2)")

    # Convert to (path, size_sectors) tuples
    disks = []
    for d in disks_raw:
        path = d.get("path", "")
        size = d.get("size_sectors", 0)
        if not path or not size:
            raise HTTPException(400, "Each disk needs 'path' and 'size_sectors'")
        disks.append((path, int(size)))

    try:
        layout = plan_layout(disks, parity=parity)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Build response
    return {
        "parity": parity,
        "disk_count": layout.disk_count,
        "tier_count": layout.tier_count,
        "total_raw": layout.total_raw_sectors,
        "total_raw_human": format_size(layout.total_raw_sectors),
        "total_usable": layout.total_usable_sectors,
        "total_usable_human": format_size(layout.total_usable_sectors),
        "disks": [
            {
                "index": i,
                "path": d.path,
                "total_sectors": d.total_sectors,
                "total_human": format_size(d.total_sectors),
                "available_sectors": d.available_sectors,
                "available_human": format_size(d.available_sectors),
                "partition_count": d.partition_count,
            }
            for i, d in enumerate(layout.disks)
        ],
        "tiers": [
            {
                "index": t.tier_idx,
                "raid_type": t.raid_type,
                "parity": t.parity_per_tier,
                "member_count": t.partition_count,
                "partition_size": t.partition_size,
                "partition_size_human": format_size(t.partition_size),
                "usable_sectors": t.usable_sectors,
                "usable_human": format_size(t.usable_sectors),
                "disks": [
                    f"d{p.disk_idx}"
                    for p in layout.partitions
                    if p.tier == t.tier_idx
                ],
            }
            for t in layout.tiers
        ],
        "partitions": [
            {
                "disk_idx": p.disk_idx,
                "disk_path": layout.disks[p.disk_idx].path,
                "offset_sectors": p.offset_sectors,
                "size_sectors": p.size_sectors,
                "size_human": format_size(p.size_sectors),
                "tier": p.tier,
            }
            for p in layout.partitions
        ],
    }


@router.get("/api/lhsr/health/{device:path}")
async def lhsr_health(device: str, user=Depends(verify_token)):
    """Get composite health score for a disk.

    Path parameter:
        device: device name (e.g., "sdb") — NOT full /dev path for safety

    Returns:
        Health score (0-100), label, and contributing factors.
    """
    # Sanitize — only allow bare device names
    device = device.replace("/dev/", "").replace("/", "")
    if not device or len(device) > 20:
        raise HTTPException(400, "Invalid device name")

    # Get SMART data via smartctl (reuse existing pattern from storage_api)
    from storage_api import _run_args
    import json as _json

    run = _run_args
    if run is None:
        raise HTTPException(500, "Storage API not initialized")

    smart_h = _run_args(["smartctl", "-H", "-j", f"/dev/{device}"], timeout=5)
    smart_a = _run_args(["smartctl", "-A", "-j", f"/dev/{device}"], timeout=5)

    dh = DiskHealth(disk_path=f"/dev/{device}")

    # Parse health status
    if smart_h:
        try:
            data = _json.loads(smart_h)
            status = data.get("smart_status", {})
            if isinstance(status, dict) and not status.get("passed", True):
                dh.consecutive_errors += 1
        except Exception:
            pass

    # Parse attributes
    if smart_a:
        try:
            data = _json.loads(smart_a)
            attrs = data.get("ata_smart_attributes", {}).get("table", [])
            for attr in attrs:
                aid = attr.get("id", 0)
                val = attr.get("raw", {}).get("value", 0)
                if aid == 5:  # Reallocated Sectors Count
                    dh.smart_reallocated = val
                elif aid == 197:  # Current Pending Sector Count
                    dh.smart_pending = val
                elif aid == 198:  # Offline Uncorrectable
                    dh.smart_uncorrectable = val
                elif aid in (194, 190):  # Temperature
                    dh.temperature = val
                elif aid == 9:  # Power On Hours
                    dh.power_on_hours = val
                elif aid == 177:  # Wear Level (SSD)
                    dh.wear_level = val
        except Exception:
            pass

    score = compute_health_score(dh)
    label = health_label(score)
    color = health_color(score)

    return {
        "device": f"/dev/{device}",
        "score": score,
        "label": label,
        "color": color,
        "factors": {
            "reallocated_sectors": dh.smart_reallocated,
            "pending_sectors": dh.smart_pending,
            "uncorrectable_sectors": dh.smart_uncorrectable,
            "temperature_c": dh.temperature,
            "power_on_hours": dh.power_on_hours,
            "wear_level": dh.wear_level,
        },
    }


# ────────────────────────────────────────────────────────────
# Trend database endpoints
# ────────────────────────────────────────────────────────────

_trend_db = None


def _get_trend_db():
    """Get or initialize the trend database."""
    global _trend_db
    if _trend_db is None:
        from forgeos_lhsr_trend import TrendDB
        _trend_db = TrendDB("/var/lib/forgeos/lhsr_trends.db")
        _trend_db.open()
    return _trend_db


@router.get("/api/lhsr/trends")
async def lhsr_trends(user=Depends(verify_token)):
    """Get SMART trend data for all monitored disks.

    Returns:
        List of disk trends with slopes and warning flags.
    """
    db = _get_trend_db()
    disks = db.get_disk_paths()

    results = []
    for disk_path in disks:
        trend = db.query_trend(disk_path)
        latest = db.get_latest_snapshot(disk_path)
        if trend:
            results.append({
                "disk_path": disk_path,
                "data_points": trend.data_points,
                "reallocated_slope": round(trend.reallocated_slope, 2),
                "pending_slope": round(trend.pending_slope, 2),
                "uncorrectable_slope": round(trend.uncorrectable_slope, 2),
                "temperature_slope": round(trend.temperature_slope, 2),
                "warnings": {
                    "reallocated": trend.reallocated_warn,
                    "pending": trend.pending_warn,
                    "uncorrectable": trend.uncorrectable_warn,
                    "temperature": trend.temperature_warn,
                },
                "warning_text": db.get_warning_text(disk_path),
                "latest_snapshot": latest,
            })

    return {"disks": results}


@router.get("/api/lhsr/trends/{device:path}")
async def lhsr_trend_detail(device: str, user=Depends(verify_token)):
    """Get detailed trend data for a specific disk.

    Path parameter:
        device: device name (e.g., "sdb")

    Returns:
        Trend data with slopes, warnings, and latest snapshot.
    """
    device = device.replace("/dev/", "").replace("/", "")
    if not device or len(device) > 20:
        raise HTTPException(400, "Invalid device name")

    disk_path = f"/dev/{device}"
    db = _get_trend_db()

    trend = db.query_trend(disk_path)
    if not trend:
        raise HTTPException(404, f"No trend data for {disk_path}")

    return {
        "disk_path": disk_path,
        "data_points": trend.data_points,
        "reallocated_slope": round(trend.reallocated_slope, 2),
        "pending_slope": round(trend.pending_slope, 2),
        "uncorrectable_slope": round(trend.uncorrectable_slope, 2),
        "temperature_slope": round(trend.temperature_slope, 2),
        "warnings": {
            "reallocated": trend.reallocated_warn,
            "pending": trend.pending_warn,
            "uncorrectable": trend.uncorrectable_warn,
            "temperature": trend.temperature_warn,
        },
        "warning_text": db.get_warning_text(disk_path),
        "latest_snapshot": db.get_latest_snapshot(disk_path),
    }


@router.post("/api/lhsr/trends/snapshot")
async def lhsr_record_snapshot(body: dict, user=Depends(verify_token)):
    """Record a SMART snapshot for a disk.

    Request body:
        device: device name (e.g., "sdb")

    Returns:
        Recorded snapshot data.
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")

    device = body.get("device", "").replace("/dev/", "").replace("/", "")
    if not device or len(device) > 20:
        raise HTTPException(400, "Invalid device name")

    disk_path = f"/dev/{device}"

    # Get SMART data
    from storage_api import _run_args
    import json as _json

    run = _run_args
    if run is None:
        raise HTTPException(500, "Storage API not initialized")

    smart_a = run(["smartctl", "-A", "-j", disk_path], timeout=5)

    reallocated = 0
    pending = 0
    uncorrectable = 0
    temperature = 0
    power_on_hours = 0
    wear_level = 0

    if smart_a:
        try:
            data = _json.loads(smart_a)
            attrs = data.get("ata_smart_attributes", {}).get("table", [])
            for attr in attrs:
                aid = attr.get("id", 0)
                val = attr.get("raw", {}).get("value", 0)
                if aid == 5:
                    reallocated = val
                elif aid == 197:
                    pending = val
                elif aid == 198:
                    uncorrectable = val
                elif aid in (194, 190):
                    temperature = val
                elif aid == 9:
                    power_on_hours = val
                elif aid == 177:
                    wear_level = val
        except Exception:
            pass

    # Compute health score
    from forgeos_lhsr_health import DiskHealth, compute_health_score
    dh = DiskHealth(
        disk_path=disk_path,
        smart_reallocated=reallocated,
        smart_pending=pending,
        smart_uncorrectable=uncorrectable,
        temperature=temperature,
        power_on_hours=power_on_hours,
        wear_level=wear_level,
    )
    score = compute_health_score(dh)

    # Record to trend DB
    db = _get_trend_db()
    recorded = db.record_snapshot(
        disk_path=disk_path,
        reallocated=reallocated,
        pending=pending,
        uncorrectable=uncorrectable,
        temperature=temperature,
        power_on_hours=power_on_hours,
        wear_level=wear_level,
        health_score=score,
    )

    return {
        "recorded": recorded,
        "disk_path": disk_path,
        "health_score": score,
        "factors": {
            "reallocated": reallocated,
            "pending": pending,
            "uncorrectable": uncorrectable,
            "temperature": temperature,
            "power_on_hours": power_on_hours,
            "wear_level": wear_level,
        },
    }


# ────────────────────────────────────────────────────────────
# Scheduler endpoints
# ────────────────────────────────────────────────────────────

@router.get("/api/lhsr/scheduler")
async def lhsr_scheduler_status(user=Depends(verify_token)):
    """Get SMART snapshot scheduler status."""
    from forgeos_lhsr_scheduler import get_status
    return get_status()


@router.post("/api/lhsr/scheduler")
async def lhsr_scheduler_configure(body: dict, user=Depends(verify_token)):
    """Configure the SMART snapshot scheduler.

    Request body:
        action: "install" or "remove"
        calendar: systemd calendar expression (default: daily)
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")

    action = body.get("action", "install")
    calendar = body.get("calendar", "daily")

    from forgeos_lhsr_scheduler import install_scheduler, remove_scheduler

    if action == "install":
        try:
            install_scheduler(calendar=calendar)
            return {"ok": True, "detail": f"Scheduler installed (calendar: {calendar})"}
        except Exception as e:
            raise HTTPException(500, str(e))
    elif action == "remove":
        try:
            remove_scheduler()
            return {"ok": True, "detail": "Scheduler removed"}
        except Exception as e:
            raise HTTPException(500, str(e))
    else:
        raise HTTPException(400, "action must be 'install' or 'remove'")
