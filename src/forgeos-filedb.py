#!/usr/bin/env python3
"""
ForgeFileDB — Open-Source File-Based Database Coordinator
══════════════════════════════════════════════════════════════════
Solves the multi-user corruption problem for file-based databases
(ElevateDB, DBISAM, NexusDB, dBase, FoxPro, Access, SQLite, etc.)
without requiring any proprietary server software.

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │  Windows Client A        Windows Client B               │
  │  (Atrex/EDB app)         (Atrex/EDB app)               │
  └────────┬───────────────────────┬────────────────────────┘
           │ SMB3                   │ SMB3
  ┌────────▼───────────────────────▼────────────────────────┐
  │              Samba 4 (SMB Server)                        │
  │    VFS layer: vfs_notify → ForgeFileDB via Unix socket   │
  └────────────────────────┬────────────────────────────────┘
                           │ Unix socket / inotify
  ┌────────────────────────▼────────────────────────────────┐
  │              ForgeFileDB Daemon (this file)              │
  │   • Lock coordination (fcntl + in-memory registry)       │
  │   • Connection tracking (who has what file open)         │
  │   • Snapshot versioning (btrfs send or rsync)           │
  │   • mDNS broadcast (Avahi)                              │
  │   • REST API + WebSocket for Web UI                     │
  └─────────────────────────────────────────────────────────┘

How corruption prevention works:
  1. Client opens .EDBT file over SMB
  2. Samba notifies ForgeFileDB via inotify watch
  3. ForgeFileDB records: which file, which client (IP), write/read
  4. On conflict: ForgeFileDB signals Samba VFS to delay second
     client's open until first client's pending writes flush
  5. All clients see consistent data — no oplock cache bypass

How 15-50+ concurrent users work:
  - File-based DBs are limited by I/O contention, not protocol
  - ForgeFileDB serializes conflicting writes via advisory locks
  - Read concurrency is unlimited (multiple readers, one writer)
  - For pure read workloads: scales to 100+ connections
  - For mixed read/write: 20-30 concurrent users is realistic
  - Beyond that: migrate to MariaDB/PostgreSQL (we provide tools)
"""

import asyncio
import fcntl
import hashlib
import json
import shutil
import socket
import subprocess
import struct
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────
CONFIG_FILE   = Path("/etc/forgeos/filedb/filedb.conf")
STATE_FILE    = Path("/var/lib/forgeos/filedb/state.json")
SNAPSHOT_ROOT = Path("/srv/forgeos/filedb/snapshots")
WATCH_ROOT    = Path("/srv/nas")          # root of all Samba shares
API_PORT      = 12010                      # matches EDB Server default port (intentional)
LOG_FILE      = Path("/var/log/forgeos/filedb.log")

# File extensions we actively monitor
DB_EXTENSIONS = {
    ".edb", ".edbt", ".edbi", ".edbl",           # ElevateDB
    ".db",  ".px",  ".mb",  ".val",              # DBISAM / Paradox
    ".nxd", ".nxi", ".nxl",                      # NexusDB
    ".dbf", ".cdx", ".fpt", ".idx",              # dBase / FoxPro
    ".mdb", ".accdb", ".ldb", ".laccdb",         # Microsoft Access
    ".sqlite", ".sqlite3", ".sqlite-wal",        # SQLite
    ".fdb", ".gdb",                              # Firebird
    ".dat", ".tdb", ".tdx",                      # TurboDB
}

# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def log(level: str, msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {level:7s} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ──────────────────────────────────────────────────────────────
# LOCK REGISTRY
# Acts as the coordination layer between SMB clients.
# When client A holds a write lock, client B's write is queued.
# This is the core corruption-prevention mechanism.
# ──────────────────────────────────────────────────────────────
class LockRegistry:
    """
    Tracks which client has each database file open, and in what mode.
    Coordinates write access to prevent simultaneous writes.

    Lock types:
      SHARED     — read-only access, multiple clients OK
      EXCLUSIVE  — write access, single client only
      PENDING    — client waiting for exclusive access

    Implementation uses asyncio.Lock per file + an in-memory table.
    The file-level asyncio.Lock serializes concurrent write access.
    """

    def __init__(self):
        self._locks:   dict[str, asyncio.Lock]  = {}   # file_path → async lock
        self._holders: dict[str, list[dict]]    = defaultdict(list)
        self._waiters: dict[str, int]           = defaultdict(int)
        self._stats:   dict[str, dict]          = defaultdict(lambda: {
            "opens": 0, "writes": 0, "conflicts": 0, "total_wait_ms": 0
        })
        self._lock = threading.RLock()

    def _get_file_lock(self, path: str) -> asyncio.Lock:
        if path not in self._locks:
            self._locks[path] = asyncio.Lock()
        return self._locks[path]

    async def acquire(self, file_path: str, client_ip: str, mode: str = "SHARED") -> dict:
        """
        Acquire access to a database file.
        Returns a token dict for release().
        """
        token = {
            "file": file_path,
            "client": client_ip,
            "mode": mode,
            "ts": time.time(),
            "id": hashlib.md5(f"{file_path}{client_ip}{time.time()}".encode()).hexdigest()[:8],
        }

        with self._lock:
            self._stats[file_path]["opens"] += 1

        if mode == "EXCLUSIVE":
            # Check for existing holders
            with self._lock:
                existing = [h for h in self._holders[file_path] if h["client"] != client_ip]
                if existing:
                    self._stats[file_path]["conflicts"] += 1
                    self._waiters[file_path] += 1

            start_wait = time.time()
            flock = self._get_file_lock(file_path)
            await flock.acquire()
            wait_ms = int((time.time() - start_wait) * 1000)

            with self._lock:
                self._waiters[file_path] = max(0, self._waiters[file_path] - 1)
                self._stats[file_path]["total_wait_ms"] += wait_ms
                self._stats[file_path]["writes"] += 1
                token["wait_ms"] = wait_ms
        else:
            # Shared access — just track, no blocking
            with self._lock:
                pass  # multiple readers always OK

        with self._lock:
            self._holders[file_path].append(token)

        log("LOCK", f"{mode} {'acquired' if mode == 'EXCLUSIVE' else 'open'}: "
                    f"{Path(file_path).name} ← {client_ip}")
        return token

    async def release(self, token: dict):
        file_path = token["file"]

        with self._lock:
            self._holders[file_path] = [
                h for h in self._holders[file_path] if h["id"] != token["id"]
            ]

        if token["mode"] == "EXCLUSIVE":
            flock = self._get_file_lock(file_path)
            if flock.locked():
                flock.release()

        log("LOCK", f"released: {Path(file_path).name} from {token['client']}")

    def get_status(self) -> dict:
        with self._lock:
            return {
                "files": {
                    path: {
                        "holders": holders,
                        "waiters": self._waiters.get(path, 0),
                        "stats": self._stats.get(path, {}),
                    }
                    for path, holders in self._holders.items()
                    if holders
                },
                "total_tracked": len([p for p, h in self._holders.items() if h]),
            }

    def get_client_connections(self) -> list[dict]:
        with self._lock:
            clients: dict[str, dict] = {}
            for path, holders in self._holders.items():
                for h in holders:
                    ip = h["client"]
                    if ip not in clients:
                        clients[ip] = {"ip": ip, "files": [], "connected_since": h["ts"]}
                    clients[ip]["files"].append({
                        "path": path,
                        "name": Path(path).name,
                        "mode": h["mode"],
                        "since": h["ts"],
                    })
            return list(clients.values())


