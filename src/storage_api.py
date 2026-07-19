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


def _dev(name: str) -> str:
    """Validate a bare device name (e.g. 'sdb') into a /dev path."""
    from fastapi import HTTPException
    d = re.sub(r"[^a-zA-Z0-9]", "", str(name))
    if not d or len(d) > 20:
        raise HTTPException(400, "Invalid device name")
    return "/dev/" + d


def _pool_mount(pool: str) -> str:
    """Resolve a pool NAME to its btrfs mountpoint from config, and verify it
    is actually a mounted btrfs filesystem before any device operation. btrfs
    is managed by mountpoint, so this is the anchor for add/replace/scrub."""
    from fastapi import HTTPException
    cfg = fc.load()
    match = next((p for p in cfg.storage.pools if p.name == pool), None)
    if match is None:
        raise HTTPException(404, f"No such pool: {pool}")
    mp = match.resolved_mountpoint()
    if not Path(mp).is_mount():
        raise HTTPException(409, f"Pool '{pool}' is not mounted at {mp}")
    return mp


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
    _enrich_drive_roles(drives)
    return {"drives": drives}


def _enrich_drive_roles(drives: list) -> None:
    """Annotate each drive with the truth the UI needs to stop showing every
    disk as if it were pooled:

      role     : "os" (holds root/boot/swap) | "pool" (in a config pool)
                 | "spare" (attached, unpooled)
      pool     : the owning pool's name, or "" 
      rota     : rotational? True=HDD, False=SSD/NVMe (from lsblk ROTA)
      media    : "nvme" | "ssd" | "hdd" — for the right icon + always-monitor
      os_label : "Forge" on the system disk (shown as its pool cell)

    Source of truth is cross-referenced: the disk inspector for OS/rotational,
    config for pool membership. This is the reconciliation the two separate
    views (live hardware vs config pools) previously lacked.
    """
    try:
        disks = {d.path: d for d in dp.inspect_disks()}
    except Exception:
        disks = {}
    cfg = fc.load()
    dev_to_pool = {}
    for p in cfg.storage.pools:
        for dev in p.devices:
            dev_to_pool[dev] = p.name

    # rotational flag straight from lsblk (ROTA), keyed by /dev path
    rota_map = {}
    try:
        out = _run_args(["lsblk", "-J", "-d", "-o", "NAME,ROTA,TRAN"], timeout=10)
        raw = json.loads(out) if out else {}
        for dev in (raw.get("blockdevices", []) if isinstance(raw, dict) else raw):
            rota_map[f"/dev/{dev.get('name','')}"] = {
                "rota": str(dev.get("rota")) in ("1", "True", "true"),
                "tran": (dev.get("tran") or "").lower()}
    except Exception:
        pass

    for d in drives:
        path = d.get("name", "")
        info = disks.get(path)
        rt = rota_map.get(path, {})
        tran = rt.get("tran") or (d.get("type", "") or "").lower()
        rota = rt.get("rota", True)
        # media class drives the icon and the "monitor regardless of type" rule
        if tran == "nvme" or path.startswith("/dev/nvme"):
            media = "nvme"
        elif rota is False:
            media = "ssd"
        else:
            media = "hdd"
        d["rota"] = rota
        d["media"] = media
        if info is not None and info.is_system:
            d["role"] = "os"
            d["pool"] = ""
            d["os_label"] = "Forge"
        elif path in dev_to_pool:
            d["role"] = "pool"
            d["pool"] = dev_to_pool[path]
        else:
            d["role"] = "spare"
            d["pool"] = ""


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
    """Add a drive to an existing btrfs pool via `btrfs device add`.

    btrfs pools are managed by MOUNTPOINT, not an /dev/md node — the old
    mdadm --add path could never work against the btrfs pools this same page
    creates. The device is added online; the caller should run a scrub or let
    btrfs rebalance as needed.
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    pool   = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    device = _dev(body.get("device", ""))
    if not pool:
        raise HTTPException(400, "Pool name required")
    mount = _pool_mount(pool)
    try:
        r = subprocess.run(["btrfs", "device", "add", "-f", device, mount],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise HTTPException(400, r.stderr.strip() or "btrfs device add failed")
    except FileNotFoundError:
        raise HTTPException(500, "btrfs-progs not installed on this system")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Drive add timed out")
    _audit(user["sub"], "storage.drive.add", "success",
           f"{device} added to btrfs pool {pool} ({mount})")

    # Persist the new device to config — WITHOUT this the pool card kept
    # showing the original device count while btrfs actually had one more
    # (the "says 2 but there are 3" divergence). Config is the source of
    # truth the pools view reads, so it must track the live filesystem.
    cfg = fc.load()
    match = next((p for p in cfg.storage.pools if p.name == pool), None)
    if match is not None and device not in match.devices:
        match.devices.append(device)
        fc.save(cfg)
    return {"ok": True, "message": f"Drive {device} added to pool {pool}"}


@router.get("/api/storage/df")
async def storage_df(user=Depends(verify_token)):
    """Disk usage per btrfs mount — ONE row per mountpoint.

    findmnt reads the calling process's mount table verbatim, and the same
    filesystem legitimately appears there more than once: bind mounts,
    subvolume mounts, or — as this service hits — a systemd
    ProtectSystem=strict + ReadWritePaths=/srv namespace that reflects the
    /srv/nas/<pool> submount a second time when it binds /srv back read-write.
    So one findmnt line != one filesystem; dedup by mountpoint.
    """
    results = []
    seen: set[str] = set()
    mounts = _run_args(["findmnt", "-t", "btrfs", "-o", "TARGET,SOURCE", "-n"]).splitlines()
    for line in mounts:
        parts = line.split()
        if len(parts) < 2:
            continue
        mp, src = parts[0], parts[1]
        if mp in seen:          # same fs reflected by a bind/subvol/namespace mount
            continue
        seen.add(mp)
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

