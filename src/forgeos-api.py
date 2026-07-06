#!/usr/bin/env python3
"""
ForgeOS Web UI Backend — FastAPI
════════════════════════════════════════════════════════════════
Powers the ForgeOS desktop web interface.
Runs as: forgeos-api (systemd service, port 5080)
Proxied by: nginx → https://forgeos.local

Architecture:
  HTTP REST API  — GUI calls for data, actions
  WebSocket /ws  — Live metrics stream (2s interval)
  WebSocket /ws/logs — Tail -f system logs live
  Webhook /api/alert-webhook — Alertmanager → Gotify/Apprise

Security:
  JWT auth (12h tokens), bcrypt passwords
  All endpoints require auth except /api/auth/login and /health
"""

from typing import List
import asyncio
import json
import sqlite3
import os
import re
import subprocess
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
import threading
import uuid
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger("forgeos-api")
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "forgeos: %(levelname)s %(message)s [%(funcName)s:%(lineno)d]"
))
logger.addHandler(_log_handler)
logger.setLevel(logging.INFO)

import uvicorn
from fastapi import (
    Depends, FastAPI, HTTPException,
    Request, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from forgeos_auth import (
    JWT_SECRET, JWT_ALGO, JWT_EXPIRE,
    pwd_ctx, LoginRequest,
    load_users, save_users, create_token, verify_token,
)

# Optional psutil — try once at module level instead of in every function
try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False

# ────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────
CONFIG_FILE = Path("/etc/forgeos/forgeos.conf")
USERS_FILE  = Path("/etc/forgeos/api-users.json")
# JWT config lives in forgeos_auth.py — JWT_SECRET, JWT_ALGO, JWT_EXPIRE, pwd_ctx
WEB_ROOT    = Path(os.environ.get("FORGEOS_WEB_ROOT", "/opt/forgeos/web"))

# Load config from forgeos.conf
_conf: dict[str, str] = {}
if CONFIG_FILE.exists():
    for line in CONFIG_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            _conf[k.strip()] = v.strip().strip('"')


def conf(key: str, default: str = "") -> str:
    return _conf.get(key, os.environ.get(f"FORGEOS_{key}", default))


# ────────────────────────────────────────────────────────────
# BACKGROUND TASK TRACKER
#   Long-running ops (borg create, restic snapshot, rclone
#   sync) run in a daemon thread. The endpoint returns a
#   task_id immediately; the frontend polls for completion.
# ────────────────────────────────────────────────────────────
_background_tasks: dict[str, dict] = {}
_task_lock = threading.Lock()
_TASK_TTL = 3600  # purge finished tasks after 1 hour
_MAX_TASKS = 100
_DATA_DIR = Path(os.environ.get("FORGEOS_DATA_DIR", "/var/lib/forgeos"))
_TASKS_FILE = _DATA_DIR / "background-tasks.json"

# ────────────────────────────────────────────────────────────
# BACKUP JOB SCHEDULER
#   Persist scheduled backup jobs to JSON. A background
#   asyncio task (started in lifespan) checks every 60s
#   whether any enabled jobs are due to run.
# ────────────────────────────────────────────────────────────
_backup_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOBS_FILE = _DATA_DIR / "backup-jobs.json"
_AUDIT_FILE = _DATA_DIR / "audit-log.json"     # used by _migrate_from_json()
_SCHEDULER_INTERVAL = 60  # check every 60 seconds

# ────────────────────────────────────────────────────────────
# SQLite PERSISTENCE LAYER
#   Single DB replacing 3 JSON files (tasks, backup jobs, audit).
#   In-memory dicts kept for hot task/job reads; audit queries
#   go directly to SQLite. JSON files are migrated on first run.
# ────────────────────────────────────────────────────────────
_DB: sqlite3.Connection | None = None


def _get_db() -> sqlite3.Connection:
    """Get the shared SQLite connection (WAL mode, init once)."""
    global _DB
    if _DB is None:
        db_path = _DATA_DIR / "forgeos.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _DB = sqlite3.connect(str(db_path), check_same_thread=False)
        _DB.execute("PRAGMA journal_mode=WAL")
        _DB.execute("PRAGMA foreign_keys=ON")
        _init_schema()
        _migrate_from_json()
    return _DB


def _init_schema() -> None:
    """Create tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        PRAGMA user_version = 1;
        CREATE TABLE IF NOT EXISTS tasks (
            id        TEXT PRIMARY KEY,
            tool      TEXT NOT NULL,
            action    TEXT NOT NULL,
            status    TEXT NOT NULL DEFAULT 'pending',
            started_at REAL NOT NULL,
            finished_at REAL,
            result    TEXT,
            error     TEXT,
            job_id    TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS backup_jobs (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            tool        TEXT NOT NULL,
            source      TEXT NOT NULL,
            destination TEXT NOT NULL,
            schedule    TEXT NOT NULL DEFAULT 'daily',
            enabled     INTEGER NOT NULL DEFAULT 1,
            last_run_ts REAL,
            last_status TEXT,
            last_error  TEXT,
            config      TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            who       TEXT NOT NULL,
            action    TEXT NOT NULL,
            status    TEXT NOT NULL,
            detail    TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
        CREATE INDEX IF NOT EXISTS idx_audit_who    ON audit_log(who);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    """)
    # Migrate v0→v1: add runs column for run history persistence
    try:
        conn.execute("ALTER TABLE backup_jobs ADD COLUMN runs TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()


def _migrate_from_json() -> None:
    """One-time migration from legacy JSON files to SQLite."""
    conn = _get_db()

    # Migrate tasks
    if _TASKS_FILE.exists():
        try:
            data = json.loads(_TASKS_FILE.read_text())
            for tid, t in data.items():
                conn.execute(
                    "INSERT OR IGNORE INTO tasks (id, tool, action, status, started_at, finished_at, result, error, job_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tid, t.get("tool", ""), t.get("action", ""), t.get("status", "pending"),
                     t.get("started_at", 0), t.get("finished_at"), t.get("result"),
                     t.get("error"), t.get("job_id"))
                )
            conn.commit()
            _TASKS_FILE.rename(_TASKS_FILE.with_suffix(".json.migrated"))
            logger.info("Migrated %d tasks from JSON to SQLite", len(data))
        except Exception as e:
            logger.warning("Failed to migrate tasks from JSON: %s", e)

    # Migrate backup jobs
    if _JOBS_FILE.exists():
        try:
            data = json.loads(_JOBS_FILE.read_text())
            for jid, j in data.items():
                conn.execute(
                    "INSERT OR IGNORE INTO backup_jobs (id, name, tool, source, destination, schedule, enabled, last_run_ts, last_status, last_error, config) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (jid, j.get("name", ""), j.get("tool", ""), json.dumps(j.get("source", [])),
                     j.get("destination", ""), j.get("schedule", "daily"),
                     1 if j.get("enabled", True) else 0,
                     j.get("last_run_ts"), j.get("last_status"), j.get("last_error"), j.get("config"))
                )
            conn.commit()
            _JOBS_FILE.rename(_JOBS_FILE.with_suffix(".json.migrated"))
            logger.info("Migrated %d backup jobs from JSON to SQLite", len(data))
        except Exception as e:
            logger.warning("Failed to migrate backup jobs from JSON: %s", e)

    # Migrate audit log
    if _AUDIT_FILE.exists():
        try:
            data = json.loads(_AUDIT_FILE.read_text())
            for entry in data:
                conn.execute(
                    "INSERT INTO audit_log (timestamp, who, action, status, detail) VALUES (?, ?, ?, ?, ?)",
                    (entry.get("timestamp", ""), entry.get("who", ""), entry.get("action", ""),
                     entry.get("status", ""), entry.get("detail", ""))
                )
            conn.commit()
            _AUDIT_FILE.rename(_AUDIT_FILE.with_suffix(".json.migrated"))
            logger.info("Migrated %d audit entries from JSON to SQLite", len(data))
        except Exception as e:
            logger.warning("Failed to migrate audit log from JSON: %s", e)