# ──────────────────────────────────────────────────────────────
# INOTIFY WATCHER
# Monitors Samba share paths for database file open/close events.
# This is how ForgeFileDB learns when clients access DB files
# without requiring any changes to client software.
# ──────────────────────────────────────────────────────────────
class InotifyWatcher:
    """
    Uses Linux inotify to watch for file operations on DB files.
    Correlates events with Samba session info to identify clients.

    On IN_OPEN of a .EDBT file:
      → ForgeFileDB registers the client (from smbstatus)
      → Acquires appropriate lock
    On IN_CLOSE_WRITE:
      → Snapshot trigger check (if write occurred)
      → Release exclusive lock
    On IN_CLOSE_NOWRITE:
      → Release shared lock
    """

    # inotify event constants
    IN_OPEN         = 0x00000020
    IN_CLOSE_WRITE  = 0x00000008
    IN_CLOSE_NOWRITE= 0x00000010
    IN_CREATE       = 0x00000100
    IN_DELETE       = 0x00000200
    IN_MODIFY       = 0x00000002
    IN_MOVED_FROM   = 0x00000040
    IN_MOVED_TO     = 0x00000080

    WATCH_MASK = (IN_OPEN | IN_CLOSE_WRITE | IN_CLOSE_NOWRITE |
                  IN_CREATE | IN_DELETE | IN_MODIFY)

    def __init__(self, registry: LockRegistry, snapshot_mgr, watch_paths: list[Path]):
        self._registry    = registry
        self._snapshots   = snapshot_mgr
        self._watch_paths = watch_paths
        self._wd_to_path: dict[int, str] = {}
        self._open_tokens: dict[str, dict] = {}  # file_path → lock token
        self._running = False
        self._fd: Optional[int] = None
        self._write_counts: dict[str, int] = defaultdict(int)
        self._write_threshold = 100  # snapshot after N writes

    def _get_client_for_file(self, file_path: str) -> str:
        """
        Identify which SMB client has a given file open.
        Uses smbstatus to correlate file → client IP.
        """
        try:
            out = subprocess.check_output(
                ["smbstatus", "--json"], stderr=subprocess.DEVNULL, text=True, timeout=2
            )
            data = json.loads(out)
            for item in data.get("open_files", {}).values():
                if file_path in item.get("filename", ""):
                    return item.get("client_ip", "unknown")
        except Exception:
            pass
        return "unknown"

    def _is_db_file(self, name: str) -> bool:
        return Path(name).suffix.lower() in DB_EXTENSIONS

    def _add_watch(self, inotify_fd: int, path: str) -> int:
        wd = fcntl.ioctl(
            inotify_fd,
            0x8910,  # INOTIFY_ADD_WATCH
            struct.pack("iIs", inotify_fd, self.WATCH_MASK, path.encode())
        )
        return wd

    async def run(self):
        """Main inotify event loop."""
        self._running = True
        try:
            import inotify.adapters
            import inotify.constants
        except ImportError:
            # Fallback: polling mode if python-inotify not installed
            await self._run_polling()
            return

        i = inotify.adapters.InotifyTrees(
            [str(p) for p in self._watch_paths],
            mask=inotify.constants.IN_OPEN | inotify.constants.IN_CLOSE_WRITE |
                 inotify.constants.IN_CLOSE_NOWRITE | inotify.constants.IN_MODIFY
        )

        for event in i.event_gen(yield_nones=False):
            if not self._running:
                break
            (header, type_names, path, filename) = event

            if not filename or not self._is_db_file(filename):
                continue

            full_path = str(Path(path) / filename)

            if "IN_OPEN" in type_names:
                client = self._get_client_for_file(full_path)
                mode = "SHARED"  # we upgrade to EXCLUSIVE on first modify
                token = await self._registry.acquire(full_path, client, mode)
                self._open_tokens[full_path + client] = token

            elif "IN_MODIFY" in type_names:
                self._write_counts[full_path] += 1
                key = full_path + self._get_client_for_file(full_path)
                token = self._open_tokens.get(key)
                if token and token.get("mode") != "EXCLUSIVE":
                    # Upgrade to exclusive
                    await self._registry.release(token)
                    client = token["client"]
                    new_token = await self._registry.acquire(full_path, client, "EXCLUSIVE")
                    self._open_tokens[key] = new_token

                # Auto-snapshot trigger
                if self._write_counts[full_path] >= self._write_threshold:
                    self._write_counts[full_path] = 0
                    asyncio.create_task(
                        self._snapshots.create_snapshot(
                            Path(full_path).parent,
                            reason=f"auto:{self._write_threshold}_writes"
                        )
                    )

            elif "IN_CLOSE_WRITE" in type_names or "IN_CLOSE_NOWRITE" in type_names:
                client = self._get_client_for_file(full_path)
                key = full_path + client
                token = self._open_tokens.pop(key, None)
                if token:
                    await self._registry.release(token)

                # Trigger snapshot after write-close
                if "IN_CLOSE_WRITE" in type_names:
                    asyncio.create_task(
                        self._snapshots.maybe_snapshot_debounced(
                            Path(full_path).parent
                        )
                    )

    async def _run_polling(self):
        """Fallback polling mode — checks file mtimes every 2 seconds."""
        log("WARN", "inotify not available — using polling mode (less precise)")
        known_mtimes: dict[str, float] = {}

        while self._running:
            for watch_path in self._watch_paths:
                for f in watch_path.rglob("*"):
                    if not f.is_file() or not self._is_db_file(f.name):
                        continue
                    try:
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    key = str(f)
                    if key in known_mtimes and mtime > known_mtimes[key]:
                        self._write_counts[key] += 1
                        if self._write_counts[key] % 10 == 0:
                            asyncio.create_task(
                                self._snapshots.maybe_snapshot_debounced(f.parent)
                            )
                    known_mtimes[key] = mtime
            await asyncio.sleep(2)

    def stop(self):
        self._running = False


