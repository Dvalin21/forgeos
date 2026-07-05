"""ForgeOS — SECURITY API surface.

Mounts under the existing FastAPI app via:

    from security_api import router as security_router, set_helpers as set_security_helpers
    set_security_helpers(run_args=_run_args)
    app.include_router(security_router)

Routes (/api/security/*): fail2ban, crowdsec, firewall status
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

import forgeos_config as fc
from generators import registry
from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None


_audit: Optional[Callable] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Optional[Callable] = None,
) -> None:
    global _run_args, _audit
    _run_args = run_args
    _audit = audit


@router.get("/api/security/fail2ban")
async def fail2ban_status(user=Depends(verify_token)):
    """Per-jail state from config-DB + live bans from fail2ban-client."""
    cfg = fc.load()
    f2b = cfg.security.fail2ban
    jails = {"sshd": f2b.jail_sshd, "nginx-http-auth": f2b.jail_nginx,
             "forgeos-api": f2b.jail_forgeos}
    out = {"enabled": f2b.enabled, "bantime": f2b.bantime,
           "findtime": f2b.findtime, "maxretry": f2b.maxretry, "jails": []}
    assert _run_args is not None
    for name, on in jails.items():
        j = {"name": name, "enabled": bool(f2b.enabled and on), "banned": [], "total": 0}
        if j["enabled"]:
            try:
                raw = _run_args(["fail2ban-client", "status", name])
                m = re.search(r"Banned IP list:\s*(.*)", raw)
                if m and m.group(1).strip():
                    j["banned"] = m.group(1).split()
                m = re.search(r"Total banned:\s*(\d+)", raw)
                if m:
                    j["total"] = int(m.group(1))
            except Exception:
                j["error"] = "jail not responding"
        out["jails"].append(j)
    return out


@router.post("/api/security/fail2ban/unban")
async def fail2ban_unban(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    ip = str(body.get("ip", "")).strip()
    import ipaddress
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, detail=f"invalid IP: {ip!r}")
    assert _run_args is not None
    _run_args(["fail2ban-client", "unban", ip])
    if _audit is not None:
        _audit(user["sub"], "security.fail2ban.unban", "success", ip)
    return {"ok": True, "ip": ip}


@router.put("/api/security/fail2ban")
async def fail2ban_config(body: dict, user=Depends(verify_token)):
    """Update tunables/jail switches; regenerates jail.d + filter and reloads."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    cfg = fc.load()
    try:
        cfg.security.fail2ban = fc.Fail2banConfig(
            **{**cfg.security.fail2ban.model_dump(), **body})
    except (ValueError, Exception) as e:
        from pydantic import ValidationError
        if isinstance(e, (ValidationError, ValueError)):
            raise HTTPException(400, detail=f"invalid fail2ban config: {e}")
        raise
    if _apply is not None:
        _apply(cfg)
    else:
        res = registry.apply_one("security", cfg=cfg)
        if not res.ok:
            raise HTTPException(500, f"fail2ban apply failed: {res.error}")
        fc.save(cfg)
    if _audit is not None:
        _audit(user["sub"], "security.fail2ban.config", "success", str(body))
    return {"ok": True, "fail2ban": cfg.security.fail2ban.model_dump()}


_apply = None


def set_apply(fn) -> None:
    """Test seam: inject converge+persist."""
    global _apply
    _apply = fn


@router.get("/api/security/crowdsec")
async def crowdsec_status(user=Depends(verify_token)):
    out = _run_args(["cscli", "decisions", "list"])
    return {"output": out or "CrowdSec not installed"}


@router.get("/api/security/firewall")
async def firewall_status(user=Depends(verify_token)):
    ufw_out = _run_args(["ufw", "status", "verbose"])
    iptables_out = _run_args(["iptables", "-L"])
    iptables_count = str(len(iptables_out.splitlines())) if iptables_out else "0"
    return {
        "ufw": ufw_out,
        "iptables_count": iptables_count,
    }

