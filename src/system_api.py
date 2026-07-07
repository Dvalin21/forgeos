"""ForgeOS — System info, metrics, services, network, config, settings.

Mounts under the existing FastAPI app via:

    from system_api import router as system_router, set_helpers as set_system_helpers
    set_system_helpers(run_args=_run_args, audit=_audit, conf=conf, ...)
    app.include_router(system_router)

Routes:
  • GET  /api/system/stats   — live CPU/mem/network/load/temps
  • GET  /api/system/info    — hostname, OS, kernel, CPU model
  • GET  /api/services       — systemd service status for a known list
  • GET  /api/network        — network interfaces with IPs + counters
  • GET  /api/config         — basic system config (hostname, domain, tz)
  • GET  /api/settings       — admin: read whitelisted config keys
  • PUT  /api/settings       — admin: write whitelisted config keys

Helpers injected by the main module at startup. See set_helpers().
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None
_conf_get: Optional[Callable[[str, str], str]] = None
_conf_file_path: Optional[Path] = None
_conf_cache: Optional[dict[str, str]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
    conf: Callable[[str, str], str],
    conf_file: Path,
    conf_cache: dict[str, str],
) -> None:
    """Wire shared helpers from the main module.

    conf_cache is the live _conf dict — passing it by reference lets
    save_settings() clear-and-reload without an extra round-trip.
    """
    global _run_args, _audit, _conf_get, _conf_file_path, _conf_cache
    _run_args = run_args
    _audit = audit
    _conf_get = conf
    _conf_file_path = conf_file
    _conf_cache = conf_cache


# ────────────────────────────────────────────────────────────
# System metrics helpers — kept module-private; only used here.
# ────────────────────────────────────────────────────────────


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
        return {"total_gb": round(m.total / 1e9, 1), "used_gb": round(m.used / 1e9, 1),
                "pct": m.percent}
    # Fallback: read /proc/meminfo directly
    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k.strip()] = int(v.strip().split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        free = mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0)
        used = total - free
        return {"total_gb": round(total / 1e9, 1), "used_gb": round(used / 1e9, 1),
                "pct": round(used / total * 100, 1) if total else 0}
    except Exception as e:
        logger.debug("get_memory fallback failed: %s", e)
        return {"total_gb": 0, "used_gb": 0, "pct": 0}


def get_network_io() -> dict:
    if _HAVE_PSUTIL:
        io = psutil.net_io_counters()
        return {"bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv}
    return {}


def get_uptime() -> str:
    assert _run_args is not None  # set_helpers() must run first
    out = _run_args(["uptime", "-p"])
    return out.replace("up ", "") if out else "unknown"


def get_load() -> list[float]:
    try:
        import os
        return [round(x, 2) for x in os.getloadavg()]
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
                for entry in entries:
                    if entry.current:
                        key = f"{name}/{entry.label}" if entry.label else name
                        temps[key] = round(entry.current, 1)
        except Exception as e:
            logger.debug("get_temps psutil failed: %s", e)
    return temps


# ────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────


@router.get("/api/system/stats")
async def system_stats(user=Depends(verify_token)):
    assert _run_args is not None
    return {
        "cpu_pct": get_cpu_usage(),
        "memory": get_memory(),
        "network": get_network_io(),
        "uptime": get_uptime(),
        "load": get_load(),
        "temps": get_temps(),
        "hostname": _run_args(["hostname", "-f"]),
        "kernel": _run_args(["uname", "-r"]),
        "timestamp": time.time(),
    }


@router.get("/api/system/info")
async def system_info(user=Depends(verify_token)):
    assert _run_args is not None
    assert _conf_get is not None
    # Read CPU model directly from /proc/cpuinfo — no shell piping needed
    cpu_model = ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[-1].strip()
                    break
    except OSError:
        pass
    return {
        "hostname":   _run_args(["hostname", "-f"]),
        "os":         _run_args(["lsb_release", "-ds"]),
        "kernel":     _run_args(["uname", "-r"]),
        "cpu":        cpu_model,
        "cpu_cores":  _run_args(["nproc"]),
        "forgeos_ver": _conf_get("FORGEOS_VERSION", "1.0"),
        "uptime":     get_uptime(),
        "boot_time":  _run_args(["uptime", "-s"]),
    }


@router.get("/api/services")
async def list_services(user=Depends(verify_token)):
    """List system services status."""
    assert _run_args is not None
    services = []
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
        if svc.startswith("wg-quick"):
            # WireGuard uses instance units like wg-quick@wg0.service
            units_out = _run_args(
                ["systemctl", "list-units", f"{svc}*", "--no-legend"],
                timeout=3,
            )
            if units_out and "active" in units_out.splitlines()[0] if units_out else False:
                status = "running"
            else:
                status = "stopped"
        else:
            out = _run_args(["systemctl", "is-active", svc], timeout=3)
            status = "running" if out.strip() == "active" else "stopped"
        services.append({"name": name, "desc": desc, "status": status})
    return {"services": services}


@router.get("/api/network")
async def list_network(user=Depends(verify_token)):
    """List network interfaces."""
    assert _run_args is not None
    ifaces: list[dict[str, Any]] = []
    # Use ip -j (JSON mode) to avoid jq dependency
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
    # Fallback: use ip addr text
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


@router.get("/api/config")
async def get_config(user=Depends(verify_token)):
    """Get system config."""
    assert _run_args is not None
    assert _conf_get is not None
    return {
        "hostname": _run_args(["hostname"]).strip() or "forgeos",
        "domain": _conf_get("DOMAIN", "local"),
        "timezone": _conf_get("TIMEZONE", "UTC"),
    }


@router.get("/api/settings/smtp")
async def get_smtp(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    import forgeos_config as fcfg
    import forgeos_smtp as fsmtp
    m = fcfg.load().smtp
    return {"enabled": m.enabled, "host": m.host, "port": m.port,
            "use_tls": m.use_tls, "use_ssl": m.use_ssl, "username": m.username,
            "from_addr": m.from_addr, "to_addrs": m.to_addrs,
            "password_set": fsmtp.password_path().exists()}


@router.put("/api/settings/smtp")
async def put_smtp(body: dict, user=Depends(verify_token)):
    """Password never enters config.json — keystore file 0600, write-only from
    the UI's perspective (GET only reports password_set)."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    import forgeos_config as fcfg
    import forgeos_smtp as fsmtp
    assert _audit is not None
    cfg = fcfg.load()
    allowed = {"enabled", "host", "port", "use_tls", "use_ssl",
               "username", "from_addr", "to_addrs"}
    merged = {k: getattr(cfg.smtp, k) for k in allowed}
    merged.update({k: v for k, v in body.items() if k in allowed})
    try:
        cfg.smtp = fcfg.SmtpConfig(**merged)
    except ValueError as e:
        raise HTTPException(400, f"invalid SMTP config: {e}")
    pw = body.get("password")
    if pw:
        pp = fsmtp.password_path()
        pp.parent.mkdir(parents=True, exist_ok=True)
        pp.touch(mode=0o600, exist_ok=True)
        pp.write_text(str(pw))
        pp.chmod(0o600)
    fcfg.save(cfg)
    _audit(user["sub"], "settings.smtp", "success",
           f"host={cfg.smtp.host} enabled={cfg.smtp.enabled} pw={'set' if pw else 'kept'}")
    return {"ok": True}


