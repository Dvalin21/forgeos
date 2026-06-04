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
        rows = conn.execute("SELECT * FROM tasks").fetchall()
        columns = [desc[0] for desc in conn.description]
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
        rows = conn.execute("SELECT * FROM backup_jobs").fetchall()
        columns = [desc[0] for desc in conn.description]
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
    logger.info("Docker & LXC Management API loaded")
except ImportError as e:
    logger.warning("Docker/LXC API not available: %s", e)

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
    set_security_helpers(run_args=_run_args)
    app.include_router(security_router)
    logger.info("Security API loaded")
except ImportError as e:
    logger.error("Security API failed to load: %s", e)
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
# NOTIFICATIONS
# ────────────────────────────────────────────────────────────

# In-memory notification stores — defined before first usage below.
# NOTE: workers=1 in production. These are NOT thread-safe.
# If workers>1 is needed, wrap access with asyncio.Lock.
_notifications: deque[dict] = deque(maxlen=100)
_drive_alerts:  dict[str, dict] = {}


@app.post("/api/notify")
async def notify(body: dict):
    """Internal notification endpoint — called by scripts and alertmanager"""
    level   = body.get("level", "info")
    title   = body.get("title", "ForgeOS")
    message = body.get("message", "")

    # Forward to Gotify
    gotify_url = conf("GOTIFY_URL", "http://localhost:8070")
    gotify_tok = conf("GOTIFY_TOKEN", "")
    if gotify_tok:
        priority = {"info": 2, "warning": 5, "warn": 5, "critical": 10, "err": 8}.get(level, 2)
        _payload = json.dumps({"title": title, "message": message, "priority": priority})
        subprocess.run(
            ["curl", "-sf", "-X", "POST",
             f"{gotify_url}/message?token={gotify_tok}",
             "-H", "Content-Type: application/json",
             "-d", _payload],
            capture_output=True, timeout=10
        )

    # Forward to Apprise (if configured)
    apprise_urls = conf("APPRISE_URLS", "")
    if apprise_urls:
        subprocess.run(
            ["apprise", "-t", title, "-b", message, apprise_urls],
            capture_output=True, timeout=10
        )

    # Store in notification queue for Web UI
    # NOTE: workers=1 in production. _notifications is NOT thread-safe.
    # If workers>1 is needed, wrap with asyncio.Lock.
    _notifications.append({"level": level, "title": title, "message": message, "ts": time.time()})

    return {"ok": True}


@app.post("/api/drive-alert")
async def drive_alert(body: dict):
    """Drive SMART/hot-swap alerts — updates tray indicators"""
    _drive_alerts[body.get("device", "?")] = {
        "level": body.get("level", "warn"),
        "message": body.get("message", ""),
        "ts": time.time(),
    }
    await notify(body)
    return {"ok": True}


@app.get("/api/notifications")
async def get_notifications(user=Depends(verify_token)):
    return {"notifications": list(reversed(_notifications[-20:]))}


@app.get("/api/drive-alerts")
async def get_drive_alerts(user=Depends(verify_token)):
    return {"alerts": _drive_alerts}

# Alertmanager webhook bridge


@app.post("/api/alert-webhook")
async def alertmanager_webhook(body: dict):
    for alert in body.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status_ = alert.get("status", "firing")
        level = "critical" if status_ == "firing" else "info"
        title = labels.get("alertname", "Alert")
        message = annotations.get("description", annotations.get("summary", str(labels)))
        await notify({"level": level, "title": title, "message": message})
    return {"ok": True}

# ────────────────────────────────────────────────────────────
# SECURITY — extracted to security_api.py (Sprint 1, commit 6)
# Routes: fail2ban, crowdsec, firewall status
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
# STATIC WEB UI
# ────────────────────────────────────────────────────────────
if WEB_ROOT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
else:
    @app.get("/")
    async def root():
        return {"message": "ForgeOS API running. Web UI not yet installed."}