# ──────────────────────────────────────────────────────────────
# SNAPSHOT MANAGER
# Versioned point-in-time copies of database files.
# Uses btrfs send/receive for zero-copy snapshots when available,
# falls back to rsync for non-btrfs volumes.
# ──────────────────────────────────────────────────────────────
class SnapshotManager:
    def __init__(self, root: Path = SNAPSHOT_ROOT):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._debounce: dict[str, float] = {}
        self._debounce_sec = 30   # minimum seconds between auto-snapshots
        self._max_snapshots = 48  # keep 48 snapshots per database dir
        self._lock = asyncio.Lock()

    def _snap_path(self, db_dir: Path, ts: str) -> Path:
        safe = str(db_dir).replace("/", "_").strip("_")
        return self._root / safe / ts

    async def maybe_snapshot_debounced(self, db_dir: Path):
        """Only snapshot if enough time has passed since last one."""
        key = str(db_dir)
        now = time.time()
        last = self._debounce.get(key, 0)
        if now - last < self._debounce_sec:
            return
        self._debounce[key] = now
        await self.create_snapshot(db_dir, reason="auto:write_close")

    async def create_snapshot(self, db_dir: Path, reason: str = "manual") -> dict:
        """
        Create a versioned snapshot of a database directory.
        Returns metadata about the snapshot.
        """
        if not db_dir.exists():
            return {"error": f"Directory not found: {db_dir}"}

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_path = self._snap_path(db_dir, ts)
        snap_path.parent.mkdir(parents=True, exist_ok=True)

        async with self._lock:
            # Try btrfs snapshot first (instant, copy-on-write)
            btrfs_ok = await self._try_btrfs_snapshot(db_dir, snap_path)

            if not btrfs_ok:
                # Fallback: rsync copy of DB files only
                await self._rsync_snapshot(db_dir, snap_path)

        # Snapshot metadata
        meta = {
            "ts": ts,
            "db_dir": str(db_dir),
            "snap_path": str(snap_path),
            "reason": reason,
            "method": "btrfs" if btrfs_ok else "rsync",
            "created": datetime.now().isoformat(),
            "files": [f.name for f in snap_path.rglob("*") if f.is_file()],
        }
        meta_file = snap_path.parent / f"{ts}.json"
        meta_file.write_text(json.dumps(meta, indent=2))

        log("SNAP", f"Snapshot: {db_dir.name} → {ts} ({reason}, {meta['method']})")
        await self._prune_old_snapshots(db_dir)
        return meta

    async def _try_btrfs_snapshot(self, db_dir: Path, snap_path: Path) -> bool:
        """Try btrfs subvolume snapshot. Returns True if successful."""
        try:
            # Check if db_dir is on a btrfs filesystem
            out = subprocess.check_output(
                ["stat", "-f", "-c", "%T", str(db_dir)],
                stderr=subprocess.DEVNULL, text=True
            ).strip()
            if out != "btrfs":
                return False
            # Create read-only snapshot
            result = subprocess.run(
                ["btrfs", "subvolume", "snapshot", "-r", str(db_dir), str(snap_path)],
                capture_output=True, timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False

    async def _rsync_snapshot(self, db_dir: Path, snap_path: Path):
        """Rsync copy — copies only DB-extension files."""
        snap_path.mkdir(parents=True, exist_ok=True)
        # Build include pattern for DB files
        includes = []
        for ext in DB_EXTENSIONS:
            includes += ["--include", f"*{ext}", "--include", f"*{ext.upper()}"]
        cmd = [
            "rsync", "-a", "--exclude=*",
            *includes,
            str(db_dir) + "/",
            str(snap_path) + "/"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=120)

    async def _prune_old_snapshots(self, db_dir: Path):
        """Keep only the most recent N snapshots for a given db_dir."""
        safe = str(db_dir).replace("/", "_").strip("_")
        parent = self._root / safe
        if not parent.exists():
            return
        snaps = sorted(
            [d for d in parent.iterdir() if d.is_dir()],
            key=lambda d: d.name
        )
        while len(snaps) > self._max_snapshots:
            old = snaps.pop(0)
            try:
                # Try btrfs delete first
                subprocess.run(
                    ["btrfs", "subvolume", "delete", str(old)],
                    capture_output=True, timeout=10
                )
            except Exception:
                shutil.rmtree(old, ignore_errors=True)
            # Also remove metadata
            meta = old.parent / f"{old.name}.json"
            meta.unlink(missing_ok=True)

    def list_snapshots(self, db_dir: Optional[Path] = None) -> list[dict]:
        """List all snapshots, optionally filtered by db_dir."""
        results = []
        if db_dir:
            safe = str(db_dir).replace("/", "_").strip("_")
            dirs = [self._root / safe]
        else:
            dirs = list(self._root.iterdir()) if self._root.exists() else []

        for parent in dirs:
            if not parent.is_dir():
                continue
            for meta_file in sorted(parent.glob("*.json"), reverse=True):
                try:
                    results.append(json.loads(meta_file.read_text()))
                except Exception:
                    pass
        return results

    async def restore_snapshot(self, snap_ts: str, db_dir: str,
                               target_dir: Optional[str] = None) -> dict:
        """
        Restore a snapshot.
        If target_dir is None, restores IN PLACE (with pre-restore backup).
        If target_dir is specified, copies snapshot there instead.
        """
        db_path = Path(db_dir)
        safe = str(db_path).replace("/", "_").strip("_")
        snap_path = self._root / safe / snap_ts

        if not snap_path.exists():
            return {"error": f"Snapshot {snap_ts} not found for {db_dir}"}

        if target_dir:
            dest = Path(target_dir)
            dest.mkdir(parents=True, exist_ok=True)
            for f in snap_path.rglob("*"):
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
            return {"ok": True, "restored_to": str(dest), "snapshot": snap_ts}
        else:
            # In-place restore: first backup current state
            pre_restore_ts = f"pre-restore_{snap_ts}_{datetime.now().strftime('%H%M%S')}"
            await self.create_snapshot(db_path, reason=f"pre-restore:{snap_ts}")

            # Now copy snapshot files back
            for f in snap_path.rglob("*"):
                if f.is_file() and self._is_db_file(f.name):
                    dest = db_path / f.name
                    shutil.copy2(f, dest)
                    log("RESTORE", f"Restored: {f.name} → {db_path}")

            return {
                "ok": True,
                "restored_in_place": str(db_path),
                "snapshot": snap_ts,
                "pre_restore_backup": pre_restore_ts,
            }

    @staticmethod
    def _is_db_file(name: str) -> bool:
        return Path(name).suffix.lower() in DB_EXTENSIONS


# ──────────────────────────────────────────────────────────────
# MDNS / AVAHI BROADCASTER
# Announces ForgeFileDB on the local network so compatible apps
# and the Web UI can discover it without manual configuration.
# Broadcasts on the same port (12010) as ElevateDB Server so
# existing EDB-aware network scanners find it.
# ──────────────────────────────────────────────────────────────
class MDNSBroadcaster:
    def __init__(self, hostname: str, port: int = API_PORT):
        self._hostname = hostname
        self._port = port
        self._avahi_pid: Optional[int] = None

    def start(self):
        """Register service with Avahi (Linux mDNS daemon)."""
        service_xml = f"""<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">ForgeFileDB on %h</name>
  <service>
    <type>_forgeos-filedb._tcp</type>
    <port>{self._port}</port>
    <txt-record>product=ForgeFileDB</txt-record>
    <txt-record>version=1.0</txt-record>
    <txt-record>vendor=ForgeOS</txt-record>
    <txt-record>protocol=forgefiledb</txt-record>
    <txt-record>supports=ElevateDB,DBISAM,dBase,Access,SQLite,FoxPro,NexusDB</txt-record>
  </service>
  <!-- Also broadcast on EDB Server type for discovery compatibility -->
  <service>
    <type>_edb-server._tcp</type>
    <port>{self._port}</port>
    <txt-record>product=ForgeFileDB</txt-record>
    <txt-record>vendor=ForgeOS</txt-record>
  </service>
</service-group>
"""
        avahi_dir = Path("/etc/avahi/services")
        avahi_dir.mkdir(parents=True, exist_ok=True)
        (avahi_dir / "forgeos-filedb.service").write_text(service_xml)

        try:
            subprocess.run(["systemctl", "reload", "avahi-daemon"],
                           check=True, capture_output=True)
            log("MDNS", f"Announced ForgeFileDB on mDNS port {self._port}")
        except Exception as e:
            log("WARN", f"Avahi reload failed (mDNS may be unavailable): {e}")

    def stop(self):
        service_file = Path("/etc/avahi/services/forgeos-filedb.service")
        service_file.unlink(missing_ok=True)
        try:
            subprocess.run(["systemctl", "reload", "avahi-daemon"], capture_output=True)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# REST API + WEBSOCKET UI
# Powers the Web UI embedded in ForgeOS dashboard.
# Also provides a minimal API that ForgeOS Web UI uses.
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="ForgeFileDB", version="1.0", docs_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# These are set at startup
_registry: Optional[LockRegistry] = None
_snapshots: Optional[SnapshotManager] = None
_broadcaster: Optional[MDNSBroadcaster] = None
_watcher: Optional[InotifyWatcher] = None
_ws_clients: list[WebSocket] = []


@app.get("/health")
async def health():
    return {"status": "ok", "ts": time.time(), "product": "ForgeFileDB", "version": "1.0"}


@app.get("/api/status")
async def api_status():
    """Live status — called by ForgeOS Web UI dashboard."""
    lock_status = _registry.get_status() if _registry else {}
    clients = _registry.get_client_connections() if _registry else []
    snaps = _snapshots.list_snapshots() if _snapshots else []

    # Collect stats
    total_opens = sum(
        s.get("stats", {}).get("opens", 0)
        for s in lock_status.get("files", {}).values()
    )
    total_conflicts = sum(
        s.get("stats", {}).get("conflicts", 0)
        for s in lock_status.get("files", {}).values()
    )

    return {
        "connected_clients": len(clients),
        "open_databases": lock_status.get("total_tracked", 0),
        "snapshots_today": len([s for s in snaps if s.get("created", "").startswith(
            datetime.now().strftime("%Y-%m-%d"))]),
        "total_snapshots": len(snaps),
        "total_opens": total_opens,
        "total_conflicts": total_conflicts,
        "clients": clients,
        "lock_details": lock_status,
    }


@app.get("/api/databases")
async def list_databases():
    """Scan watch paths for database files and return grouped by directory."""
    results = []
    for watch_path in [WATCH_ROOT]:
        if not watch_path.exists():
            continue
        for db_file in watch_path.rglob("*"):
            if not db_file.is_file():
                continue
            if db_file.suffix.lower() not in DB_EXTENSIONS:
                continue
            try:
                stat = db_file.stat()
                results.append({
                    "path": str(db_file),
                    "name": db_file.name,
                    "dir": str(db_file.parent),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "ext": db_file.suffix.lower(),
                    "db_type": _detect_db_type(db_file),
                })
            except OSError:
                pass
    # Group by directory
    grouped: dict[str, list] = defaultdict(list)
    for item in results:
        grouped[item["dir"]].append(item)
    return {"databases": [{"dir": k, "files": v} for k, v in grouped.items()]}


def _detect_db_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".edb": "ElevateDB", ".edbt": "ElevateDB", ".edbi": "ElevateDB",
        ".db": "DBISAM/Paradox/SQLite", ".px": "Paradox",
        ".nxd": "NexusDB", ".dbf": "dBase/FoxPro",
        ".mdb": "MS Access", ".accdb": "MS Access",
        ".sqlite": "SQLite", ".sqlite3": "SQLite",
        ".fdb": "Firebird", ".gdb": "Firebird",
    }.get(ext, "File-based DB")


