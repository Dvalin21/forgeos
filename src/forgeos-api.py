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


def _run_background(cmd: list[str], task_id: str, timeout: int = 600) -> None:
    """Run a command in a daemon thread, updating task state."""
    with _task_lock:
        t = _background_tasks.get(task_id)
        if t:
            t["status"] = "running"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                if r.returncode == 0:
                    t["status"] = "done"
                    t["result"] = r.stdout.strip()
                else:
                    t["status"] = "failed"
                    t["error"] = r.stderr.strip() or "Exit code %d" % r.returncode
                t["finished_at"] = time.time()
    except subprocess.TimeoutExpired:
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = "Command timed out"
                t["finished_at"] = time.time()
    except Exception as e:
        with _task_lock:
            t = _background_tasks.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = str(e)
                t["finished_at"] = time.time()


def _start_task(cmd: list[str], tool: str, action: str, timeout: int = 600) -> str:
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
        }
    t = threading.Thread(
        target=_run_background, args=(cmd, task_id, timeout), daemon=True
    )
    t.start()
    return task_id


# ────────────────────────────────────────────────────────────
# APP / LIFECYCLE
# ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Graceful startup/shutdown lifecycle."""
    try:
        yield
    finally:
        pending = list(_background_tasks.keys())
        if pending:
            logger.info("Shutdown — cancelling %d background tasks", len(pending))
            for tid in pending:
                t = _background_tasks[tid]
                if t.get("task") and hasattr(t["task"], "cancel"):
                    t["task"].cancel()
                del _background_tasks[tid]
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


@app.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    _check_login_rate_limit(request.client.host)
    users = load_users()
    if not users:
        raise HTTPException(status_code=503, detail="No users configured. Run forgeos-install to set up admin user.")
    user = users.get(body.username)
    if not user or not pwd_ctx.verify(body.password, user["hash"]):
        logger.warning("FAILED LOGIN user=%s from=%s", body.username, request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(body.username, user["role"])
    resp = JSONResponse({"token": token, "username": body.username, "role": user["role"]})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie("forgeos_token", token, httponly=True, secure=secure, samesite="strict", max_age=JWT_EXPIRE * 3600)
    return resp


@app.post("/api/auth/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("forgeos_token")
    return resp


@app.post("/api/auth/change-password")
async def change_password(body: dict, user=Depends(verify_token)):
    users = load_users()
    u = users.get(user["sub"])
    if not u or not pwd_ctx.verify(body.get("current", ""), u["hash"]):
        raise HTTPException(status_code=401, detail="Current password incorrect")
    users[user["sub"]]["hash"] = pwd_ctx.hash(body["new"])
    save_users(users)
    return {"ok": True}

# ────────────────────────────────────────────────────────────
# SYSTEM METRICS
# ────────────────────────────────────────────────────────────


def _run_shell(cmd: str, timeout: int = 5) -> str:
    """Run a shell command with shell=True (needed for pipes, redirects, &&).

    WARNING: Only call with commands that contain NO unsanitized user input.
    User-supplied values must be validated before interpolation.
    """
    try:
        return subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout
        ).strip()
    except subprocess.CalledProcessError:
        return ""
    except subprocess.TimeoutExpired:
        logger.warning("_run_shell timed out after %ss: %s", timeout, cmd[:120])
        return ""


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


def get_cpu_usage() -> float:
    if _HAVE_PSUTIL:
        return psutil.cpu_percent(interval=0.5)
    # Fallback: read /proc/stat directly
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = [int(x) for x in line.strip().split()[1:]]
                    idle = parts[3]
                    total = sum(parts)
                    return round(100.0 * (1.0 - idle / total) if total else 0.0, 1)
    except Exception as e:
        logger.debug("get_cpu_usage fallback failed: %s", e)
    return 0.0


def get_memory() -> dict:
    if _HAVE_PSUTIL:
        m = psutil.virtual_memory()
        return {"total_gb": round(m.total/1e9, 1), "used_gb": round(m.used/1e9, 1),
                "pct": m.percent}
    # Fallback: read /proc/meminfo directly
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k.strip()] = int(v.strip().split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        free = mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0)
        used = total - free
        return {"total_gb": round(total/1e9, 1), "used_gb": round(used/1e9, 1),
                "pct": round(used/total*100, 1) if total else 0}
    except Exception as e:
        logger.debug("get_memory fallback failed: %s", e)
        return {"total_gb": 0, "used_gb": 0, "pct": 0}


