"""
ForgeFileDB API Module
═══════════════════════════════════════════════════════════════
Provides REST API endpoints for ForgeFileDB management.

Endpoints:
  GET  /api/filedb/status     - Daemon status
  GET  /api/filedb/clients    - Connected SMB clients
  GET  /api/filedb/databases  - Discovered DB files
  GET  /api/filedb/locks      - Current file locks
  GET  /api/filedb/snapshots - List snapshots
  POST /api/filedb/snapshots  - Create snapshot
  POST /api/filedb/restore    - Restore snapshot
  GET  /api/filedb/settings   - Get settings
  PUT  /api/filedb/settings   - Update settings
  GET  /api/filedb/log        - Daemon log

WebSocket:
  /ws/filedb                   - Real-time updates

Mock Mode:
  Set MOCK_FILEDB=true environment variable to return sample data
  without requiring the actual ForgeFileDB daemon.
"""

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import JSONResponse

# ────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────
MOCK_MODE = os.environ.get('MOCK_FILEDB', 'false').lower() == 'true'
FILEDB_CONFIG = Path('/etc/forgeos/filedb.conf')
FILEDB_LOG = Path('/var/log/forgeos/filedb.log')

# ────────────────────────────────────────────────────────────
# ROUTER
# ────────────────────────────────────────────────────────────
router = APIRouter(prefix='/api/filedb', tags=['filedb'])


# ────────────────────────────────────────────────────────────
# MOCK DATA
# ────────────────────────────────────────────────────────────
def get_mock_status() -> dict:
    return {
        "daemon_running": True,
        "connected_clients": 3,
        "open_databases": 5,
        "snapshots_today": 12,
        "total_conflicts": 0,
        "uptime": "2h 34m",
        "version": "1.0.0",
        "mock_mode": True
    }


def get_mock_clients() -> List[dict]:
    return [
        {"ip": "192.168.1.10", "user": "alice", "files_open": 3, "connected_since": "2026-04-28T14:20:00"},
        {"ip": "192.168.1.15", "user": "bob", "files_open": 1, "connected_since": "2026-04-28T15:10:00"},
        {"ip": "192.168.1.20", "user": "charlie", "files_open": 2, "connected_since": "2026-04-28T13:45:00"},
    ]


def get_mock_databases() -> List[dict]:
    return [
        {
            "directory": "/data/databases/finance",
            "databases": [
                {"name": "ledger.db", "size": 1048576, "modified": "2026-04-28T14:30:00", "locks": 0},
                {"name": "payroll.db", "size": 2097152, "modified": "2026-04-28T13:15:00", "locks": 1},
            ]
        },
        {
            "directory": "/data/databases/inventory",
            "databases": [
                {"name": "stock.db", "size": 5242880, "modified": "2026-04-28T15:00:00", "locks": 0},
                {"name": "orders.db", "size": 3145728, "modified": "2026-04-28T14:45:00", "locks": 2},
            ]
        }
    ]


def get_mock_locks() -> List[dict]:
    return [
        {"file": "/data/databases/finance/payroll.db", "client_ip": "192.168.1.15", "user": "bob", "locked_since": "2026-04-28T15:05:00", "mode": "write"},
        {"file": "/data/databases/inventory/orders.db", "client_ip": "192.168.1.10", "user": "alice", "locked_since": "2026-04-28T14:50:00", "mode": "write"},
        {"file": "/data/databases/inventory/orders.db", "client_ip": "192.168.1.20", "user": "charlie", "locked_since": "2026-04-28T14:52:00", "mode": "read"},
    ]


def get_mock_snapshots() -> List[dict]:
    now = datetime.now().isoformat()
    return [
        {"ts": "20260428T153000", "db_dir": "/data/databases/finance", "method": "auto", "reason": "write_threshold", "size": 3145728},
        {"ts": "20260428T145000", "db_dir": "/data/databases/inventory", "method": "manual", "reason": "user_request", "size": 8388608},
        {"ts": "20260428T140000", "db_dir": "/data/databases/finance", "method": "auto", "reason": "write_threshold", "size": 3145728},
    ]