# ────────────────────────────────────────────────────────────
# AUDIT LOG — SQLite-backed, no in-memory list
# ────────────────────────────────────────────────────────────


def _audit(who: str, action: str, status: str, detail: str | None = None) -> None:
    """Record an auditable action directly in SQLite.

    Args:
        who:   Username (user["sub"] from the JWT).
        action: Machine-readable action name, e.g. "backup.job.create".
        status: "success" or "failure".
        detail: Human-readable description of what happened.
    """
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO audit_log (timestamp, who, action, status, detail) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), who, action, status, detail or "")
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to write audit entry: %s", e)


# Shutdown guard — prevents re-entry of the lifespan shutdown handler.
# Set to True when shutdown starts; any re-entry returns immediately.
_shutting_down = False
_shutdown_lock = threading.Lock()


def _persist_tasks() -> None:
    """Write in-memory task state to SQLite so it survives restart."""
    try:
        conn = _get_db()
        with _task_lock:
            for tid, t in _background_tasks.items():
                entry = dict(t)
                entry.pop("thread", None)
                conn.execute(
                    """INSERT INTO tasks (id, tool, action, status, started_at, finished_at, result, error, job_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           status=excluded.status,
                           finished_at=excluded.finished_at,
                           result=excluded.result,
                           error=excluded.error""",
                    (tid, entry.get("tool", ""), entry.get("action", ""),
                     entry.get("status", "pending"),
                     entry.get("started_at", 0), entry.get("finished_at"),
                     entry.get("result"), entry.get("error"), entry.get("job_id"))
                )
            conn.commit()
    except Exception as e:
        logger.warning("Failed to persist tasks to DB: %s", e)