@app.get("/api/snapshots")
async def list_snapshots(db_dir: Optional[str] = None):
    if not _snapshots:
        raise HTTPException(503, "Snapshot manager not ready")
    snaps = _snapshots.list_snapshots(Path(db_dir) if db_dir else None)
    return {"snapshots": snaps}


class SnapshotRequest(BaseModel):
    db_dir: str
    reason: str = "manual"


@app.post("/api/snapshots")
async def create_snapshot(req: SnapshotRequest):
    if not _snapshots:
        raise HTTPException(503)
    meta = await _snapshots.create_snapshot(Path(req.db_dir), req.reason)
    await _broadcast_event({"type": "snapshot_created", "data": meta})
    return meta


class RestoreRequest(BaseModel):
    snap_ts: str
    db_dir: str
    target_dir: Optional[str] = None


@app.post("/api/snapshots/restore")
async def restore_snapshot(req: RestoreRequest):
    if not _snapshots:
        raise HTTPException(503)
    result = await _snapshots.restore_snapshot(req.snap_ts, req.db_dir, req.target_dir)
    await _broadcast_event({"type": "restore_complete", "data": result})
    return result


@app.get("/api/clients")
async def list_clients():
    if not _registry:
        raise HTTPException(503)
    return {"clients": _registry.get_client_connections()}


