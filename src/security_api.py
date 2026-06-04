"""ForgeOS — SECURITY API surface.

Mounts under the existing FastAPI app via:

    from security_api import router as security_router, set_helpers as set_security_helpers
    set_security_helpers(run_args=_run_args)
    app.include_router(security_router)

Routes (/api/security/*): fail2ban, crowdsec, firewall status
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None


def set_helpers(
    run_args: Callable[..., str],
) -> None:
    global _run_args
    _run_args = run_args


@router.get("/api/security/fail2ban")
async def fail2ban_status(user=Depends(verify_token)):
    # Run both commands separately, combine in Python — no shell piping
    out1 = _run_args(["fail2ban-client", "status"])
    out2 = _run_args(["fail2ban-client", "status", "sshd"])
    if out1:
        combined = out1
        if out2:
            combined += "\n" + out2
        return {"output": combined}
    return {"output": "fail2ban not running"}


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

