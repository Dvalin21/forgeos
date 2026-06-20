"""ForgeOS — Storage API surface.

Mounts under the existing FastAPI app via:

    from storage_api import router as storage_router, set_helpers as set_storage_helpers
    set_storage_helpers(run_args=_run_args, audit=_audit)
    app.include_router(storage_router)

Routes:
  • GET  /api/storage/pools          — pool status (forgeos-pool-status)
  • GET  /api/storage/drives         — all disks with SMART
  • POST /api/storage/pool           — create pool (admin, mdadm)
  • POST /api/storage/drive          — add drive to pool (admin, mdadm)
  • GET  /api/storage/df             — disk-free per mount
  • GET  /api/storage/snapshots      — list btrfs snapshots
  • POST /api/storage/snapshot       — create snapshot (admin)
  • GET  /api/storage/smart/{device} — SMART detail
  • GET  /api/storage/hotswap-log    — hot-swap event log
  • GET  /api/storage/smart-alerts   — SMART alerts log
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token
import forgeos_config as fc
import forgeos_diskprep as dp

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
) -> None:
    global _run_args, _audit
    _run_args = run_args
    _audit = audit


@router.get("/api/storage/pools")
async def storage_pools(user=Depends(verify_token)):
    # V2 engine: pools are read from the config-DB — the single source of
    # truth, ONE entry per pool. (The old forgeos-pool-status scanned the
    # system live and listed a raid pool once PER DEVICE, so a 2-disk raid1
    # showed up twice.) Mount state is checked live per pool.
    cfg = fc.load()
    pools = []
    for p in cfg.storage.pools:
        mp = p.resolved_mountpoint()
        pools.append({
            "name": p.name,
            "raid_level": p.raid_level,
            "mountpoint": mp,
            "devices": p.devices,
            "uuid": p.uuid,
            "mounted": Path(mp).is_mount(),
            "health": "ok" if Path(mp).is_mount() else "unmounted",
        })
    return {"pools": pools, "unassigned": []}


@router.get("/api/storage/drives")
async def storage_drives(user=Depends(verify_token)):
    """List all drives with SMART status"""
    drives = []
    # Get list of block devices (lsblk -J — no jq needed, parse JSON directly)
    out = _run_args(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL,TRAN"], timeout=10)
    if out:
        try:
            raw = json.loads(out)
            # lsblk -J wraps in { "blockdevices": [...] }
            blockdevices = raw.get("blockdevices", []) if isinstance(raw, dict) else raw
            for dev in blockdevices:
                if not isinstance(dev, dict) or dev.get("type") != "disk":
                    continue
                name = dev.get("name", "")
                if not name:
                    continue
                # Get SMART data via arg-list (no shell)
                smart_out = _run_args(["smartctl", "-H", "-j", f"/dev/{name}"], timeout=5)
                temp_out = _run_args(["smartctl", "-A", "-j", f"/dev/{name}"], timeout=5)
                smart_data = {}
                if smart_out:
                    try:
                        smart_data = json.loads(smart_out)
                    except Exception as e:
                        logger.debug("smartctl -H JSON parse failed for %s: %s", name, e)
                # Parse temperature from SMART attributes
                temp_val = 0
                if temp_out:
                    try:
                        temp_json = json.loads(temp_out)
                        for entry in temp_json.get("ATA_SmartData", {}).get("Attributes", {}).get("Table", []):
                            if entry.get("ID") == 194:
                                temp_val = int(entry.get("Value", 0))
                                break
                    except Exception as e:
                        logger.debug("smartctl -A JSON parse failed for %s: %s", name, e)
                # Determine health
                health = 95
                smart_status = smart_data.get("smart_status")
                if isinstance(smart_status, dict):
                    health = 100 if smart_status.get("passed") else 50
                drives.append({
                    "name": f"/dev/{name}",
                    "type": dev.get("trans", "unknown").upper() if dev.get("trans") else "HDD",
                    "size": dev.get("size", "0"),
                    "model": dev.get("model", "").strip() or "Unknown",
                    "temp": temp_val,
                    "health": health,
                })
        except Exception as e:
            logger.warning("lsblk parse failed: %s", e)
    # Fallback: use lsblk directly
    if not drives:
        out = _run_args(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL"], timeout=10)
        try:
            raw = json.loads(out) if out else {}
            blockdevices = raw.get("blockdevices", []) if isinstance(raw, dict) else raw
            for dev in blockdevices:
                if not isinstance(dev, dict) or dev.get("type") != "disk":
                    continue
                drives.append({
                    "name": f'/dev/{dev.get("name","")}',
                    "type": "HDD",
                    "size": dev.get("size", "0"),
                    "model": dev.get("model", "").strip() or "Unknown",
                    "temp": 0,
                    "health": 95,
                })
        except Exception as e:
            logger.warning("lsblk fallback parse failed: %s", e)
    return {"drives": drives}


@router.post("/api/storage/pool")
async def create_pool(body: dict, user=Depends(verify_token)):
    """Create a btrfs pool through the GUARDED disk-prep path. Every disk is
    checked (system disk untouchable, mounted/in-array/has-data refused) before
    anything is written, and mounted by UUID. Replaces the old unguarded
    mdadm --create which had no safety checks at all."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name = body.get("name", "")
    level = body.get("level", "raid1")
    drives = body.get("drives", [])
    force = bool(body.get("force", False))

    try:
        all_disks = dp.inspect_disks()
        targets = [dp.find_disk(all_disks, d) for d in drives]
        plan = dp.plan_pool(name, level, targets, force=force)

        def _record(result):
            cfg = fc.load()
            cfg.storage.pools.append(fc.StoragePool(
                name=plan.name, raid_level=plan.raid_level,
                devices=plan.devices, mountpoint=result["mountpoint"],
                uuid=result["uuid"]))
            fc.save(cfg)
            reloaded = fc.load()
            if not any(p.uuid == result["uuid"] for p in reloaded.storage.pools):
                raise RuntimeError("config-DB save did not persist the pool")

        # re-inspect right before executing (guards re-check inside execute);
        # the record step makes persistence part of the atomic operation.
        result = dp.execute_pool(plan, dp.inspect_disks(), force=force, record=_record)
    except dp.DiskGuardError as e:
        raise HTTPException(400, detail=str(e))

    _audit(user["sub"], "storage.pool.create", "success",
           f"btrfs {level} pool '{name}' at {result['mountpoint']} "
           f"({len(plan.devices)} drives)")
    return {"ok": True, "pool": {"name": name, "mountpoint": result["mountpoint"],
                                 "uuid": result["uuid"]}}