@router.post("/api/settings/smtp/test")
async def smtp_test(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    import forgeos_config as fcfg
    import forgeos_smtp as fsmtp
    m = fcfg.load().smtp
    if not m.enabled:
        raise HTTPException(400, "SMTP is disabled — enable and save first")
    try:
        fsmtp.send(m, "ForgeOS test notification",
                   "SMTP settings are working. Sent from the Settings page.")
    except Exception as e:
        raise HTTPException(502, f"send failed: {str(e)[:300]}")
    return {"ok": True}


@router.get("/api/settings")
async def get_settings(user=Depends(verify_token)):
    """v2: config-DB is the source of truth. The v1 shell-conf read (HIPAA/
    MariaDB/Redis/PROXY vocabulary) is deleted — none of it exists in v2."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    import forgeos_config as fcfg
    cfg = fcfg.load()
    try:
        tz = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        tz = ""
    try:
        real_hostname = subprocess.run(["hostname"], capture_output=True,
                                       text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        real_hostname = ""
    sysc = cfg.naming
    return {"system_hostname": sysc.system_hostname,
            "effective_hostname": sysc.system_hostname or real_hostname,
            "lan_name": sysc.lan_name or ((sysc.system_hostname or real_hostname) + ".local"),
            "public_fqdn": sysc.public_fqdn,
            "timezone": tz,
            "version": _conf_get("FORGEOS_VERSION", "") if _conf_get else ""}


@router.put("/api/settings")
async def save_settings(body: dict, user=Depends(verify_token)):
    """Identity + timezone. Hostname is NEVER silently changed — persisting
    system_hostname here only records intent; hostnamectl stays operator-run
    (same sandbox boundary as timers: /etc/hostname isn't in ReadWritePaths).
    Timezone goes through timedated over D-Bus, which is sandbox-legal."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    import forgeos_config as fcfg
    assert _audit is not None
    cfg = fcfg.load()
    allowed = {"system_hostname", "lan_name", "public_fqdn"}
    merged = {k: getattr(cfg.naming, k) for k in allowed}
    merged.update({k: str(v).strip() for k, v in body.items() if k in allowed})
    try:
        cfg.naming = fcfg.NamingConfig(**merged)
    except ValueError as e:
        raise HTTPException(400, f"invalid identity: {e}")
    updated = list(merged.keys())
    tz = str(body.get("timezone", "")).strip()
    if tz:
        if not re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}", tz):
            raise HTTPException(400, f"invalid timezone: {tz!r}")
        r = subprocess.run(["timedatectl", "set-timezone", tz],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise HTTPException(500, f"timedatectl failed: {r.stderr.strip()[:200]}")
        updated.append("timezone")
    fcfg.save(cfg)
    _audit(user["sub"], "settings.update", "success", ", ".join(updated))
    return {"ok": True, "updated": updated}