def get_network() -> dict:
    if _HAVE_PSUTIL:
        io = psutil.net_io_counters()
        return {"bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv}
    return {}


def get_uptime() -> str:
    out = _run_args(["uptime", "-p"])
    return out.replace("up ", "") if out else "unknown"


def get_load() -> list[float]:
    try:
        return [round(x, 2) for x in __import__("os").getloadavg()]
    except Exception as e:
        logger.debug("get_load fallback failed: %s", e)
        return [0.0, 0.0, 0.0]


def get_temps() -> dict:
    temps: dict[str, float] = {}
    # CPU temp (various kernel interfaces)
    for path in [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
    ]:
        if Path(path).exists():
            try:
                temps["cpu"] = round(int(Path(path).read_text().strip()) / 1000, 1)
                break
            except Exception as e:
                logger.debug("get_temps read %s failed: %s", path, e)
    # Try psutil sensors
    if _HAVE_PSUTIL:
        try:
            for name, entries in psutil.sensors_temperatures().items():
                for e in entries:
                    if e.current:
                        key = f"{name}/{e.label}" if e.label else name
                        temps[key] = round(e.current, 1)
        except Exception as e:
            logger.debug("get_temps psutil failed: %s", e)
    return temps


@app.get("/api/system/stats")
async def system_stats(user=Depends(verify_token)):
    return {
        "cpu_pct": get_cpu_usage(),
        "memory": get_memory(),
        "network": get_network(),
        "uptime": get_uptime(),
        "load": get_load(),
        "temps": get_temps(),
        "hostname": _run_args(["hostname", "-f"]),
        "kernel": _run_args(["uname", "-r"]),
        "timestamp": time.time(),
    }


@app.get("/api/system/info")
async def system_info(user=Depends(verify_token)):
    return {
        "hostname":   _run_args(["hostname", "-f"]),
        "os":         _run_args(["lsb_release", "-ds"]),
        "kernel":     _run_args(["uname", "-r"]),
        "cpu":        _run_shell("grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2").strip(),
        "cpu_cores":  _run_args(["nproc"]),
        "forgeos_ver": conf("FORGEOS_VERSION", "1.0"),
        "uptime":     get_uptime(),
        "boot_time":  _run_args(["uptime", "-s"]),
    }

# ────────────────────────────────────────────────────────────
# STORAGE — Pool status (grouped by pool, with SMART)
# ────────────────────────────────────────────────────────────


@app.get("/api/storage/pools")
async def storage_pools(user=Depends(verify_token)):
    out = _run_args(["forgeos-pool-status"], timeout=15)
    try:
        return json.loads(out)
    except Exception as e:
        logger.warning("pool-status JSON parse failed: %s", e)
        return {"pools": [], "unassigned": [], "error": "pool-status failed"}


@app.get("/api/storage/drives")
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


@app.post("/api/storage/pool")
async def create_pool(body: dict, user=Depends(verify_token)):
    """Create a RAID pool using mdadm — wraps mdadm --create."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name   = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("name", ""))
    level  = body.get("level", 5)
    drives = body.get("drives", [])
    if not name or len(name) < 2:
        raise HTTPException(400, "Pool name must be at least 2 characters")
    if level not in (0, 1, 5, 6, 10):
        raise HTTPException(400, "Invalid RAID level — must be 0, 1, 5, 6, or 10")
    if len(drives) < 2:
        raise HTTPException(400, "At least 2 drives required")
    # Sanitize drive paths
    clean = []
    for d in drives:
        dev = re.sub(r"[^a-zA-Z0-9_/]", "", str(d))
        if not dev.startswith("/dev/"):
            dev = "/dev/" + dev
        clean.append(dev)
    try:
        r = subprocess.run(
            ["mdadm", "--create", f"/dev/md/{name}",
             "--level", str(level),
             "--raid-devices", str(len(clean)),
             "--run"] + clean,
            capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            raise HTTPException(500, detail=r.stderr.strip() or "mdadm failed")
    except FileNotFoundError:
        raise HTTPException(500, detail="mdadm not installed on this system")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, detail="Pool creation timed out")
    return {"ok": True, "message": f"RAID {level} pool '{name}' created ({len(clean)} drives)"}


@app.post("/api/storage/drive")
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
    return {"ok": True, "message": f"Drive {device} added to pool {pool}"}


@app.get("/api/storage/df")
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


@app.get("/api/storage/snapshots")
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


@app.post("/api/storage/snapshot")
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
    return {"ok": True, "message": f"Snapshot created: {desc}"}


@app.get("/api/storage/smart/{device}")
async def smart_detail(device: str, user=Depends(verify_token)):
    # Strict sanitization: only allow actual block device names
    # Block /dev/ prefix, path traversal, and special devices
    dev = re.sub(r"[^a-z0-9]", "", device)
    # Additional check: reject if it looks like a path or special device
    if dev in ("loop", "ram", "dm", "md") or len(dev) > 20:
        raise HTTPException(400, "Invalid device name")
    out = _run_args(["smartctl", "-a", f"/dev/{dev}"])
    return {"device": f"/dev/{dev}", "output": out}


@app.get("/api/storage/hotswap-log")
async def hotswap_log(user=Depends(verify_token)):
    log = Path("/var/log/forgeos/hotswap.log")
    lines = log.read_text().splitlines()[-50:] if log.exists() else []
    return {"lines": lines}


@app.get("/api/storage/smart-alerts")
async def smart_alerts(user=Depends(verify_token)):
    log = Path("/var/log/forgeos/smart-alerts.log")
    lines = log.read_text().splitlines()[-100:] if log.exists() else []
    return {"alerts": lines}

# ────────────────────────────────────────────────────────────
# NGINX PROXY MANAGEMENT
# ────────────────────────────────────────────────────────────


@app.get("/api/nginx/vhosts")
async def nginx_vhosts(user=Depends(verify_token)):
    """List all vhosts from forgeos.d/*.conf"""
    vhosts = []
    conf_dir = Path("/etc/nginx/forgeos.d")
    if not conf_dir.exists():
        return {"vhosts": []}
    for f in sorted(conf_dir.glob("*.conf")):
        text = f.read_text()
        domain = re.search(r"server_name\s+(\S+);", text)
        upstream = re.search(r"proxy_pass\s+http://\S+:(\d+)", text)
        has_ssl = "ssl_certificate" in text
        name = f.stem
        vhosts.append({
            "name": name,
            "domain": domain.group(1) if domain else name,
            "upstream_port": upstream.group(1) if upstream else "?",
            "ssl": has_ssl,
            "enabled": True,
            "raw": text,
        })
    return {"vhosts": vhosts}


@app.post("/api/nginx/vhost")
async def add_vhost(body: dict, user=Depends(verify_token)):
    """Add a new vhost via forgeos-nginx CLI"""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name   = re.sub(r"[^a-z0-9-]", "", body["name"].lower())
    domain = body["domain"]
    port   = int(body["port"])
    tls    = body.get("tls", "acme")
    ws     = body.get("websocket", False)
    auth   = body.get("auth", "none")

    if not 1 <= port <= 65535:
        raise HTTPException(400, "Invalid port")

    # Sanitize all user inputs before passing to shell
    name   = re.sub(r"[^a-z0-9-]", "", name.lower())[:64]
    domain = re.sub(r"[^a-zA-Z0-9.\-]", "", domain)[:253]
    tls    = tls   if tls  in ("acme", "selfsigned", "none") else "acme"
    auth   = auth  if auth in ("none", "basic", "oidc")      else "none"
    result = _run_args([
        "forgeos-nginx", "add-vhost", name, domain, str(port),
        tls, auth, "yes" if ws else "no"
    ])
    return {"ok": True, "message": result}


@app.delete("/api/nginx/vhost/{name}")
async def remove_vhost(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9-]", "", name)
    result = _run_args(["forgeos-nginx", "remove-vhost", name])
    return {"ok": True, "message": result}


@app.get("/api/nginx/raw")
async def nginx_raw_config(user=Depends(verify_token)):
    return {"config": Path("/etc/nginx/nginx.conf").read_text() if Path("/etc/nginx/nginx.conf").exists() else ""}


@app.put("/api/nginx/raw")
async def nginx_save_raw(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    config = body.get("config", "")
    # Test first using a secure temp file
    import tempfile
    import os as _os
    _fd, _tmp = tempfile.mkstemp(prefix="forgeos-nginx-", suffix=".conf")
    try:
        with _os.fdopen(_fd, "w") as _fh:
            _fh.write(config)
        test = _run_args(["nginx", "-t", "-c", _tmp])
    finally:
        _os.unlink(_tmp) if _os.path.exists(_tmp) else None
    if "failed" in test.lower():
        raise HTTPException(400, detail={"error": "Config test failed", "output": test})
    Path("/etc/nginx/nginx.conf").write_text(config)
    # Test live config, then reload — never reload a broken config
    test = _run_args(["nginx", "-t"], timeout=10)
    if "failed" in test.lower() or "test is successful" not in test:
        raise HTTPException(400, detail={"error": "Live config test failed", "output": test})
    _run_args(["systemctl", "reload", "nginx"])
    return {"ok": True}


@app.post("/api/nginx/reload")
async def nginx_reload(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    # Test config first, only reload if test passes
    test = _run_args(["nginx", "-t"], timeout=10)
    if "test is successful" not in test:
        return {"ok": False, "error": "Config test failed", "output": test}
    result = _run_args(["systemctl", "reload", "nginx"])
    return {"ok": True, "output": result}


@app.post("/api/nginx/test")
async def nginx_test(user=Depends(verify_token)):
    return {"output": _run_args(["nginx", "-t"], timeout=10)}


@app.post("/api/nginx/certbot")
async def request_cert(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    domain = body.get("domain", "")
    email  = body.get("email", "")
    if not domain:
        raise HTTPException(400, "domain required")
    # Strict validation: only allow valid domain/email chars - no shell metacharacters
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$", domain):
        raise HTTPException(400, "Invalid domain name")
    if email and not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email):
        raise HTTPException(400, "Invalid email address")
    # Use arg list - no shell injection possible
    cmd = ["certbot", "certonly", "--nginx", "--non-interactive",
           "--agree-tos", "--email", email or f"admin@{domain}", "-d", domain]
    result = _run_args(cmd, timeout=120)
    return {"ok": True, "output": result}

# ────────────────────────────────────────────────────────────
# SAMBA SHARE MANAGEMENT
# ────────────────────────────────────────────────────────────


@app.get("/api/samba/shares")
async def samba_shares(user=Depends(verify_token)):
    raw = _run_shell("forgeos-samba list 2>&1")
    return {"raw": raw}


@app.post("/api/samba/share")
async def create_share(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name    = re.sub(r"[^a-z0-9_-]", "", body["name"])
    path    = body["path"]
    type_   = body.get("type", "standard")
    write   = "yes" if body.get("writable", True) else "no"
    users   = body.get("users", "@users")
    comment = body.get("comment", "")
    result  = _run_args(["forgeos-samba", "create", name, path, type_, write, users, comment])
    return {"ok": True, "message": result}


@app.delete("/api/samba/share/{name}")
async def remove_share(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9_-]", "", name)
    result = _run_args(["forgeos-samba", "remove", name])
    return {"ok": True, "message": result}


@app.get("/api/samba/raw")
async def samba_raw(user=Depends(verify_token)):
    return {"config": _run_args(["forgeos-samba", "raw-get"])}


@app.put("/api/samba/raw")
async def samba_save_raw(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    config = body.get("config", "")
    # Pipe config via stdin to avoid shell/single-quote escaping entirely
    result = subprocess.run(
        ["forgeos-samba", "raw-put"],
        input=config, capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise HTTPException(400, detail=result.stderr.strip() or "samba config rejected")
    return {"ok": True, "message": result.stdout.strip()}


@app.get("/api/samba/connections")
async def samba_connections(user=Depends(verify_token)):
    return {"output": _run_shell("smbstatus 2>/dev/null || echo 'No connections'")}

# ────────────────────────────────────────────────────────────
# DOCKER APP BROWSER
# ────────────────────────────────────────────────────────────

DOCKER_APPS = [
    {"name": "nginx", "image": "nginx:latest", "port": 80, "category": "web"},
    {"name": "jellyfin", "image": "jellyfin/jellyfin:latest", "port": 8096, "category": "media"},
    {"name": "adguard", "image": "adguard/adguardhome:latest", "port": 3000, "category": "network"},
    {"name": "portainer", "image": "portainer/portainer-ce:latest", "port": 9000, "category": "admin"},
    {"name": "homarr", "image": "ghcr.io/axistent/homarr:latest", "port": 3000, "category": "dashboard"},
    {"name": "nextcloud", "image": "nextcloud:latest", "port": 80, "category": "cloud"},
    {"name": "rustfs", "image": "rustfs/rustfs:latest", "port": 9000, "admin_port": 9001, "category": "storage", "s3_api": True, "console": True},
    {"name": "rustfs-console", "image": "rustfs/console:latest", "port": 9001, "category": "storage", "type": "console"},
    {"name": "prometheus", "image": "prom/prometheus:latest", "port": 9090, "category": "monitoring"},
    {"name": "grafana", "image": "grafana/grafana:latest", "port": 3000, "category": "monitoring"},
    {"name": "immich", "image": "ghcr.io/immich-app/immich-server:latest", "port": 2283, "category": "media"},
]


@app.get("/api/docker/apps")
async def docker_apps(user=Depends(verify_token)):
    """Get available Docker apps for one-click install"""
    return {"apps": DOCKER_APPS}


@app.post("/api/docker/install")
async def docker_install(app: str, image: str = None, ports: List[str] = None, user=Depends(verify_token)):
    """Install Docker app from curated list"""
    app_info = next((a for a in DOCKER_APPS if a["name"] == app), None)
    if not app_info:
        app_info = {"name": app, "image": image or app, "ports": ports or []}

    port_args = []
    if app_info.get("port"):
        port_args = ["-p", f"{app_info['port']}:{app_info['port']}"]

    cmd = ["docker", "run", "-d", "--name", app_info["name"]] + port_args + [app_info["image"]]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Docker pull timed out")

    if result.returncode == 0:
        return {"status": "installed", "app": app_info["name"]}
    raise HTTPException(status_code=500, detail=result.stderr.strip() or "docker run failed")


# ────────────────────────────────────────────────────────────
# DOCKER / INCUS — full lifecycle via docker_lxc_api.py router
#   (mounted at /api/docker with start/stop/restart/logs/exec,
#    compose up/down, prune, images, LXC management)
# ────────────────────────────────────────────────────────────


@app.get("/api/services")
async def list_services(user=Depends(verify_token)):
    """List system services status"""
    services = []
    # Key services to check
    check_services = [
        ("docker", "Docker", "Container runtime"),
        ("smbd", "Samba", "File sharing"),
        ("nginx", "nginx", "Web server"),
        ("fail2ban", "fail2ban", "Intrusion prevention"),
        ("smartd", "smartd", "SMART monitoring"),
        ("wg-quick@", "WireGuard", "VPN server"),
        ("postfix", "Postfix", "Mail server"),
        ("redis-server", "Redis", "Cache server"),
    ]
    for svc, name, desc in check_services:
        # Check if service is active
        if svc.startswith("wg-quick"):
            out = _run_shell(f"systemctl is-active {svc}@*.service 2>/dev/null || echo inactive", timeout=3)
        else:
            out = _run_shell(f"systemctl is-active {svc} 2>/dev/null || echo 'inactive'", timeout=3)
        status = "running" if out.strip() == "active" else "stopped"
        services.append({"name": name, "desc": desc, "status": status})
    return {"services": services}


@app.get("/api/network")
async def list_network(user=Depends(verify_token)):
    """List network interfaces"""
    ifaces = []
    # Get interfaces with IPs — use ip -j (JSON mode) to avoid jq dependency
    out = _run_args(["ip", "-j", "addr", "show"], timeout=5)
    if out:
        try:
            raw = json.loads(out)
            for iface in raw:
                if not isinstance(iface, dict):
                    continue
                for addr_info in iface.get("addr_info", []):
                    if isinstance(addr_info, dict) and addr_info.get("family") == "inet":
                        ifaces.append({
                            "name": iface.get("ifname", "?"),
                            "ip": addr_info.get("local", "N/A"),
                        })
        except Exception as e:
            logger.warning("ip -j addr JSON parse failed: %s", e)
            ifaces = []
    # Fallback: use ip addr
    if not ifaces:
        out = _run_args(["ip", "addr", "show"], timeout=5)
        for line in out.splitlines():
            m = re.match(r'^\d+:\s+(\S+):', line)
            if m and m.group(1) != "lo":
                name = m.group(1)
                ip_out = _run_args(["ip", "addr", "show", name], timeout=3)
                ip_match = re.search(r'inet\s+(\S+)', ip_out)
                ip_addr = ip_match.group(1).split('/')[0] if ip_match else "N/A"
                rx_out = _run_args(["cat", f"/sys/class/net/{name}/statistics/rx_bytes"], timeout=2)
                tx_out = _run_args(["cat", f"/sys/class/net/{name}/statistics/tx_bytes"], timeout=2)
                ifaces.append({
                    "name": name,
                    "ip": ip_addr,
                    "rx": int(rx_out.strip() or 0),
                    "tx": int(tx_out.strip() or 0),
                })
    return {"interfaces": ifaces}


@app.get("/api/config")
async def get_config(user=Depends(verify_token)):
    """Get system config"""
    return {
        "hostname": _run_args(["hostname"]).strip() or "forgeos",
        "domain": conf("DOMAIN", "local"),
        "timezone": conf("TIMEZONE", "UTC"),
    }

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
# SECURITY
# ────────────────────────────────────────────────────────────


@app.get("/api/security/fail2ban")
async def fail2ban_status(user=Depends(verify_token)):
    return {"output": _run_shell("fail2ban-client status 2>/dev/null && fail2ban-client status sshd 2>/dev/null || echo 'fail2ban not running'")}


@app.get("/api/security/crowdsec")
async def crowdsec_status(user=Depends(verify_token)):
    return {"output": _run_shell("cscli decisions list 2>/dev/null || echo 'CrowdSec not installed'")}


@app.get("/api/security/firewall")
async def firewall_status(user=Depends(verify_token)):
    return {
        "ufw": _run_shell("ufw status verbose 2>/dev/null"),
        "iptables_count": _run_shell("iptables -L | wc -l"),
    }

# ────────────────────────────────────────────────────────────
# SETTINGS
# ────────────────────────────────────────────────────────────


@app.get("/api/settings")
async def get_settings(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    safe_keys = [
        "DOMAIN", "HOSTNAME", "TIMEZONE", "ACME_EMAIL",
        "FORGEOS_VERSION", "PRIMARY_POOL", "PRIMARY_POOL_MOUNT",
        "PRIMARY_POOL_TYPE", "HIPAA_ENABLED", "PROXY",
        "MARIADB_ENABLED", "REDIS_ENABLED",
    ]
    return {k: conf(k) for k in safe_keys}


@app.put("/api/settings")
async def save_settings(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    # Only allow safe keys
    allowed = {"DOMAIN", "TIMEZONE", "ACME_EMAIL", "HOSTNAME"}
    safe = {k: v for k, v in body.items() if k in allowed}
    if not safe:
        return {"ok": True, "message": "No allowed settings to update"}
    # Append to config file
    text = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else ""
    for k, v in safe.items():
        text = re.sub(rf'^{k}=.*$', f'{k}="{v}"', text, flags=re.MULTILINE)
        if f'{k}=' not in text:
            text += f'\n{k}="{v}"'
    CONFIG_FILE.write_text(text)
    logger.info("SETTINGS changed by %s: %s", user.get("sub", "unknown"), list(safe.keys()))
    # Reload in-memory cache so settings take effect without restart
    _conf.clear()
    for line in CONFIG_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            _conf[k.strip()] = v.strip().strip('"')
    return {"ok": True, "updated": list(safe.keys())}

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
    
    # Set terminal size helper
    async def set_size(rows: int, cols: int):
        try:
            # Docker doesn't support TIOCSWINSZ directly via exec
            # Would need docker exec -e COLUMNS=cols -e LINES=rows
            pass
        except Exception:
            pass
    
    # Forward WebSocket to process
    async def ws_to_proc():
        try:
            while True:
                data = await ws.receive_text()
                if data.startswith("RESIZE:"):
                    # Handle terminal resize
                    try:
                        _, size = data.split(":", 1)
                        cols, rows = map(int, size.split(","))
                        await set_size(rows, cols)
                    except Exception as e:
                        logger.debug("terminal RESIZE parse failed: %s", e)
                else:
                    proc.stdin.write(data.encode())
                    await proc.stdin.drain()
        except WebSocketDisconnect:
            proc.kill()
        except Exception:
            pass
    
    async def proc_to_ws():
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await ws.send_text(data.decode("utf-8", errors="replace"))
        except Exception:
            pass
    
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
                    # Handle terminal resize if needed
                    pass
                else:
                    proc.stdin.write(data.encode())
                    await proc.stdin.drain()
        except WebSocketDisconnect:
            proc.kill()
        except Exception:
            pass
    
    async def proc_to_ws():
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await ws.send_text(data.decode("utf-8", errors="replace"))
        except Exception:
            pass
    
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