def get_mock_settings() -> dict:
    return {
        "snapshot_debounce_sec": 10,
        "max_snapshots": 24,
        "write_threshold": 100,
        "watch_root": "/data/databases",
        "mock_mode": True
    }


# ────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────
def _run_filedb_cli(args: list) -> dict:
    """Run ForgeFileDB CLI and return parsed JSON response."""
    if MOCK_MODE:
        raise RuntimeError("Mock mode enabled")

    try:
        result = subprocess.run(
            ['filedb-cli'] + args,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "CLI command failed")
        return json.loads(result.stdout) if result.stdout else {}
    except FileNotFoundError:
        raise RuntimeError("ForgeFileDB CLI not installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("CLI command timed out")
    except json.JSONDecodeError:
        raise RuntimeError("Invalid response from CLI")


# ────────────────────────────────────────────────────────────
# STATUS ENDPOINT
# ────────────────────────────────────────────────────────────
@router.get("/status")
async def filedb_status():
    """Get ForgeFileDB daemon status"""
    if MOCK_MODE:
        return get_mock_status()

    try:
        return _run_filedb_cli(['status'])
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": str(e), "daemon_running": False}
        )


# ────────────────────────────────────────────────────────────
# CLIENTS ENDPOINT
# ────────────────────────────────────────────────────────────
@router.get("/clients")
async def filedb_clients():
    """List connected SMB clients with open files"""
    if MOCK_MODE:
        return {"clients": get_mock_clients()}

    try:
        data = _run_filedb_cli(['clients', '--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ────────────────────────────────────────────────────────────
# DATABASES ENDPOINT
# ────────────────────────────────────────────────────────────
@router.get("/databases")
async def filedb_databases():
    """List discovered database files grouped by directory"""
    if MOCK_MODE:
        return {"databases": get_mock_databases()}

    try:
        data = _run_filedb_cli(['databases', '--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ────────────────────────────────────────────────────────────
# LOCKS ENDPOINT
# ────────────────────────────────────────────────────────────
@router.get("/locks")
async def filedb_locks():
    """Get current file lock registry"""
    if MOCK_MODE:
        return {"locks": get_mock_locks()}

    try:
        data = _run_filedb_cli(['locks', '--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ────────────────────────────────────────────────────────────
# SNAPSHOTS ENDPOINTS
# ────────────────────────────────────────────────────────────
@router.get("/snapshots")
async def filedb_snapshots(
    db_dir: Optional[str] = Query(None, description="Filter by database directory")
):
    """List snapshots, optionally filtered by directory"""
    if MOCK_MODE:
        snapshots = get_mock_snapshots()
        if db_dir:
            snapshots = [s for s in snapshots if s['db_dir'] == db_dir]
        return {"snapshots": snapshots}

    try:
        args = ['snapshots', '--json']
        if db_dir:
            args.extend(['--dir', db_dir])
        data = _run_filedb_cli(args)
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/snapshots")
async def filedb_create_snapshot(body: dict):
    """Create a snapshot for a database directory"""
    db_dir = body.get('db_dir')
    if not db_dir:
        raise HTTPException(status_code=400, detail="db_dir required")

    if MOCK_MODE:
        return {
            "ok": True,
            "snapshot": {
                "ts": datetime.now().strftime("%Y%m%dT%H%M%S"),
                "db_dir": db_dir,
                "method": "manual",
                "reason": "user_request"
            }
        }

    try:
        data = _run_filedb_cli(['snapshot', 'create', '--dir', db_dir, '--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore")
async def filedb_restore(body: dict):
    """Restore a snapshot (in-place or to new location)"""
    snap_ts = body.get('snap_ts')
    db_dir = body.get('db_dir')
    target_dir = body.get('target_dir')

    if not snap_ts or not db_dir:
        raise HTTPException(status_code=400, detail="snap_ts and db_dir required")

    if MOCK_MODE:
        if target_dir:
            return {"ok": True, "restored_to": target_dir}
        else:
            return {"ok": True, "restored_in_place": db_dir}

    try:
        args = ['snapshot', 'restore', '--ts', snap_ts, '--dir', db_dir]
        if target_dir:
            args.extend(['--target', target_dir])
        data = _run_filedb_cli(args + ['--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ────────────────────────────────────────────────────────────
# SETTINGS ENDPOINTS
# ────────────────────────────────────────────────────────────
@router.get("/settings")
async def filedb_get_settings():
    """Get ForgeFileDB settings"""
    if MOCK_MODE:
        return get_mock_settings()

    try:
        data = _run_filedb_cli(['settings', 'get', '--json'])
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


_ALLOWED_SETTINGS = {
    "snapshot_debounce_sec", "max_snapshots", "write_threshold", "watch_root",
}

@router.put("/settings")
async def filedb_update_settings(body: dict):
    """Update ForgeFileDB settings (whitelist-only keys)"""
    if MOCK_MODE:
        return {"ok": True, "settings": body, "mock_mode": True}

    # Whitelist: only accept known keys to prevent CLI injection
    safe = {k: v for k, v in body.items() if k in _ALLOWED_SETTINGS}
    if not safe:
        raise HTTPException(status_code=400, detail="No valid settings keys provided")

    try:
        # Build CLI args from whitelisted keys only
        args = ['settings', 'set']
        for key, value in safe.items():
            args.extend(['--' + key.replace('_', '-'), str(value)])
        args.append('--json')
        data = _run_filedb_cli(args)
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ────────────────────────────────────────────────────────────
# LOG ENDPOINT
# ────────────────────────────────────────────────────────────
@router.get("/log")
async def filedb_log(
    lines: int = Query(100, description="Number of lines to return")
):
    """Get ForgeFileDB daemon log (last N lines)"""
    if MOCK_MODE:
        mock_lines = [
            "[2026-04-28T15:30:00] START ForgeFileDB daemon v1.0.0 started",
            "[2026-04-28T15:30:01] SNAP Auto-snapshot created for /data/databases/finance",
            "[2026-04-28T15:25:00] LOCK File locked: /data/databases/inventory/orders.db by 192.168.1.10",
            "[2026-04-28T15:20:00] SNAP Auto-snapshot created for /data/databases/inventory",
            "[2026-04-28T15:15:00] WARN Write threshold exceeded for /data/databases/finance",
        ]
        return {"lines": mock_lines[:lines]}

    try:
        if not FILEDB_LOG.exists():
            return {"lines": []}

        result = subprocess.run(
            ['tail', '-n', str(lines), str(FILEDB_LOG)],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines_list = result.stdout.strip().split('\n') if result.stdout else []
        return {"lines": lines_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ────────────────────────────────────────────────────────────
# WEBSOCKET ENDPOINT
# ────────────────────────────────────────────────────────────
@router.websocket("/ws")
async def websocket_filedb(ws: WebSocket):
    """WebSocket for real-time ForgeFileDB updates"""
    await ws.accept()

    try:
        # Send initial status
        if MOCK_MODE:
            await ws.send_json({
                "type": "status",
                "data": get_mock_status()
            })
            # In mock mode, send periodic heartbeat updates
            while True:
                await asyncio.sleep(30)
                await ws.send_json({
                    "type": "heartbeat",
                    "ts": datetime.now().isoformat()
                })
        else:
            # In production, forward ForgeFileDB daemon events
            # Use subprocess to tail the daemon log for real-time updates
            proc = await asyncio.create_subprocess_exec(
                "tail", "-n", "0", "-F", str(FILEDB_LOG),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                while True:
                    if proc.stdout is None:
                        break
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                    if not line:
                        break
                    await ws.send_text(line.decode("utf-8", errors="replace").rstrip())
            finally:
                proc.kill()

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await ws.close()