def _load_tasks() -> None:
    """Load tasks from SQLite into memory.

    Any task that was 'pending' or 'running' when the server
    last shut down (or crashed) gets marked 'cancelled' —
    the daemon thread died with the process.
    """
    try:
        conn = _get_db()
        now = time.time()
        cur = conn.execute("SELECT * FROM tasks")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        with _task_lock:
            for row in rows:
                t = dict(zip(columns, row))
                tid = t.pop("id")
                t.pop("created_at", None)
                if t.get("status") in ("pending", "running"):
                    t["status"] = "cancelled"
                    t["error"] = "Server restarted while task was in flight"
                    t["finished_at"] = now
                    conn.execute("UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
                                 (t["status"], t["error"], t["finished_at"], tid))
                if tid not in _background_tasks:
                    _background_tasks[tid] = t
            conn.commit()
    except Exception as e:
        logger.warning("Failed to load tasks from DB: %s", e)


def _task_cleanup() -> None:
    """Remove stale tasks to prevent unbounded growth."""
    now = time.time()
    with _task_lock:
        stale = [
            tid for tid, t in _background_tasks.items()
            if t.get("finished_at") and (now - t["finished_at"]) > _TASK_TTL
        ]
        for tid in stale:
            del _background_tasks[tid]
        if len(_background_tasks) > _MAX_TASKS:
            sorted_tasks = sorted(
                _background_tasks.items(),
                key=lambda x: x[1].get("started_at", 0),
            )
            for tid, _ in sorted_tasks[:len(_background_tasks) - _MAX_TASKS]:
                del _background_tasks[tid]
    _persist_tasks()


def _run_background(cmd: list[str], task_id: str, timeout: int = 600,
                    job_id: str | None = None) -> None:
    """Run a command in a daemon thread, updating task and (optionally) job state."""
    with _task_lock:
        t = _background_tasks.get(task_id)
        if t:
            t["status"] = "running"
    final_status = "failed"
    final_error = None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                if r.returncode == 0:
                    t["status"] = "done"
                    t["result"] = r.stdout.strip()
                    final_status = "done"
                else:
                    t["status"] = "failed"
                    t["error"] = r.stderr.strip() or "Exit code %d" % r.returncode
                    final_error = t["error"]
                t["finished_at"] = time.time()
    except subprocess.TimeoutExpired:
        final_error = "Command timed out"
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = final_error
                t["finished_at"] = time.time()
    except Exception as e:
        final_error = str(e)
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = final_error
                t["finished_at"] = time.time()
    _persist_tasks()
    _update_job_from_task(task_id, final_status, final_error)


def _start_task(cmd: list[str], tool: str, action: str,
                timeout: int = 600, job_id: str | None = None) -> str:
    """Launch a command in background and return its task_id."""
    _task_cleanup()
    task_id = str(uuid.uuid4())
    now = time.time()
    with _task_lock:
        _background_tasks[task_id] = {
            "id": task_id,
            "tool": tool,
            "action": action,
            "status": "pending",
            "started_at": now,
            "finished_at": None,
            "result": None,
            "error": None,
            "job_id": job_id,
        }
    t = threading.Thread(
        target=_run_background, args=(cmd, task_id, timeout, job_id), daemon=True
    )
    with _task_lock:
        _background_tasks[task_id]["thread"] = t
    _persist_tasks()
    t.start()
    return task_id


# ── Backup job persistence ──────────────────────────────────

def _persist_jobs() -> None:
    """Write backup job configs to SQLite."""
    try:
        conn = _get_db()
        with _jobs_lock:
            for jid, j in _backup_jobs.items():
                runs = j.get("runs", [])
                conn.execute(
                    """INSERT INTO backup_jobs (id, name, tool, source, destination, schedule, enabled, last_run_ts, last_status, last_error, config, runs)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           name=excluded.name, tool=excluded.tool, source=excluded.source,
                           destination=excluded.destination, schedule=excluded.schedule,
                           enabled=excluded.enabled, last_run_ts=excluded.last_run_ts,
                           last_status=excluded.last_status, last_error=excluded.last_error,
                           config=excluded.config, runs=excluded.runs,
                           updated_at=datetime('now')""",
                    (jid, j.get("name", ""), j.get("tool", ""),
                     json.dumps(j.get("source", [])), j.get("destination", ""),
                     j.get("schedule", "daily"),
                     1 if j.get("enabled", True) else 0,
                     j.get("last_run_ts"), j.get("last_status"),
                     j.get("last_error"), j.get("config"),
                     json.dumps(runs[-_MAX_JOB_HISTORY:]))
                )
            conn.commit()
    except Exception as e:
        logger.warning("Failed to persist backup jobs to DB: %s", e)


