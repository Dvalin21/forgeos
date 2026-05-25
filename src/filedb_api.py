"""
ForgeFileDB API Module
═══════════════════════════════════════════════════════════════
Provides REST API endpoints for ForgeFileDB management.
Proxies requests to the ForgeFileDB daemon on localhost:12010.

Endpoints:
  GET    /api/filedb/status      - Daemon status + lock registry
  GET    /api/filedb/clients     - Connected SMB clients
  GET    /api/filedb/databases   - Discovered DB files
  GET    /api/filedb/locks       - Current file lock state
  GET    /api/filedb/snapshots   - List snapshots
  POST   /api/filedb/snapshots   - Create snapshot
  POST   /api/filedb/restore     - Restore snapshot
  GET    /api/filedb/settings    - Get settings
  PUT    /api/filedb/settings    - Update settings
  GET    /api/filedb/log         - Daemon log

WebSocket:
  /ws/filedb                     - Real-time daemon events
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx  # new dependency: httpx for async HTTP calls
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from forgeos_auth import verify_token, verify_ws_token

# ── Config ──────────────────────────────────────────────────
DAEMON_BASE = os.environ.get("FILEDB_DAEMON_URL", "http://127.0.0.1:12010")
MOCK_MODE = os.environ.get("MOCK_FILEDB", "false").lower() == "true"
DAEMON_TIMEOUT = 5  # seconds

# ── Router ──────────────────────────────────────────────────
router = APIRouter(
    prefix="/api/filedb",
    tags=["filedb"],
    dependencies=[Depends(verify_token)],
)


# ── HTTP client helper ──────────────────────────────────────
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=DAEMON_BASE, timeout=DAEMON_TIMEOUT)
    return _client


async def _proxy_get(path: str) -> dict:
    """GET from daemon, return JSON or raise 503."""
    if MOCK_MODE:
        raise RuntimeError("Mock mode enabled — daemon not contacted")
    client = await _get_client()
    try:
        r = await client.get(path)
        r.raise_for_status()
        return r.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"ForgeFileDB daemon unreachable: {e}",
        )


async def _proxy_post(path: str, body: dict | None = None) -> dict:
    """POST to daemon, return JSON or raise 503."""
    if MOCK_MODE:
        raise RuntimeError("Mock mode enabled — daemon not contacted")
    client = await _get_client()
    try:
        r = await client.post(path, json=body or {})
        r.raise_for_status()
        return r.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"ForgeFileDB daemon unreachable: {e}",
        )


# ── Mock data (dev / demo only) ─────────────────────────────
# These are only used when MOCK_FILEDB=true for development
# without the actual daemon.

_MOCK_STATUS = {
    "daemon_running": True,
    "connected_clients": 3,
    "open_databases": 5,
    "snapshots_today": 12,
    "total_conflicts": 0,
    "uptime": "2h 34m",
    "version": "1.0.0",
    "mock_mode": True,
}

_MOCK_CLIENTS = [
    {"ip": "192.168.1.10", "user": "alice", "files_open": 3,
     "connected_since": "2026-04-28T14:20:00"},
    {"ip": "192.168.1.15", "user": "bob", "files_open": 1,
     "connected_since": "2026-04-28T15:10:00"},
    {"ip": "192.168.1.20", "user": "charlie", "files_open": 2,
     "connected_since": "2026-04-28T13:45:00"},
]

_MOCK_DATABASES = {
    "databases": [
        {
            "dir": "/data/databases/finance",
            "files": [
                {"name": "ledger.db", "size": 1048576,
                 "modified": "2026-04-28T14:30:00", "ext": ".db"},
                {"name": "payroll.db", "size": 2097152,
                 "modified": "2026-04-28T13:15:00", "ext": ".db"},
            ],
        },
        {
            "dir": "/data/databases/inventory",
            "files": [
                {"name": "stock.db", "size": 5242880,
                 "modified": "2026-04-28T15:00:00", "ext": ".db"},
                {"name": "orders.db", "size": 3145728,
                 "modified": "2026-04-28T14:45:00", "ext": ".db"},
            ],
        },
    ]
}

_MOCK_SNAPSHOTS = {
    "snapshots": [
        {"ts": "20260428T153000", "db_dir": "/data/databases/finance",
         "method": "btrfs", "reason": "write_threshold"},
        {"ts": "20260428T145000", "db_dir": "/data/databases/inventory",
         "method": "btrfs", "reason": "user_request"},
    ]
}

_MOCK_SETTINGS = {
    "snapshot_debounce_sec": 10,
    "max_snapshots": 24,
    "write_threshold": 100,
    "watch_root": "/srv/nas",
}

_MOCK_LOG = {
    "lines": [
        "[2026-04-28T15:30:00] START  ForgeFileDB daemon v1.0.0 started",
        "[2026-04-28T15:30:01] SNAP   Auto-snapshot created for /data/databases/finance",
        "[2026-04-28T15:25:00] LOCK   File locked: orders.db by 192.168.1.10",
    ]
}


# ── Endpoints ───────────────────────────────────────────────

@router.get("/status")
async def filedb_status():
    """Daemon status and lock registry summary."""
    if MOCK_MODE:
        return _MOCK_STATUS
    return await _proxy_get("/api/status")


@router.get("/clients")
async def filedb_clients():
    """Connected SMB clients with open files."""
    if MOCK_MODE:
        return {"clients": _MOCK_CLIENTS}
    return await _proxy_get("/api/clients")


@router.get("/databases")
async def filedb_databases():
    """Discovered database files grouped by directory."""
    if MOCK_MODE:
        return _MOCK_DATABASES
    return await _proxy_get("/api/databases")


@router.get("/locks")
async def filedb_locks():
    """Current file lock registry."""
    if MOCK_MODE:
        status = _MOCK_STATUS.copy()
        status["lock_details"] = {
            "files": {
                "/data/databases/finance/payroll.db": {
                    "holders": [
                        {"client": "192.168.1.15", "mode": "EXCLUSIVE",
                         "since": "2026-04-28T15:05:00"}
                    ]
                }
            }
        }
        return status
    return await _proxy_get("/api/status")


@router.get("/snapshots")
async def filedb_snapshots(
    db_dir: Optional[str] = Query(None, description="Filter by database directory"),
):
    """List snapshots, optionally filtered by directory."""
    if MOCK_MODE:
        snaps = _MOCK_SNAPSHOTS["snapshots"]
        if db_dir:
            snaps = [s for s in snaps if s["db_dir"] == db_dir]
        return {"snapshots": snaps}
    path = "/api/snapshots" + (f"?db_dir={db_dir}" if db_dir else "")
    return await _proxy_get(path)


@router.post("/snapshots")
async def filedb_create_snapshot(body: dict):
    """Create a snapshot for a database directory."""
    db_dir = body.get("db_dir")
    if not db_dir:
        raise HTTPException(status_code=400, detail="db_dir required")

    if MOCK_MODE:
        return {
            "ok": True,
            "snapshot": {
                "ts": datetime.now().strftime("%Y%m%dT%H%M%S"),
                "db_dir": db_dir,
                "method": "mock",
                "reason": "user_request",
            },
        }
    return await _proxy_post("/api/snapshots", {
        "db_dir": db_dir,
        "reason": body.get("reason", "manual"),
    })


@router.post("/restore")
async def filedb_restore(body: dict):
    """Restore a snapshot (in-place or to new location)."""
    snap_ts = body.get("snap_ts")
    db_dir = body.get("db_dir")
    if not snap_ts or not db_dir:
        raise HTTPException(status_code=400, detail="snap_ts and db_dir required")

    if MOCK_MODE:
        target_dir = body.get("target_dir")
        if target_dir:
            return {"ok": True, "restored_to": target_dir}
        return {"ok": True, "restored_in_place": db_dir}
    return await _proxy_post("/api/snapshots/restore", body)


@router.get("/settings")
async def filedb_get_settings():
    """Get daemon settings."""
    if MOCK_MODE:
        return _MOCK_SETTINGS
    return await _proxy_get("/api/settings")


_ALLOWED_SETTINGS = {
    "snapshot_debounce_sec", "max_snapshots",
    "write_threshold", "watch_root",
}


@router.put("/settings")
async def filedb_update_settings(body: dict):
    """Update daemon settings (whitelist-only keys)."""
    safe = {k: v for k, v in body.items() if k in _ALLOWED_SETTINGS}
    if not safe:
        raise HTTPException(status_code=400, detail="No valid settings keys")

    if MOCK_MODE:
        return {"ok": True, "settings": safe, "mock_mode": True}
    return await _proxy_post("/api/settings", body)


@router.get("/log")
async def filedb_log(
    lines: int = Query(100, description="Number of lines"),
):
    """Get daemon log (last N lines)."""
    if MOCK_MODE:
        return {"lines": _MOCK_LOG["lines"][:lines]}
    return await _proxy_get(f"/api/log?lines={lines}")


# ── WebSocket ───────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_filedb(ws: WebSocket):
    """Real-time ForgeFileDB events via WebSocket.

    In mock mode: sends periodic heartbeats.
    In production: forwards daemon WebSocket events.
    """
    if not verify_ws_token(ws):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    if MOCK_MODE:
        try:
            while True:
                await asyncio.sleep(30)
                await ws.send_json({
                    "type": "heartbeat",
                    "ts": datetime.now().isoformat(),
                })
        except Exception:
            pass
        finally:
            await ws.close()
        return

    # Production: proxy WebSocket from daemon
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET", f"{DAEMON_BASE}/ws",
                timeout=None,
            ) as resp:
                async for line in resp.aiter_lines():
                    try:
                        data = json.loads(line)
                        await ws.send_json(data)
                    except json.JSONDecodeError:
                        await ws.send_text(line)
    except Exception:
        pass
    finally:
        await ws.close()