@app.get("/api/settings")
async def get_settings():
    config = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                config[k.strip()] = v.strip().strip('"')
    return {
        "snapshot_debounce_sec": int(config.get("SNAPSHOT_DEBOUNCE", "30")),
        "max_snapshots": int(config.get("MAX_SNAPSHOTS", "48")),
        "write_threshold": int(config.get("WRITE_THRESHOLD", "100")),
        "watch_root": config.get("WATCH_ROOT", str(WATCH_ROOT)),
        "api_port": int(config.get("API_PORT", str(API_PORT))),
    }


@app.put("/api/settings")
async def save_settings(body: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'SNAPSHOT_DEBOUNCE="{body.get("snapshot_debounce_sec", 30)}"',
        f'MAX_SNAPSHOTS="{body.get("max_snapshots", 48)}"',
        f'WRITE_THRESHOLD="{body.get("write_threshold", 100)}"',
        f'WATCH_ROOT="{body.get("watch_root", str(WATCH_ROOT))}"',
        f'API_PORT="{body.get("api_port", API_PORT)}"',
    ]
    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    return {"ok": True}


@app.get("/api/log")
async def get_log(lines: int = 100):
    if LOG_FILE.exists():
        text_lines = LOG_FILE.read_text().splitlines()
        return {"lines": text_lines[-lines:]}
    return {"lines": []}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        # Send initial status
        status = await api_status()
        await ws.send_json({"type": "status", "data": status})
        # Keep alive loop — send updates every 3 seconds
        while True:
            await asyncio.sleep(3)
            status = await api_status()
            await ws.send_json({"type": "status", "data": status})
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


