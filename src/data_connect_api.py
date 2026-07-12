"""Data Connect API — manage databases for multiple clients.

Two kinds of managed database:
  • file    — file-based DBs (ElevateDB, Access, DBISAM, SQLite, ...) whose
              files live on a Samba share. Concurrency/corruption protection
              comes from SMB share modes (oplocks off, strict locking on),
              applied per-share by the Samba generator (see patch 2).
  • postgres/mysql — real client/server engines. Data dir lives LOCALLY (never
              on a share — that corrupts them); clients connect over the native
              port (5432/3306); the engine's own MVCC/ACID handles concurrency.
              Managed as a service (see patch 3).

This module replaces the old standalone forgeos-filedb daemon. Its advisory-lock
approach never worked cross-protocol (client apps use their own file locking and
ignore outside advisory locks), so it's gone. What's kept and folded in here:
browsing/import, mDNS broadcast (via a generated Avahi service), DB file-type
detection, and per-app tagging — all config-DB backed like every other subsystem.

Dependencies injected by the main app at include time:
  • verify_token for auth; user["role"] == "admin" for writes.
  • set_audit(fn) for the audit log.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token  # type: ignore
import forgeos_config as fc

router = APIRouter()

# Root under which file-based DB directories are tracked (mirrors the NAS pool).
WATCH_ROOT = Path(os.environ.get("DATA_CONNECT_ROOT", "/srv/nas"))

# File-DB extensions -> the app/engine family they belong to. Used to auto-tag
# an imported directory. Ported from the old daemon's detection table.
DB_FAMILIES: dict[str, str] = {
    ".edb": "ElevateDB", ".edbt": "ElevateDB", ".edbi": "ElevateDB", ".edbl": "ElevateDB",
    ".db": "DBISAM", ".px": "Paradox", ".mb": "Paradox", ".val": "Paradox",
    ".nxd": "NexusDB", ".nxi": "NexusDB", ".nxl": "NexusDB",
    ".dbf": "dBase/FoxPro", ".cdx": "dBase/FoxPro", ".fpt": "dBase/FoxPro", ".idx": "dBase/FoxPro",
    ".mdb": "Access", ".accdb": "Access", ".ldb": "Access", ".laccdb": "Access",
    ".sqlite": "SQLite", ".sqlite3": "SQLite", ".sqlite-wal": "SQLite",
    ".fdb": "Firebird", ".gdb": "Firebird",
    ".dat": "TurboDB", ".tdb": "TurboDB", ".tdx": "TurboDB",
}

# ── audit injection (same pattern as forgeos_pages_api) ──────────────────────
__audit_impl__ = None


def set_audit(fn) -> None:
    global __audit_impl__
    __audit_impl__ = fn


def _audit(who: str, action: str, status: str, detail: str | None = None) -> None:
    if __audit_impl__:
        try:
            __audit_impl__(who, action, status, detail)
        except Exception:
            pass


def _safe_under_root(path: str) -> Path:
    """Resolve `path` and ensure it stays under WATCH_ROOT (no traversal)."""
    p = Path(path)
    if not p.is_absolute():
        p = WATCH_ROOT / p
    resolved = p.resolve()
    root = WATCH_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(400, f"path escapes {root}")
    return resolved


def detect_family(directory: Path) -> str:
    """Best-effort DB family for a directory, by file extension. "" if unknown."""
    try:
        for entry in directory.iterdir():
            fam = DB_FAMILIES.get(entry.suffix.lower())
            if fam:
                return fam
    except (OSError, PermissionError):
        pass
    return ""


@router.get("/api/data-connect")
async def list_databases(user=Depends(verify_token)):
    """Tracked databases + broadcast state. Each entry reports its directory /
    data path, owning app, and type."""
    cfg = fc.load()
    dc = cfg.data_connect
    out = []
    for d in dc.databases:
        p = Path(d.data_path)
        out.append({
            "name": d.name, "kind": d.kind, "data_path": d.data_path,
            "app": d.app, "db_type": d.db_type, "port": d.port,
            "comment": d.comment, "exists": p.exists(),
        })
    return {"enabled": dc.enabled, "broadcast": dc.broadcast, "databases": out}


@router.post("/api/data-connect/import")
async def import_database(body: dict, user=Depends(verify_token)):
    """Import (track) an existing file-based DB directory. Auto-detects the DB
    family for tagging; the caller supplies the owning app. Server DBs
    (postgres/mysql) are added via their own provisioning path, not here."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name = str(body.get("name", "")).strip()
    data_path = str(body.get("data_path", "")).strip()
    app = str(body.get("app", "")).strip()
    comment = str(body.get("comment", "")).strip()
    if not name or not data_path:
        raise HTTPException(400, "name and data_path required")
    directory = _safe_under_root(data_path)
    if not directory.is_dir():
        raise HTTPException(400, f"not a directory: {directory}")
    family = str(body.get("db_type", "")).strip() or detect_family(directory)

    cfg = fc.load()
    if any(d.name.lower() == name.lower() for d in cfg.data_connect.databases):
        raise HTTPException(409, f"a database named {name!r} already exists")
    try:
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name=name, kind="file", data_path=str(directory),
            app=app, db_type=family, port=0, comment=comment))
    except Exception as e:
        raise HTTPException(400, f"invalid: {e}")
    cfg.data_connect.enabled = True
    fc.save(cfg)
    _audit(user["sub"], "data_connect.import", "success",
           f"{name} ({family or 'unknown'}) at {directory}")
    return {"ok": True, "db_type": family}


@router.delete("/api/data-connect/{name}")
async def remove_database(name: str, user=Depends(verify_token)):
    """Stop tracking a database. Files/data on disk are left untouched."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    cfg = fc.load()
    name = name.strip()
    if not any(d.name == name for d in cfg.data_connect.databases):
        raise HTTPException(404, f"no such database: {name}")
    cfg.data_connect.databases = [d for d in cfg.data_connect.databases if d.name != name]
    fc.save(cfg)
    _audit(user["sub"], "data_connect.remove", "success", name)
    return {"ok": True}


@router.post("/api/data-connect/broadcast")
async def set_broadcast(body: dict, user=Depends(verify_token)):
    """Toggle mDNS/Avahi broadcast. The generator writes/removes the Avahi
    service file on the next config apply."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    cfg = fc.load()
    cfg.data_connect.broadcast = bool(body.get("broadcast", True))
    fc.save(cfg)
    _audit(user["sub"], "data_connect.broadcast", "success",
           "on" if cfg.data_connect.broadcast else "off")
    return {"ok": True, "broadcast": cfg.data_connect.broadcast}


@router.get("/api/data-connect/detect")
async def detect_dir(path: str, user=Depends(verify_token)):
    """Detect the DB family in a directory before importing (UI helper)."""
    directory = _safe_under_root(path)
    if not directory.is_dir():
        raise HTTPException(400, "not a directory")
    return {"path": str(directory), "db_type": detect_family(directory)}