# ────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("FORGEOS_PORT", "5080"))
    logger.info("Starting ForgeOS API on port %s", port)
    uvicorn.run(
        "forgeos-api:app" if __package__ is None else app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
        workers=1,
    )

# ────────────────────────────────────────────────────────────
# BACKUP HELPERS
# ────────────────────────────────────────────────────────────


def _check_tool(name: str, version_args: list[str] | None = None) -> bool:
    """Check if a CLI tool is installed and executable."""
    try:
        cmd = [name]
        if version_args:
            cmd.extend(version_args)
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _require_tool(name: str, version_args: list[str] | None = None) -> None:
    """Like _check_tool but raises HTTPException if not found."""
    if not _check_tool(name, version_args):
        raise HTTPException(status_code=500, detail=f"{name} not installed")


# ────────────────────────────────────────────────────────────
# BORG BACKUP
# ────────────────────────────────────────────────────────────


@app.get("/api/backup/borg/status")
async def borg_status(user=Depends(verify_token)):
    """Get Borg backup status and jobs"""
    installed = _check_tool("borg", ["version"])
    jobs = []
    if installed:
        try:
            list_result = subprocess.run(
                ["borg", "list", "--json", "/backup"],
                capture_output=True, text=True, timeout=30
            )
            if list_result.returncode == 0:
                try:
                    jobs = json.loads(list_result.stdout)
                except Exception as e:
                    logger.warning("borg list JSON parse failed: %s", e)
                    jobs = []
        except subprocess.TimeoutExpired:
            pass  # jobs stays []
    return {"installed": installed, "jobs": jobs}