def _load_jobs() -> None:
    """Load backup job configs from SQLite into memory."""
    try:
        conn = _get_db()
        cur = conn.execute("SELECT * FROM backup_jobs")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        with _jobs_lock:
            _backup_jobs.clear()
            for row in rows:
                j = dict(zip(columns, row))
                jid = j.pop("id")
                j.pop("created_at", None)
                j.pop("updated_at", None)
                # source stored as JSON string in DB — convert back to list
                if isinstance(j.get("source"), str):
                    try:
                        j["source"] = json.loads(j["source"])
                    except (json.JSONDecodeError, TypeError):
                        j["source"] = [j["source"]]
                # runs stored as JSON string in DB — convert back to list
                if isinstance(j.get("runs"), str):
                    try:
                        j["runs"] = json.loads(j["runs"])
                    except (json.JSONDecodeError, TypeError):
                        j["runs"] = []
                _backup_jobs[jid] = j
    except Exception as e:
        logger.warning("Failed to load backup jobs from DB: %s", e)


def _schedule_to_seconds(schedule: str) -> int:
    """Convert a schedule string to interval in seconds."""
    s = schedule.strip().lower()
    if s == "hourly":
        return 3600
    if s == "daily":
        return 86400
    if s == "weekly":
        return 604800
    if s == "monthly":
        return 2592000
    # Assume it's already a number of seconds
    try:
        return max(60, int(s))
    except (ValueError, TypeError):
        return 86400  # default to daily


async def _scheduler_loop() -> None:
    """Background loop: check every 60s for jobs that are due."""
    while not _shutting_down:
        try:
            now = time.time()
            with _jobs_lock:
                jobs = list(_backup_jobs.values())
            for job in jobs:
                if not job.get("enabled", True):
                    continue
                last = job.get("last_run_ts", 0)
                interval = _schedule_to_seconds(job.get("schedule", "daily"))
                if now - last >= interval:
                    _execute_backup_job(job["id"])
        except Exception as e:
            logger.warning("Scheduler check failed: %s", e)
        # Sleep in 1s increments so shutdown doesn't wait 60s
        for _ in range(_SCHEDULER_INTERVAL):
            if _shutting_down:
                return
            await asyncio.sleep(1)


def _execute_backup_job(job_id: str) -> None:
    """Dispatch a backup job using the appropriate tool."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        return

    tool = job.get("tool", "")
    source = job.get("source", [])
    dest = job.get("destination", "")

    if tool == "borg":
        archive_name = f"{job.get('name', 'backup')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        cmd = ["borg", "create", f"{dest}::{archive_name}"] + source
        task_id = _start_task(cmd, "borg", "scheduled", timeout=600, job_id=job_id)
    elif tool == "restic":
        cmd = ["restic", "-r", dest, "backup"] + source
        task_id = _start_task(cmd, "restic", "scheduled", timeout=600, job_id=job_id)
    elif tool == "rclone":
        cmd = ["rclone", "sync"] + source + [dest]
        task_id = _start_task(cmd, "rclone", "scheduled", timeout=600, job_id=job_id)
    else:
        logger.warning("Unknown backup tool '%s' for job %s", tool, job_id)
        return

    with _jobs_lock:
        j = _backup_jobs.get(job_id)
        if j:
            j["last_run_ts"] = time.time()
            j["last_run"] = datetime.now().isoformat()
            j["last_task_id"] = task_id
            j["last_status"] = "running"
    _persist_jobs()


_MAX_JOB_HISTORY = 20  # keep this many completed runs per job


def _update_job_from_task(task_id: str, status: str, error: str | None = None) -> None:
    """Update a backup job's last_status when its task finishes.

    Always writes last_error: None on success, error string on failure.
    This prevents stale errors from a previous run persisting.

    Appends a run record to the job's runs[] list (capped at
    _MAX_JOB_HISTORY) so run history survives task cleanup.
    """
    with _jobs_lock:
        for job in _backup_jobs.values():
            if job.get("last_task_id") == task_id:
                job["last_status"] = status
                job["last_error"] = error  # None clears on success
                # Append run record
                runs = job.setdefault("runs", [])
                runs.append({
                    "task_id": task_id,
                    "started_at": job.get("last_run"),
                    "finished_at": datetime.now().isoformat(),
                    "status": status,
                    "error": error,
                })
                # Keep only the last N
                if len(runs) > _MAX_JOB_HISTORY:
                    job["runs"] = runs[-_MAX_JOB_HISTORY:]
                break
    _persist_jobs()


# ────────────────────────────────────────────────────────────
# APP / LIFECYCLE
# ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Graceful startup/shutdown lifecycle.

    Re-entry guard (_shutting_down flag) prevents double-execution
    if systemd sends SIGTERM while shutdown is already in progress.
    Most thread-unsafe work happens with _task_lock held.
    """
    _load_tasks()
    _load_jobs()
    # Audit log is queried directly from SQLite — no in-memory load needed
    scheduler_task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        global _shutting_down
        scheduler_task.cancel()
        # Re-entry guard: if shutdown is already running, skip.
        with _shutdown_lock:
            if _shutting_down:
                logger.warning("Shutdown re-entry blocked (already shutting down)")
                return
            _shutting_down = True

        pending = list(_background_tasks.items())
        if pending:
            logger.warning("Shutdown — %d background tasks in flight", len(pending))
            for tid, t in pending:
                thread = t.get("thread")
                if thread and thread.is_alive():
                    logger.warning("  Task %s (%s/%s) still running — will be killed",
                                   tid, t.get("tool","?"), t.get("action","?"))
                    # Can't safely kill a thread; will be terminated by process exit.
                    # Mark it so frontend sees "cancelled" on next poll.
                    t["status"] = "cancelled"
                    t["error"] = "Server shutdown during task execution"
                    t["finished_at"] = time.time()
            # Persist cancelled tasks so frontend can poll once after restart
            _persist_tasks()
        for h in logger.handlers:
            h.flush()


