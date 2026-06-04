"""ForgeOS — SAMBA API surface.

Mounts under the existing FastAPI app via:

    from samba_api import router as samba_router, set_helpers as set_samba_helpers
    set_samba_helpers(run_args=_run_args, audit=_audit)
    app.include_router(samba_router)

Routes (/api/samba/*): shares (CRUD), raw config (GET/PUT), connections
"""
from __future__ import annotations

import re
import subprocess
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
_audit: Optional[Callable[..., None]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
) -> None:
    global _run_args, _audit
    _run_args = run_args
    _audit = audit


@router.get("/api/samba/shares")
async def samba_shares(user=Depends(verify_token)):
    raw = _run_args(["forgeos-samba", "list"])
    return {"raw": raw}


@router.post("/api/samba/share")
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
    _audit(user["sub"], "samba.share.create", "success",
            f"Share '{name}' at '{path}' ({'rw' if write == 'yes' else 'ro'})")
    return {"ok": True, "message": result}


@router.delete("/api/samba/share/{name}")
async def remove_share(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9_-]", "", name)
    result = _run_args(["forgeos-samba", "remove", name])
    _audit(user["sub"], "samba.share.delete", "success", f"Share '{name}' removed")
    return {"ok": True, "message": result}


@router.get("/api/samba/raw")
async def samba_raw(user=Depends(verify_token)):
    return {"config": _run_args(["forgeos-samba", "raw-get"])}


@router.put("/api/samba/raw")
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
    _audit(user["sub"], "samba.config.update", "success", "Raw Samba config updated")
    return {"ok": True, "message": result.stdout.strip()}


@router.get("/api/samba/connections")
async def samba_connections(user=Depends(verify_token)):
    out = _run_args(["smbstatus"])
    return {"output": out or "No connections"}

