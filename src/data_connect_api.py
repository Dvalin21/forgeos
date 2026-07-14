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
import logging
import subprocess
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token  # type: ignore
import forgeos_config as fc

router = APIRouter()

# Root under which file-based DB directories are tracked (mirrors the NAS pool).
logger = logging.getLogger("forgeos.data_connect")

WATCH_ROOT = Path(os.environ.get("DATA_CONNECT_ROOT", "/srv/nas"))

# File-DB extension -> family table lives in forgeos_config (the Samba
# generator builds veto patterns from it). Re-exported here for callers/tests.
DB_FAMILIES = fc.DB_FAMILIES

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


# Save the config-DB then regenerate the services that render from
# data_connect: samba (protected DB shares) and avahi (mDNS broadcast).
# Overridable in tests so they don't write /etc or touch systemctl.
_apply = None


def _apply_data_connect(cfg) -> None:
    if _apply is not None:
        _apply(cfg)
        return
    from generators import registry
    fc.save(cfg)
    names = ["samba", "avahi", "dbserver"] + (
        ["ufw"] if cfg.firewall.enabled else [])
    for n in names:
        r = registry.apply_one(n, cfg=cfg)
        if not r.ok:
            logger.error("data-connect apply failed: %s: %s", n, r.error)


def set_apply(fn) -> None:
    """Test seam: inject a fake apply (save+generate+reload)."""
    global _apply
    _apply = fn


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
            # file DBs: share-mode protection is live iff samba renders the
            # share. Server DBs are protected by the engine itself.
            "protected": (cfg.samba.enabled and dc.enabled) if d.kind == "file" else True,
        })
    return {"enabled": dc.enabled, "broadcast": dc.broadcast,
            "samba_enabled": cfg.samba.enabled, "databases": out}


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
    # A file DB IS a Samba share — its whole protection model is SMB share
    # modes. Without smbd there is no access path at all, so refuse loudly
    # instead of tracking a database nobody can reach.
    if not cfg.samba.enabled:
        raise HTTPException(409, "File sharing (Samba) is disabled — enable it "
                                 "before importing file-based databases")
    if any(d.name.lower() == name.lower() for d in cfg.data_connect.databases):
        raise HTTPException(409, f"a database named {name!r} already exists")
    if any(sh.name.lower() == name.lower() for sh in cfg.samba.shares):
        raise HTTPException(409, f"{name!r} collides with an existing Samba share")
    if name.lower() in ("global", "homes", "printers"):
        raise HTTPException(400, f"{name!r} is a reserved Samba section name")
    try:
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name=name, kind="file", data_path=str(directory),
            app=app, db_type=family, port=0, comment=comment))
    except Exception as e:
        raise HTTPException(400, f"invalid: {e}")
    cfg.data_connect.enabled = True
    _apply_data_connect(cfg)
    _audit(user["sub"], "data_connect.import", "success",
           f"{name} ({family or 'unknown'}) at {directory}")
    return {"ok": True, "db_type": family}


# ── server databases (patch 3) ──────────────────────────────────────────────
# Debian 13 facts, not guesses: package/service names, default ports, data
# dirs. MariaDB is Debian's "mysql"; kind stays "mysql" for client familiarity.
ENGINES = {
    "postgres": {"pkg": "postgresql", "svc": "postgresql", "port": 5432,
                 "data": "/var/lib/postgresql", "label": "PostgreSQL"},
    "mysql":    {"pkg": "mariadb-server", "svc": "mariadb", "port": 3306,
                 "data": "/var/lib/mysql", "label": "MariaDB"},
}

# Subprocess seam for tests (dpkg / systemd-run / systemctl).
_run_cmd = None


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    if _run_cmd is not None:
        return _run_cmd(cmd, timeout)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def set_run(fn) -> None:
    """Test seam: fake out dpkg/systemctl/systemd-run."""
    global _run_cmd
    _run_cmd = fn


def _engine_installed(pkg: str) -> bool:
    return _run(["dpkg", "-s", pkg]).returncode == 0


@router.post("/api/data-connect/register-server")
async def register_server(body: dict, user=Depends(verify_token)):
    """Track (and optionally install) a local Postgres/MariaDB instance.

    Data dir stays local — server DBs never render a Samba share (SMB
    caching breaks their write ordering). Clients use the native port.
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name = str(body.get("name", "")).strip()
    engine = str(body.get("engine", "")).strip()
    install = bool(body.get("install", False))
    if engine not in ENGINES:
        raise HTTPException(400, f"unknown engine {engine!r} — expected one of "
                                 f"{sorted(ENGINES)}")
    eng = ENGINES[engine]
    cfg = fc.load()
    if any(d.name.lower() == name.lower() for d in cfg.data_connect.databases):
        raise HTTPException(409, f"a database named {name!r} already exists")

    if not _engine_installed(eng["pkg"]):
        if not install:
            raise HTTPException(
                409, f"{eng['label']} is not installed. Re-submit with "
                     f"install=true, or run: apt-get install -y {eng['pkg']}")
        # apt writes /usr and /var/lib/dpkg — impossible inside this
        # service's ProtectSystem=strict sandbox. systemd-run executes it as
        # a transient unit under the system manager, outside the sandbox.
        # NEVER block this request on apt: nginx's proxy_read_timeout would
        # 504 long before a package install finishes. Start a NAMED unit,
        # return 202, and let the client poll this same endpoint — the retry
        # completes registration once dpkg sees the package. Idempotent:
        # while the named unit is active, repeat calls just report 202.
        unit = f"forgeos-engine-install-{engine}"
        if _run(["systemctl", "is-active", "--quiet", unit]).returncode != 0:
            _audit(user["sub"], "data_connect.install", "started", eng["pkg"])
            res = _run(["systemd-run", "--collect", "--quiet",
                        f"--unit={unit}",
                        "--setenv=DEBIAN_FRONTEND=noninteractive",
                        "apt-get", "install", "-y", eng["pkg"]], timeout=60)
            if res.returncode != 0:
                _audit(user["sub"], "data_connect.install", "failed", eng["pkg"])
                raise HTTPException(502, f"could not start install: "
                                         f"{(res.stderr or res.stdout or '')[-300:]}")
        return JSONResponse(status_code=202, content={
            "installing": True, "engine": engine,
            "detail": f"Installing {eng['label']} — poll this endpoint until "
                      f"it returns 200"})

    # Registering means managing: the engine must be running and survive boot.
    res = _run(["systemctl", "enable", "--now", eng["svc"]], timeout=120)
    if res.returncode != 0:
        raise HTTPException(502, f"could not start {eng['svc']}: "
                                 f"{(res.stderr or res.stdout or '')[-300:]}")

    try:
        cfg.data_connect.databases.append(fc.ManagedDatabase(
            name=name, kind=engine, data_path=eng["data"],
            app=str(body.get("app", "")).strip(), db_type=eng["label"],
            port=int(body.get("port", 0)) or eng["port"],
            comment=str(body.get("comment", "")).strip()))
    except Exception as e:
        raise HTTPException(400, f"invalid: {e}")
    cfg.data_connect.enabled = True
    _apply_data_connect(cfg)
    _audit(user["sub"], "data_connect.register_server", "success",
           f"{name} ({engine})")
    return {"ok": True, "engine": engine, "port": eng["port"]}


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
    _apply_data_connect(cfg)
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
    _apply_data_connect(cfg)
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