app = FastAPI(
    title="ForgeOS API", version="1.0",
    docs_url=None, redoc_url=None,
    lifespan=lifespan,
)

# Auth types + functions imported from forgeos_auth:
#   JWT_SECRET, JWT_ALGO, JWT_EXPIRE, pwd_ctx, LoginRequest,
#   load_users, save_users, create_token, verify_token


# Import routers — these reference verify_token which is now defined
try:
    from filedb_api import router as filedb_router
    app.include_router(filedb_router)
except ImportError as e:
    logger.warning("ForgeFileDB API not available: %s", e)

try:
    from rustfs_api import router as rustfs_router
    app.include_router(rustfs_router)
    logger.info("RustFS Storage API loaded")
except ImportError as e:
    logger.warning("RustFS API not available: %s", e)

try:
    from docker_lxc_api import router as docker_lxc_router
    app.include_router(docker_lxc_router)
    logger.info("Docker Management API loaded")
except ImportError as e:
    logger.warning("Docker API not available: %s", e)

try:
    from lxc_api import router as lxc_router, set_helpers as set_lxc_helpers
    set_lxc_helpers(audit=_audit)
    app.include_router(lxc_router)
    logger.info("LXC / Incus Management API loaded")
except ImportError as e:
    logger.warning("LXC API not available: %s", e)

try:
    from forgeos_pages_api import router as pages_router, set_audit
    set_audit(_audit)
    app.include_router(pages_router)
    logger.info("ForgeOS Pages API loaded (file station, firewall, storage drives, docker compose, nginx, ForgeDB extensions)")
except ImportError as e:
    logger.warning("ForgeOS Pages API not available: %s", e)

# CORS configuration
_allowed_origins = os.environ.get("FORGEOS_CORS_ORIGINS", "").split(",") if os.environ.get("FORGEOS_CORS_ORIGINS") else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Security Headers (CSP via pure ASGI middleware) ───
# Strict CSP: no inline scripts (all onclick removed, external JS only).
# Inline style= still permitted — 99 instances in the UI need cleaning.

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware:
    """ASGI middleware that adds security headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.append((b"content-security-policy", _CSP.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)


# In-memory rate limiter for login attempts — no external dependency needed
_LOGIN_LIMIT_WINDOW = 300   # 5 minutes
_LOGIN_LIMIT_MAX    = 10    # max attempts per window
_login_attempts: dict[str, deque] = {}

def _check_login_rate_limit(client_ip: str) -> None:
    """Track login attempts per IP. Raises 429 if over limit."""
    now = time.time()
    window = _LOGIN_LIMIT_WINDOW
    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = deque()
    dq = _login_attempts[client_ip]
    # Purge entries older than the window
    while dq and dq[0] < now - window:
        dq.popleft()
    if len(dq) >= _LOGIN_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    dq.append(now)


# ─── Mutation rate limiter (ASGI middleware) ───
# Protects all POST/PUT/DELETE from brute-force / DoS.
# Login has its own stricter limiter inside the route handler.
_MUTATION_WINDOW = 60     # 1-minute sliding window
_MUTATION_MAX    = 30     # max mutations per window per IP
_mutation_log: dict[str, deque] = {}


class MutationRateLimitMiddleware:
    """Rate-limit POST/PUT/DELETE per client IP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method in ("POST", "PUT", "DELETE"):
            client = scope.get("client")
            ip = client[0] if client else "unknown"
            now = time.time()

            dq = _mutation_log.get(ip)
            if dq is None:
                _mutation_log[ip] = dq = deque()

            while dq and dq[0] < now - _MUTATION_WINDOW:
                dq.popleft()

            if len(dq) >= _MUTATION_MAX:
                body = b'{"detail":"Too many requests. Try again later."}'
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"60"),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

            dq.append(now)

        await self.app(scope, receive, send)


app.add_middleware(MutationRateLimitMiddleware)


# ────────────────────────────────────────────────────────────
# Shared subprocess + sanitize helpers — used by every router.
# Defined here (before any include_router) so set_helpers() calls
# can pass them in.
# ────────────────────────────────────────────────────────────