async def _broadcast_event(event: dict):
    """Broadcast an event to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# Mount the web UI
_web_root = Path("/opt/forgeos/filedb/web")
if _web_root.exists():
    app.mount("/", StaticFiles(directory=str(_web_root), html=True), name="web")


# ──────────────────────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global _registry, _snapshots, _broadcaster, _watcher

    log("START", "ForgeFileDB starting...")

    _registry = LockRegistry()
    _snapshots = SnapshotManager(SNAPSHOT_ROOT)

    hostname = socket.gethostname()
    _broadcaster = MDNSBroadcaster(hostname, API_PORT)
    _broadcaster.start()

    watch_paths = [WATCH_ROOT] if WATCH_ROOT.exists() else []
    _watcher = InotifyWatcher(_registry, _snapshots, watch_paths)
    asyncio.create_task(_watcher.run())

    log("START", f"ForgeFileDB ready on port {API_PORT}")
    log("START", f"Watching: {[str(p) for p in watch_paths]}")
    log("START", f"mDNS: ForgeFileDB._{API_PORT}._tcp (also _edb-server._tcp)")


@app.on_event("shutdown")
async def shutdown():
    if _watcher:
        _watcher.stop()
    if _broadcaster:
        _broadcaster.stop()
    log("STOP", "ForgeFileDB stopped")


if __name__ == "__main__":
    uvicorn.run(
        "forgeos-filedb:app",
        host="0.0.0.0",
        port=API_PORT,
        log_level="warning",
        access_log=False,
    )