@router.post("/api/storage/drive")
async def add_drive(body: dict, user=Depends(verify_token)):
    """Add a drive to an existing RAID pool — wraps mdadm --manage --add."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    pool   = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    device = re.sub(r"[^a-zA-Z0-9_/]", "", str(body.get("device", "")))
    if not pool:
        raise HTTPException(400, "Pool name required")
    if not device:
        raise HTTPException(400, "Device path required")
    if not device.startswith("/dev/"):
        device = "/dev/" + device
    try:
        r = subprocess.run(
            ["mdadm", "--manage", f"/dev/md/{pool}", "--add", device],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            raise HTTPException(500, detail=r.stderr.strip() or "mdadm --add failed")
    except FileNotFoundError:
        raise HTTPException(500, detail="mdadm not installed on this system")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, detail="Drive add timed out")
    _audit(user["sub"], "storage.drive.add", "success",
            f"Drive {device} added to pool {pool}")
    return {"ok": True, "message": f"Drive {device} added to pool {pool}"}


@router.get("/api/storage/df")
async def storage_df(user=Depends(verify_token)):
    """Disk usage per btrfs mount"""
    results = []
    mounts = _run_args(["findmnt", "-t", "btrfs", "-o", "TARGET,SOURCE", "-n"]).splitlines()
    for line in mounts:
        parts = line.split()
        if len(parts) < 2:
            continue
        mp, src = parts[0], parts[1]
        out = _run_args(["df", "-B1", mp])
        rows = out.splitlines()
        if len(rows) >= 2:
            cols = rows[1].split()
            if len(cols) >= 5:
                results.append({
                    "mount": mp, "source": src,
                    "total": int(cols[1]), "used": int(cols[2]),
                    "avail": int(cols[3]), "pct": cols[4],
                })
    return results


@router.get("/api/storage/snapshots")
async def storage_snapshots(pool: str = "", user=Depends(verify_token)):
    if pool:
        pool = re.sub(r"[^a-zA-Z0-9_-]", "", pool)  # sanitize pool name
        out = _run_args(["snapper", "-c", pool, "list",
                         "--output-cols", "number,date,description"])
    else:
        configs = _run_args(["snapper", "list-configs"]).splitlines()
        # Skip header lines (NR>2 equivalent)
        configs = [l.split()[0] for l in configs if l.strip() and not l.startswith("Config")]
        out = ""
        for c in configs:
            c_out = _run_args(["snapper", "-c", c, "list",
                               "--output-cols", "number,date,description"])
            out += f"=== {c} ===\n{c_out}\n"
    return {"snapshots": out}


@router.post("/api/storage/snapshot")
async def create_snapshot(body: dict, user=Depends(verify_token)):
    pool = body.get("pool", "")
    desc = body.get("description", "manual")
    if pool:
        pool = re.sub(r"[^a-zA-Z0-9_-]", "", pool)
        desc = re.sub(r"[^a-zA-Z0-9 _.-]", "", desc)[:80]
        r = subprocess.run(
            ["snapper", "-c", pool, "create",
             "--description", desc, "--cleanup-algorithm", "timeline"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            raise HTTPException(status_code=500,
                                detail="Snapshot failed: %s" % r.stderr.strip())
    else:
        configs = _run_args(["snapper", "list-configs"]).splitlines()
        configs = [l.split()[0] for l in configs if l.strip() and not l.startswith("Config")]
        for c in configs:
            r = subprocess.run(
                ["snapper", "-c", c, "create",
                 "--description", desc, "--cleanup-algorithm", "timeline"],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode != 0:
                raise HTTPException(status_code=500,
                                    detail="Snapshot failed for %s: %s" % (c, r.stderr.strip()))
    _audit(user["sub"], "storage.snapshot.create", "success",
            f"Snapshot '{desc}' on {'all configs' if not pool else pool}")
    return {"ok": True, "message": f"Snapshot created: {desc}"}


@router.get("/api/storage/smart/{device}")
async def smart_detail(device: str, user=Depends(verify_token)):
    # Strict sanitization: only allow actual block device names
    # Block /dev/ prefix, path traversal, and special devices
    dev = re.sub(r"[^a-z0-9]", "", device)
    # Additional check: reject if it looks like a path or special device
    if dev in ("loop", "ram", "dm", "md") or len(dev) > 20:
        raise HTTPException(400, "Invalid device name")
    out = _run_args(["smartctl", "-a", f"/dev/{dev}"])
    return {"device": f"/dev/{dev}", "output": out}


@router.get("/api/storage/hotswap-log")
async def hotswap_log(user=Depends(verify_token)):
    log = Path("/var/log/forgeos/hotswap.log")
    lines = log.read_text().splitlines()[-50:] if log.exists() else []
    return {"lines": lines}


@router.get("/api/storage/smart-alerts")
async def smart_alerts(user=Depends(verify_token)):
    log = Path("/var/log/forgeos/smart-alerts.log")
    lines = log.read_text().splitlines()[-100:] if log.exists() else []
    return {"alerts": lines}