def _run_args(args: list, timeout: int = 5) -> str:
    """Run a command with explicit arg list - no shell injection possible."""
    try:
        return subprocess.check_output(
            args, shell=False, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout
        ).strip()
    except subprocess.CalledProcessError:
        return ""
    except subprocess.TimeoutExpired:
        cmd_str = " ".join(str(a) for a in args)[:120]
        logger.warning("_run_args timed out after %ss: %s", timeout, cmd_str)
        return ""


def _sanitize_blockdev(name: str) -> str:
    """Sanitize a block device name, allowing only safe characters."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return safe[:64]


# ────────────────────────────────────────────────────────────
# AUTH — extracted to auth_api.py (Sprint 1 of forgeos-api refactor)
# ────────────────────────────────────────────────────────────
try:
    from auth_api import router as auth_router, set_helpers as set_auth_helpers
    set_auth_helpers(audit=_audit, check_rate_limit=_check_login_rate_limit)
    app.include_router(auth_router)
    logger.info("Auth API loaded")
except ImportError as e:
    logger.error("Auth API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# USERS — native user management (users_api.py, Sprint 6)
# ────────────────────────────────────────────────────────────
try:
    from users_api import router as users_router, set_helpers as set_users_helpers
    set_users_helpers(audit=_audit)
    app.include_router(users_router)
    logger.info("Users API loaded")
except ImportError as e:
    logger.error("Users API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# SYSTEM — extracted to system_api.py (Sprint 1, commit 2)
# Routes: /api/system/stats /api/system/info /api/services
#         /api/network /api/config /api/settings (GET+PUT)
# ────────────────────────────────────────────────────────────
try:
    from system_api import router as system_router, set_helpers as set_system_helpers
    set_system_helpers(
        run_args=_run_args,
        audit=_audit,
        conf=conf,
        conf_file=CONFIG_FILE,
        conf_cache=_conf,
    )
    app.include_router(system_router)
    logger.info("System API loaded")
except ImportError as e:
    logger.error("System API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# STORAGE — extracted to storage_api.py (Sprint 1, commit 3)
# Routes: pools, drives, pool, drive, df, snapshots, snapshot,
#         smart/{device}, hotswap-log, smart-alerts
# ────────────────────────────────────────────────────────────
try:
    from storage_api import router as storage_router, set_helpers as set_storage_helpers
    set_storage_helpers(run_args=_run_args, audit=_audit)
    app.include_router(storage_router)
    logger.info("Storage API loaded")
except ImportError as e:
    logger.error("Storage API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# NGINX — extracted to nginx_api.py (Sprint 1, commit 4)
# ────────────────────────────────────────────────────────────
try:
    from nginx_api import router as nginx_router, set_helpers as set_nginx_helpers
    set_nginx_helpers(run_args=_run_args, audit=_audit)
    app.include_router(nginx_router)
    logger.info("Nginx API loaded")
except ImportError as e:
    logger.error("Nginx API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# SAMBA — extracted to samba_api.py (Sprint 1, commit 5)
# ────────────────────────────────────────────────────────────
try:
    from samba_api import router as samba_router, set_helpers as set_samba_helpers
    set_samba_helpers(run_args=_run_args, audit=_audit)
    app.include_router(samba_router)
    logger.info("Samba API loaded")
except ImportError as e:
    logger.error("Samba API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# FIREWALL — config-DB backed (firewall_api.py, security P1)
# ────────────────────────────────────────────────────────────
try:
    from firewall_api import router as firewall_router, set_helpers as set_firewall_helpers
    set_firewall_helpers(audit=_audit)
    app.include_router(firewall_router)
    logger.info("Firewall API loaded")
except ImportError as e:
    logger.error("Firewall API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# VPN — WireGuard peer management (vpn_api.py, Sprint 5 / LTH-001)
# Wraps the forgeos-vpn CLI installed by 11-vpn.sh.
# ────────────────────────────────────────────────────────────
try:
    from vpn_api import router as vpn_router, set_helpers as set_vpn_helpers
    set_vpn_helpers(run_args=_run_args, audit=_audit)
    app.include_router(vpn_router)
    logger.info("VPN API loaded")
except ImportError as e:
    logger.error("VPN API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# DOCKER — extracted to docker_api.py (Sprint 1, commit 6)
# Note: separate from existing docker_lxc_api.py (lifecycle ops).
# This is just the simple app-browser + install endpoints.
# ────────────────────────────────────────────────────────────
try:
    from docker_api import router as docker_simple_router, set_helpers as set_docker_helpers
    set_docker_helpers(run_args=_run_args, audit=_audit)
    app.include_router(docker_simple_router)
    logger.info("Docker (simple) API loaded")
except ImportError as e:
    logger.error("Docker (simple) API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# SECURITY — extracted to security_api.py (Sprint 1, commit 6)
# ────────────────────────────────────────────────────────────
try:
    from security_api import router as security_router, set_helpers as set_security_helpers
    set_security_helpers(run_args=_run_args, audit=_audit)
    app.include_router(security_router)
    logger.info("Security API loaded")
except ImportError as e:
    logger.error("Security API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# NOTIFICATIONS — extracted to notifications_api.py (Sprint 1, commit 7)
# ────────────────────────────────────────────────────────────
try:
    from notifications_api import router as notifications_router, set_helpers as set_notifications_helpers
    set_notifications_helpers(conf=conf)
    app.include_router(notifications_router)
    logger.info("Notifications API loaded")
except ImportError as e:
    logger.error("Notifications API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# AUDIT — extracted to audit_api.py (Sprint 1, commit 9)
# ────────────────────────────────────────────────────────────
try:
    from audit_api import router as audit_router, set_helpers as set_audit_helpers
    set_audit_helpers(get_db=_get_db)
    app.include_router(audit_router)
    logger.info("Audit API loaded")
except ImportError as e:
    logger.error("Audit API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# IMAGING — extracted to imaging_api.py (Sprint 1, commit 9)
# ────────────────────────────────────────────────────────────
try:
    from imaging_api import router as imaging_router
    app.include_router(imaging_router)
    logger.info("Imaging API loaded")
except ImportError as e:
    logger.error("Imaging API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# SYSTEM METRICS — extracted to system_api.py (Sprint 1, commit 2)
# Routes: /api/system/stats /api/system/info /api/services
#         /api/network /api/config /api/settings (GET+PUT)
# ────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────
# STORAGE — extracted to storage_api.py (Sprint 1, commit 3)
# Routes: pools, drives, pool, drive, df, snapshots, snapshot,
#         smart/{device}, hotswap-log, smart-alerts
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# NGINX — extracted to nginx_api.py (Sprint 1, commit 4)
# Routes: vhosts (CRUD), raw config (GET/PUT), reload, test, certbot
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# SAMBA — extracted to samba_api.py (Sprint 1, commit 5)
# Routes: shares (CRUD), raw config (GET/PUT), connections
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# DOCKER — extracted to docker_api.py (Sprint 1, commit 6)
# Routes: apps list, install
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# DOCKER / INCUS — full lifecycle via docker_lxc_api.py router
#   (mounted at /api/docker with start/stop/restart/logs/exec,
#    compose up/down, prune, images, LXC management)
# ────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────
# NOTIFICATIONS — extracted to notifications_api.py (Sprint 1, commit 7)
# Routes: notify, drive-alert, notifications, drive-alerts, alert-webhook
# State (_notifications, _drive_alerts) moved with them.
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# SECURITY — extracted to security_api.py (Sprint 1, commit 6)
# Routes: fail2ban, firewall status
# ────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────
# HEALTH
# ────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "ts": time.time()}

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
# WEBSOCKET — token extracted from Sec-WebSocket-Protocol header,
#             NOT from query params (avoids leaking in proxy logs).
# ────────────────────────────────────────────────────────────


def _ws_token(ws: WebSocket) -> str:
    """Extract JWT from Sec-WebSocket-Protocol header.
    Client sends: new WebSocket(url, ['forgeos', '<token>'])
    Header arrives as: Sec-WebSocket-Protocol: forgeos, <token>
    """
    proto = ws.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in proto.split(",")] if proto else []
    return parts[1] if len(parts) > 1 else ""


@app.websocket("/ws/metrics")
async def ws_metrics(ws: WebSocket):
    token = _ws_token(ws)
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001)
        return
    await ws.accept(subprotocol="forgeos")
    try:
        while True:
            data = {
                "cpu_pct":  get_cpu_usage(),
                "memory":   get_memory(),
                "load":     get_load(),
                "temps":    get_temps(),
                "ts":       time.time(),
            }
            await ws.send_json(data)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass  # normal disconnect
    except Exception as e:
        logger.warning("ws_live_stats disconnect: %s", e)

# ────────────────────────────────────────────────────────────
# WEBSOCKET — LIVE LOGS
# ────────────────────────────────────────────────────────────
LOG_SOURCES = {
    "system":   "/var/log/syslog",
    "security": "/var/log/auth.log",
    "samba":    "/var/log/forgeos/samba",
    "storage":  "/var/log/forgeos/smart-alerts.log",
    "hotswap":  "/var/log/forgeos/hotswap.log",
    "nginx":    "/var/log/nginx/error.log",
    "forgeos":  "/var/log/forgeos-install.log",
}


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    token = _ws_token(ws)
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001)
        return
    await ws.accept(subprotocol="forgeos")

    source = ws.query_params.get("source", "system")  # harmless — not auth
    log_path = LOG_SOURCES.get(source, "/var/log/syslog")

    # Tail the log file
    proc = await asyncio.create_subprocess_exec(
        "tail", "-n", "50", "-F", log_path,
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
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        pass
    finally:
        proc.kill()

# ────────────────────────────────────────────────────────────
# WEBSOCKET — DOCKER CONTAINER TERMINAL
# ────────────────────────────────────────────────────────────
@app.websocket("/ws/docker/exec/{container}")
async def ws_docker_exec(ws: WebSocket, container: str):
    """WebSocket terminal for Docker container exec."""
    token = _ws_token(ws)
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001)
        return
    await ws.accept(subprotocol="forgeos")
    
    # Start docker exec with PTY
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-it", container, "sh",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    if proc.stdin is None or proc.stdout is None:
        await ws.close(code=4002, reason="Failed to start container shell")
        return
    
    # Forward WebSocket to process
    async def ws_to_proc():
        try:
            while True:
                data = await ws.receive_text()
                if data.startswith("RESIZE:"):
                    # Docker doesn't support TIOCSWINSZ directly via exec
                    pass
                else:
                    proc.stdin.write(data.encode())
                    await proc.stdin.drain()
        except WebSocketDisconnect:
            proc.kill()
        except Exception as e:
            logger.warning("ws_docker_exec ws_to_proc: %s", e)
            proc.kill()
    
    async def proc_to_ws():
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await ws.send_text(data.decode("utf-8", errors="replace"))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("ws_docker_exec proc_to_ws: %s", e)
    
    await asyncio.gather(
        asyncio.create_task(ws_to_proc()),
        asyncio.create_task(proc_to_ws()),
        return_exceptions=True,
    )
    try:
        proc.kill()
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# WEBSOCKET — LXC CONTAINER TERMINAL
# ────────────────────────────────────────────────────────────
@app.websocket("/ws/lxc/exec/{container}")
async def ws_lxc_exec(ws: WebSocket, container: str):
    """WebSocket terminal for LXC container exec."""
    token = _ws_token(ws)
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept(subprotocol="forgeos")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001, reason="Unauthorized")
        return
    
    # Start lxc exec with PTY
    proc = await asyncio.create_subprocess_exec(
        "lxc", "exec", container, "--", "bash", "-l",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    if proc.stdin is None or proc.stdout is None:
        await ws.close(code=4002, reason="Failed to start container shell")
        return
    
    # Forward WebSocket to process
    async def ws_to_proc():
        try:
            while True:
                data = await ws.receive_text()
                if data.startswith("RESIZE:"):
                    pass
                else:
                    proc.stdin.write(data.encode())
                    await proc.stdin.drain()
        except WebSocketDisconnect:
            proc.kill()
        except Exception as e:
            logger.warning("ws_lxc_exec ws_to_proc: %s", e)
            proc.kill()
    
    async def proc_to_ws():
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await ws.send_text(data.decode("utf-8", errors="replace"))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("ws_lxc_exec proc_to_ws: %s", e)
    
    await asyncio.gather(
        asyncio.create_task(ws_to_proc()),
        asyncio.create_task(proc_to_ws()),
        return_exceptions=True,
    )
    try:
        proc.kill()
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# BACKUP — wired here because routes use _start_task and friends,
# which are defined above (see lifespan() at top of file).
# ────────────────────────────────────────────────────────────
try:
    from backup_api import router as backup_router, set_helpers as set_backup_helpers
    set_backup_helpers(
        start_task=_start_task,
        audit=_audit,
        backup_jobs=_backup_jobs,
        jobs_lock=_jobs_lock,
        background_tasks=_background_tasks,
        task_lock=_task_lock,
        persist_jobs=_persist_jobs,
        update_job_from_task=_update_job_from_task,
    )
    app.include_router(backup_router)
    logger.info("Backup API loaded")
except ImportError as e:
    logger.error("Backup API failed to load: %s", e)
    raise


# ────────────────────────────────────────────────────────────
# STATIC WEB UI
# ────────────────────────────────────────────────────────────
if WEB_ROOT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
else:
    @app.get("/")
    async def root():
        return {"message": "ForgeOS API running. Web UI not yet installed."}


# ────────────────────────────────────────────────────────────
# ENTRY POINT — must remain at the bottom of this file.
# All app setup (routes, middleware, lifespan, router includes,
# WebSocket handlers) MUST be defined above this block.
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("FORGEOS_PORT", "5080"))
    # Bind to localhost by default: nginx is the sole front door (it proxies
    # to 127.0.0.1:PORT over TLS). Binding 0.0.0.0 would expose the API in
    # PLAIN HTTP to the whole LAN, bypassing TLS — a real exposure. Override
    # with FORGEOS_HOST only if you know you need it.
    host = os.environ.get("FORGEOS_HOST", "127.0.0.1")
    logger.info("Starting ForgeOS API on %s:%s", host, port)
    uvicorn.run(
        "forgeos-api:app" if __package__ is None else app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
        workers=1,
        # API binds 127.0.0.1 behind nginx; only the proxy can set XFF, so
        # trusting loopback is safe and request.client.host = real client.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