@app.post("/api/backup/borg/create")
async def borg_create(body: dict, user=Depends(verify_token)):
    """Create new Borg backup job (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("borg", ["version"])
    
    name = body.get("name", "backup")
    source = body.get("source", "")
    destination = body.get("destination", "/backup")
    
    if not source:
        raise HTTPException(status_code=400, detail="Source required")
    
    archive_name = f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cmd = ["borg", "create", f"{destination}::{archive_name}", source]
    task_id = _start_task(cmd, "borg", "create", timeout=600)
    _audit(user["sub"], "backup.borg.create", "success",
            f"Borg archive '{archive_name}' from {source} to {destination}")
    return {"task_id": task_id, "archive": archive_name, "status": "running"}


@app.get("/api/backup/borg/list")
async def borg_list(destination: str, user=Depends(verify_token)):
    """List archives in repository"""
    _require_tool("borg", ["version"])
    
    try:
        result = subprocess.run(
            ["borg", "list", "--json", destination],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Listing archives timed out")
    if result.returncode == 0:
        try:
            return {"archives": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"archives": []}
    raise HTTPException(status_code=500, detail="Failed to list archives")


# ────────────────────────────────────────────────────────────
# RESTIC BACKUP
# ────────────────────────────────────────────────────────────


@app.get("/api/backup/restic/status")
async def restic_status(user=Depends(verify_token)):
    """Get Restic status"""
    return {"installed": _check_tool("restic", ["version"])}


@app.post("/api/backup/restic/snapshot")
async def restic_snapshot(body: dict, user=Depends(verify_token)):
    """Create Restic snapshot (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("restic", ["version"])
    
    repo = body.get("repo", "/backup/restic")
    paths = body.get("paths", [])
    
    if not paths:
        raise HTTPException(status_code=400, detail="Paths required")
    
    cmd = ["restic", "-r", repo, "snapshot"] + paths
    task_id = _start_task(cmd, "restic", "snapshot", timeout=600)
    _audit(user["sub"], "backup.restic.snapshot", "success",
            f"Restic snapshot of {len(paths)} paths to {repo}")
    return {"task_id": task_id, "status": "running"}


@app.get("/api/backup/restic/snapshots")
async def restic_snapshots(repo: str, user=Depends(verify_token)):
    """List restic snapshots"""
    _require_tool("restic", ["version"])
    
    cmd = ["restic", "-r", repo, "snapshots", "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"snapshots": []}
    if result.returncode == 0:
        try:
            return {"snapshots": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"snapshots": []}
    return {"snapshots": []}


# ────────────────────────────────────────────────────────────
# RCLONE SYNC
# ────────────────────────────────────────────────────────────


@app.get("/api/backup/rclone/status")
async def rclone_status(user=Depends(verify_token)):
    """Get RClone status"""
    return {"installed": _check_tool("rclone", ["version"])}


@app.post("/api/backup/rclone/sync")
async def rclone_sync(body: dict, user=Depends(verify_token)):
    """Run RClone sync (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("rclone", ["version"])
    
    source = body.get("source", "")
    destination = body.get("destination", "")
    config = body.get("config", None)
    
    if not source or not destination:
        raise HTTPException(status_code=400, detail="Source and destination required")
    
    cmd = ["rclone", "sync", source, destination]
    if config:
        cmd.extend(["--config", config])
    task_id = _start_task(cmd, "rclone", "sync", timeout=600)
    _audit(user["sub"], "backup.rclone.sync", "success",
            f"Rclone sync from {source} to {destination}")
    return {"task_id": task_id, "status": "running"}


@app.get("/api/backup/rclone/configs")
async def rclone_configs(user=Depends(verify_token)):
    """List RClone configs"""
    if not _check_tool("rclone", ["version"]):
        return {"remotes": []}
    
    try:
        result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {"remotes": []}
    if result.returncode == 0:
        remotes = [r for r in result.stdout.strip().split("\n") if r]
        return {"remotes": remotes}
    return {"remotes": []}


# ────────────────────────────────────────────────────────────
# SCHEDULED BACKUP JOBS — CRUD
# ────────────────────────────────────────────────────────────


@app.get("/api/backup/jobs")
async def list_backup_jobs(user=Depends(verify_token)):
    """List all configured backup jobs."""
    with _jobs_lock:
        jobs = sorted(
            _backup_jobs.values(),
            key=lambda j: j.get("created_at", ""),
            reverse=True,
        )
    return {"jobs": jobs}


@app.post("/api/backup/jobs")
async def create_backup_job(body: dict, user=Depends(verify_token)):
    """Create a new scheduled backup job."""
    tool = body.get("tool", "")
    if tool not in ("borg", "restic", "rclone"):
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool}")
    if not body.get("source"):
        raise HTTPException(status_code=400, detail="source required")
    if not body.get("destination"):
        raise HTTPException(status_code=400, detail="destination required")

    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with _jobs_lock:
        _backup_jobs[job_id] = {
            "id": job_id,
            "name": body.get("name", f"{tool} backup"),
            "tool": tool,
            "enabled": body.get("enabled", True),
            "source": body.get("source", []),
            "destination": body.get("destination", ""),
            "schedule": body.get("schedule", "daily"),
            "retention": body.get("retention", {}),
            "created_at": now,
            "updated_at": now,
            "last_run": None,
            "last_run_ts": 0,
            "last_status": None,
            "last_task_id": None,
        }
    _persist_jobs()
    name = body.get("name", f"{tool} backup")
    _audit(user["sub"], "backup.job.create", "success",
            f"Created {tool} backup job '{name}' ({job_id})")
    return _backup_jobs[job_id]


@app.get("/api/backup/jobs/{job_id}")
async def get_backup_job(job_id: str, user=Depends(verify_token)):
    """Get a single backup job by ID."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.put("/api/backup/jobs/{job_id}")
async def update_backup_job(job_id: str, body: dict, user=Depends(verify_token)):
    """Update an existing backup job."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Only update fields that are provided
    updatable = {"name", "tool", "enabled", "source", "destination",
                 "schedule", "retention"}
    updated_fields = []
    with _jobs_lock:
        for key in updatable:
            if key in body:
                old = job.get(key)
                if old != body[key]:
                    updated_fields.append(key)
                job[key] = body[key]
        job["updated_at"] = datetime.now().isoformat()
    _persist_jobs()
    _audit(user["sub"], "backup.job.update", "success",
            f"Updated job '{job.get('name', job_id)}': {', '.join(updated_fields)}")
    return job


@app.delete("/api/backup/jobs/{job_id}")
async def delete_backup_job(job_id: str, user=Depends(verify_token)):
    """Delete a backup job."""
    with _jobs_lock:
        if job_id not in _backup_jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        name = _backup_jobs[job_id].get("name", job_id)
        del _backup_jobs[job_id]
    _persist_jobs()
    _audit(user["sub"], "backup.job.delete", "success",
            f"Deleted backup job '{name}' ({job_id})")
    return {"ok": True, "deleted": job_id}


@app.post("/api/backup/jobs/{job_id}/run")
async def run_backup_job_now(job_id: str, user=Depends(verify_token)):
    """Trigger an immediate run of a backup job."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _execute_backup_job(job_id)
    _audit(user["sub"], "backup.job.run", "success",
            f"Triggered backup job '{job.get('name', job_id)}'")
    return {"ok": True, "job_id": job_id, "status": "triggered"}


# ────────────────────────────────────────────────────────────
# BACKGROUND TASK STATUS
# ────────────────────────────────────────────────────────────


@app.get("/api/backup/task/{task_id}")
async def get_task_status(task_id: str, user=Depends(verify_token)):
    """Poll background task status."""
    with _task_lock:
        t = _background_tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return t


@app.get("/api/backup/tasks")
async def list_tasks(user=Depends(verify_token)):
    """List all recent background tasks (newest first)."""
    with _task_lock:
        tasks = list(_background_tasks.values())
    return {"tasks": sorted(tasks, key=lambda x: x.get("started_at", 0), reverse=True)}


# ────────────────────────────────────────────────────────────
# AUDIT LOG
# ────────────────────────────────────────────────────────────


@app.get("/api/audit")
async def list_audit_log(user=Depends(verify_token),
                         limit: int = 100, offset: int = 0,
                         action: str | None = None,
                         who: str | None = None):
    """Query the audit log. Newest first, with optional filters.

    Query params:
      limit   — max entries to return (default 100, max 1000)
      offset  — skip N entries from the front (for pagination)
      action  — filter by action name (e.g. "backup.job.create")
      who     — filter by username
    """
    limit = min(limit, 1000)
    conn = _get_db()
    where = []
    params = []
    if action:
        where.append("action = ?")
        params.append(action)
    if who:
        where.append("who = ?")
        params.append(who)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = conn.execute(
        f"SELECT count(*) FROM audit_log{where_clause}", params
    ).fetchone()
    total = total_row[0] if total_row else 0
    rows = conn.execute(
        f"SELECT timestamp, who, action, status, detail FROM audit_log{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    columns = ["timestamp", "who", "action", "status", "detail"]
    return {"entries": [dict(zip(columns, r)) for r in rows], "total": total, "limit": limit, "offset": offset}


# ────────────────────────────────────────────────────────────
# FOG IMAGING
# ────────────────────────────────────────────────────────────


@app.get("/api/imaging/status")
async def imaging_status(user=Depends(verify_token)):
    """Get FOG imaging status"""
    fog_installed = os.path.exists("/opt/fog")
    images = []
    hosts = []
    
    if fog_installed:
        img_dir = "/images"
        if os.path.exists(img_dir):
            try:
                images = os.listdir(img_dir)
            except Exception as e:
                logger.warning("imaging images list failed: %s", e)
    
    return {"fog_installed": fog_installed, "images": images, "hosts": hosts}


@app.post("/api/imaging/capture")
async def imaging_capture(hostname: str, image_name: str, user=Depends(verify_token)):
    """Request FOG image capture — STUB: FOG integration not yet implemented"""
    raise HTTPException(status_code=501, detail="FOG imaging capture not yet implemented")


@app.post("/api/imaging/deploy")
async def imaging_deploy(image_name: str, target_host: str, user=Depends(verify_token)):
    """Deploy image to target — STUB: FOG integration not yet implemented"""
    raise HTTPException(status_code=501, detail="FOG imaging deploy not yet implemented")
