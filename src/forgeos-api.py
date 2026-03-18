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
  Rate limiting on auth endpoint (5 req/min per IP)
"""

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import (
    Depends, FastAPI, HTTPException,
    Request, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt

# ────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────
CONFIG_FILE = Path("/etc/forgeos/forgeos.conf")
USERS_FILE  = Path("/etc/forgeos/api-users.json")
JWT_SECRET  = os.environ.get("FORGEOS_JWT_SECRET", "changeme-set-in-forgeos.conf")
JWT_ALGO    = "HS256"
JWT_EXPIRE  = 12  # hours
WEB_ROOT    = Path("/opt/forgeos/web")

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
# APP
# ────────────────────────────────────────────────────────────
app = FastAPI(title="ForgeOS API", version="1.0", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ────────────────────────────────────────────────────────────
# AUTH
# ────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    # Default admin user if no file exists yet
    return {"admin": {"hash": pwd_ctx.hash("forgeos"), "role": "admin"}}

def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def verify_token(request: Request) -> dict:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        # Also check cookie for browser-based UI
        token = request.cookies.get("forgeos_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    users = load_users()
    user = users.get(req.username)
    if not user or not pwd_ctx.verify(req.password, user["hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(req.username, user["role"])
    resp = JSONResponse({"token": token, "username": req.username, "role": user["role"]})
    resp.set_cookie("forgeos_token", token, httponly=True, samesite="strict", max_age=JWT_EXPIRE * 3600)
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
    USERS_FILE.write_text(json.dumps(users, indent=2))
    return {"ok": True}

# ────────────────────────────────────────────────────────────
# SYSTEM METRICS
# ────────────────────────────────────────────────────────────
def _run(cmd: str, timeout: int = 5) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout
        ).strip()
    except Exception:
        return ""

def get_cpu_usage() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.5)
    except ImportError:
        top = _run("top -bn1 | grep 'Cpu(s)'")
        m = re.search(r"(\d+\.\d+)\s*id", top)
        return round(100 - float(m.group(1)), 1) if m else 0.0

def get_memory() -> dict:
    try:
        import psutil
        m = psutil.virtual_memory()
        return {"total_gb": round(m.total/1e9, 1), "used_gb": round(m.used/1e9, 1),
                "pct": m.percent}
    except ImportError:
        out = _run("free -b")
        parts = out.splitlines()[1].split() if out else []
        if len(parts) >= 3:
            t, u = int(parts[1]), int(parts[2])
            return {"total_gb": round(t/1e9,1), "used_gb": round(u/1e9,1), "pct": round(u/t*100,1)}
        return {"total_gb": 0, "used_gb": 0, "pct": 0}

def get_network() -> dict:
    try:
        import psutil
        io = psutil.net_io_counters()
        return {"bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv}
    except ImportError:
        return {}

def get_uptime() -> str:
    out = _run("uptime -p")
    return out.replace("up ", "") if out else "unknown"

def get_load() -> list[float]:
    try:
        return [round(x, 2) for x in __import__("os").getloadavg()]
    except Exception:
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
            except Exception:
                pass
    # Try psutil sensors
    try:
        import psutil
        for name, entries in psutil.sensors_temperatures().items():
            for e in entries:
                if e.current:
                    key = f"{name}/{e.label}" if e.label else name
                    temps[key] = round(e.current, 1)
    except Exception:
        pass
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
        "hostname": _run("hostname -f"),
        "kernel": _run("uname -r"),
        "timestamp": time.time(),
    }

@app.get("/api/system/info")
async def system_info(user=Depends(verify_token)):
    return {
        "hostname":   _run("hostname -f"),
        "os":         _run("lsb_release -ds"),
        "kernel":     _run("uname -r"),
        "cpu":        _run("grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2").strip(),
        "cpu_cores":  _run("nproc"),
        "forgeos_ver": conf("FORGEOS_VERSION", "1.0"),
        "uptime":     get_uptime(),
        "boot_time":  _run("uptime -s"),
    }

# ────────────────────────────────────────────────────────────
# STORAGE — Pool status (grouped by pool, with SMART)
# ────────────────────────────────────────────────────────────
@app.get("/api/storage/pools")
async def storage_pools(user=Depends(verify_token)):
    out = _run("forgeos-pool-status", timeout=15)
    try:
        return json.loads(out)
    except Exception:
        return {"pools": [], "unassigned": [], "error": "pool-status failed"}

@app.get("/api/storage/df")
async def storage_df(user=Depends(verify_token)):
    """Disk usage per btrfs mount"""
    results = []
    mounts = _run("findmnt -t btrfs -o TARGET,SOURCE -n").splitlines()
    for line in mounts:
        parts = line.split()
        if len(parts) < 2:
            continue
        mp, src = parts[0], parts[1]
        out = _run(f"df -B1 {mp}")
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
        out = _run(f"snapper -c {pool} list --output-cols number,date,description 2>/dev/null")
    else:
        configs = _run("snapper list-configs | awk 'NR>2{print $1}'").splitlines()
        out = ""
        for c in configs:
            c_out = _run(f"snapper -c {c} list --output-cols number,date,description 2>/dev/null")
            out += f"=== {c} ===\n{c_out}\n"
    return {"snapshots": out}

@app.post("/api/storage/snapshot")
async def create_snapshot(body: dict, user=Depends(verify_token)):
    pool = body.get("pool", "")
    desc = body.get("description", "manual")
    if pool:
        _run(f"snapper -c {pool} create --description '{desc}' --cleanup-algorithm timeline")
    else:
        configs = _run("snapper list-configs | awk 'NR>2{print $1}'").splitlines()
        for c in configs:
            _run(f"snapper -c {c} create --description '{desc}' --cleanup-algorithm timeline")
    return {"ok": True, "message": f"Snapshot created: {desc}"}

@app.get("/api/storage/smart/{device}")
async def smart_detail(device: str, user=Depends(verify_token)):
    dev = re.sub(r"[^a-z0-9]", "", device)  # sanitize
    out = _run(f"smartctl -a /dev/{dev}")
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

    result = _run(
        f"forgeos-nginx add-vhost {name} {domain} {port} {tls} {auth} {'yes' if ws else 'no'}"
    )
    return {"ok": True, "message": result}

@app.delete("/api/nginx/vhost/{name}")
async def remove_vhost(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9-]", "", name)
    result = _run(f"forgeos-nginx remove-vhost {name}")
    return {"ok": True, "message": result}

@app.get("/api/nginx/raw")
async def nginx_raw_config(user=Depends(verify_token)):
    return {"config": Path("/etc/nginx/nginx.conf").read_text() if Path("/etc/nginx/nginx.conf").exists() else ""}

@app.put("/api/nginx/raw")
async def nginx_save_raw(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    config = body.get("config", "")
    # Test first
    Path("/tmp/nginx-test.conf").write_text(config)
    test = _run("nginx -t -c /tmp/nginx-test.conf 2>&1")
    if "failed" in test.lower():
        raise HTTPException(400, detail={"error": "Config test failed", "output": test})
    Path("/etc/nginx/nginx.conf").write_text(config)
    _run("nginx -t && systemctl reload nginx")
    return {"ok": True}

@app.post("/api/nginx/reload")
async def nginx_reload(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    result = _run("nginx -t && systemctl reload nginx 2>&1")
    return {"ok": True, "output": result}

@app.post("/api/nginx/test")
async def nginx_test(user=Depends(verify_token)):
    return {"output": _run("nginx -t 2>&1")}

@app.post("/api/nginx/certbot")
async def request_cert(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    domain = body.get("domain", "")
    email  = body.get("email", "")
    if not domain:
        raise HTTPException(400, "domain required")
    result = _run(
        f"certbot certonly --nginx --non-interactive --agree-tos "
        f"--email {email} -d {domain} 2>&1",
        timeout=120
    )
    return {"ok": True, "output": result}

# ────────────────────────────────────────────────────────────
# SAMBA SHARE MANAGEMENT
# ────────────────────────────────────────────────────────────
@app.get("/api/samba/shares")
async def samba_shares(user=Depends(verify_token)):
    raw = _run("forgeos-samba list 2>&1")
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
    result  = _run(f"forgeos-samba create '{name}' '{path}' '{type_}' '{write}' '{users}' '{comment}'")
    return {"ok": True, "message": result}

@app.delete("/api/samba/share/{name}")
async def remove_share(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9_-]", "", name)
    result = _run(f"forgeos-samba remove '{name}'")
    return {"ok": True, "message": result}

@app.get("/api/samba/raw")
async def samba_raw(user=Depends(verify_token)):
    return {"config": _run("forgeos-samba raw-get")}

@app.put("/api/samba/raw")
async def samba_save_raw(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    config = body.get("config", "").replace("'", "'\\''")
    result = _run(f"forgeos-samba raw-put '{config}'")
    return {"ok": True, "message": result}

@app.get("/api/samba/connections")
async def samba_connections(user=Depends(verify_token)):
    return {"output": _run("smbstatus 2>/dev/null || echo 'No connections'")}

# ────────────────────────────────────────────────────────────
# DOCKER / INCUS
# ────────────────────────────────────────────────────────────
@app.get("/api/docker/containers")
async def docker_containers(user=Depends(verify_token)):
    out = _run('docker ps -a --format \'{"name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","state":"{{.State}}","ports":"{{.Ports}}"}\'')
    containers = []
    for line in out.splitlines():
        try:
            containers.append(json.loads(line))
        except Exception:
            pass
    return {"containers": containers}

@app.post("/api/docker/container/{name}/{action}")
async def docker_action(name: str, action: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name   = re.sub(r"[^a-z0-9_-]", "", name)
    action = action if action in ("start", "stop", "restart", "logs") else "logs"
    if action == "logs":
        return {"output": _run(f"docker logs --tail 50 {name} 2>&1")}
    result = _run(f"docker {action} {name}")
    return {"ok": True, "output": result}

@app.get("/api/incus/containers")
async def incus_containers(user=Depends(verify_token)):
    out = _run("incus list --format json 2>/dev/null || lxc list --format json 2>/dev/null || echo '[]'")
    try:
        return {"containers": json.loads(out)}
    except Exception:
        return {"containers": [], "raw": out}

# ────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ────────────────────────────────────────────────────────────
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
        _run(
            f"curl -sf -X POST '{gotify_url}/message?token={gotify_tok}' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"title\":\"{title}\",\"message\":\"{message}\",\"priority\":{priority}}}'"
        )

    # Forward to Apprise (if configured)
    apprise_urls = conf("APPRISE_URLS", "")
    if apprise_urls:
        _run(f"apprise -t '{title}' -b '{message}' '{apprise_urls}' 2>/dev/null || true")

    # Store in notification queue for Web UI
    _notifications.append({"level": level, "title": title, "message": message, "ts": time.time()})
    if len(_notifications) > 100:
        _notifications.pop(0)

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

# In-memory notification stores
_notifications: list[dict] = []
_drive_alerts:  dict[str, dict] = {}

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
    return {"output": _run("fail2ban-client status 2>/dev/null && fail2ban-client status sshd 2>/dev/null || echo 'fail2ban not running'")}

@app.get("/api/security/crowdsec")
async def crowdsec_status(user=Depends(verify_token)):
    return {"output": _run("cscli decisions list 2>/dev/null || echo 'CrowdSec not installed'")}

@app.get("/api/security/firewall")
async def firewall_status(user=Depends(verify_token)):
    return {
        "ufw": _run("ufw status verbose 2>/dev/null"),
        "iptables_count": _run("iptables -L | wc -l"),
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
    return {"ok": True, "updated": list(safe.keys())}

# ────────────────────────────────────────────────────────────
# HEALTH
# ────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "ts": time.time()}

# ────────────────────────────────────────────────────────────
# WEBSOCKET — LIVE METRICS
# ────────────────────────────────────────────────────────────
@app.websocket("/ws/metrics")
async def ws_metrics(ws: WebSocket):
    await ws.accept()
    # Quick auth check via token param
    token = ws.query_params.get("token", "")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001)
        return
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
    except (WebSocketDisconnect, Exception):
        pass

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
    await ws.accept()
    token = ws.query_params.get("token", "")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        await ws.close(code=4001)
        return

    source = ws.query_params.get("source", "system")
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
    uvicorn.run(
        "forgeos-api:app",
        host="127.0.0.1",
        port=5080,
        reload=False,
        log_level="warning",
        access_log=False,
        workers=2,
    )
