"""ForgeOS — SAMBA API surface.

Mounts under the existing FastAPI app via:

    from samba_api import router as samba_router, set_helpers as set_samba_helpers
    set_samba_helpers(run_args=_run_args, audit=_audit)
    app.include_router(samba_router)

Routes (/api/samba/*): shares (CRUD), raw config (GET/PUT), connections
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from forgeos_auth import verify_token
import forgeos_config as fc
from pathlib import Path
from generators import GeneratorError, registry
from generators.samba import CUSTOM_FILE, SambaGenerator

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


# Save the config-DB then regenerate + reload Samba via the v2 generator.
# Overridable in tests so they don't write /etc or touch systemctl.
_apply = None


def _apply_samba(cfg) -> None:
    if _apply is not None:
        _apply(cfg)
        return
    fc.save(cfg)
    registry.apply_one("samba", cfg=cfg)


def set_apply(fn) -> None:
    """Test seam: inject a fake apply (save+generate+reload)."""
    global _apply
    _apply = fn


@router.get("/api/samba/shares")
async def samba_shares(user=Depends(verify_token)):
    # V2 engine: read shares from the config-DB, not a shelled-out CLI.
    cfg = fc.load()
    shares = [s.model_dump() for s in cfg.samba.shares]
    return {"shares": shares,
            "workgroup": cfg.samba.workgroup,
            "server_string": cfg.samba.server_string}


@router.post("/api/samba/share")
async def create_share(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    cfg = fc.load()
    try:
        share = fc.SambaShare(
            name=body["name"],
            path=body["path"],
            type=body.get("type", "standard"),
            writable=bool(body.get("writable", True)),
            valid_users=body.get("valid_users") or ["@users"],
            comment=body.get("comment", ""),
            browseable=bool(body.get("browseable", False)),
            guest_ok=bool(body.get("guest_ok", False)),
            hide_dot_files=bool(body.get("hide_dot_files", True)),
            recycle_bin=bool(body.get("recycle_bin", False)),
            force_user=body.get("force_user", ""),
            force_group=body.get("force_group", ""),
            permissions=body.get("permissions", "group"),
            write_list=body.get("write_list") or [],
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(400, detail=f"invalid share: {e}")

    # reject duplicate name (config validator also guards, but fail clearly)
    if any(s.name.lower() == share.name.lower() for s in cfg.samba.shares):
        raise HTTPException(409, detail=f"share '{share.name}' already exists")

    cfg.samba.shares.append(share)
    _apply_samba(cfg)
    _audit(user["sub"], "samba.share.create", "success",
           f"Share '{share.name}' at '{share.path}' "
           f"({'rw' if share.writable else 'ro'})")
    return {"ok": True, "share": share.model_dump()}


@router.put("/api/samba/share/{name}")
async def update_share(name: str, body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    cfg = fc.load()
    if not any(s.name.lower() == name.lower() for s in cfg.samba.shares):
        raise HTTPException(404, detail=f"share '{name}' not found")
    try:
        updated = fc.SambaShare(
            name=body.get("name", name),
            path=body["path"],
            type=body.get("type", "standard"),
            writable=bool(body.get("writable", True)),
            valid_users=body.get("valid_users") or ["@users"],
            comment=body.get("comment", ""),
            browseable=bool(body.get("browseable", False)),
            guest_ok=bool(body.get("guest_ok", False)),
            hide_dot_files=bool(body.get("hide_dot_files", True)),
            recycle_bin=bool(body.get("recycle_bin", False)),
            force_user=body.get("force_user", ""),
            force_group=body.get("force_group", ""),
            permissions=body.get("permissions", "group"),
            write_list=body.get("write_list") or [],
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(400, detail=f"invalid share: {e}")
    # a rename must not collide with a different existing share
    if updated.name.lower() != name.lower() and any(
        s.name.lower() == updated.name.lower() for s in cfg.samba.shares
    ):
        raise HTTPException(409, detail=f"share '{updated.name}' already exists")
    cfg.samba.shares = [
        updated if s.name.lower() == name.lower() else s for s in cfg.samba.shares
    ]
    _apply_samba(cfg)
    renamed = updated.name.lower() != name.lower()
    _audit(user["sub"], "samba.share.update", "success",
           f"Share '{name}' updated" + (f" (renamed to '{updated.name}')" if renamed else ""))
    return {"ok": True, "share": updated.model_dump()}


@router.delete("/api/samba/share/{name}")
async def remove_share(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    cfg = fc.load()
    before = len(cfg.samba.shares)
    cfg.samba.shares = [s for s in cfg.samba.shares if s.name.lower() != name.lower()]
    if len(cfg.samba.shares) == before:
        raise HTTPException(404, detail=f"share '{name}' not found")
    _apply_samba(cfg)
    _audit(user["sub"], "samba.share.delete", "success", f"Share '{name}' removed")
    return {"ok": True}


def _parse_smbstatus(out: str) -> list[dict]:
    """Structured client connections from smbstatus's share-connections
    section. Parsing lives HERE, tested, because the old contract shipped raw
    text and the dashboard's ad-hoc parse rendered the section HEADER as a
    fake client ("Service pid Machine Connected at...")."""
    conns: list[dict] = []
    in_section = False
    for line in (out or "").splitlines():
        ls = line.strip()
        if ls.startswith("Service") and "Machine" in ls:
            in_section = True                 # header row — not a client
            continue
        if in_section:
            if not ls or ls.startswith("-"):
                if conns or ls.startswith("-"):
                    # separator right under the header; blank line ends section
                    if not ls:
                        in_section = False
                continue
            parts = ls.split()
            if len(parts) >= 3 and parts[1].isdigit():
                conns.append({"share": parts[0], "pid": parts[1],
                              "machine": parts[2]})
    return conns


@router.get("/api/samba/connections")
async def samba_connections(user=Depends(verify_token)):
    out = _run_args(["smbstatus"])
    conns = _parse_smbstatus(out)
    return {"connections": conns, "count": len(conns),
            "output": out or "No connections"}   # raw kept for the shares page


@router.get("/api/samba/config")
async def samba_get_custom(user=Depends(verify_token)):
    """Raw user-managed custom SMB directives (the include the generator never
    overwrites). Empty string until the user writes something."""
    p = Path(CUSTOM_FILE)
    return {"config": p.read_text() if p.exists() else "", "path": str(CUSTOM_FILE)}


@router.put("/api/samba/config")
async def samba_save_custom(body: dict, user=Depends(verify_token)):
    """testparm the managed config + proposed custom directives, then write the
    custom include and reload smbd. Invalid config is refused (never persisted)."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    text = body.get("config", "")
    if not isinstance(text, str):
        raise HTTPException(400, detail="config must be a string")
    cfg = fc.load()
    try:
        SambaGenerator().validate_custom(cfg, text)
    except GeneratorError as e:
        raise HTTPException(400, detail={"error": "Config test failed", "output": str(e)})
    p = Path(CUSTOM_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    # Regenerate the managed config too: this guarantees smb.conf carries the
    # `include = <custom>` line (so the directives actually take effect, even on
    # a fresh box where no share has been created yet) and reloads smbd.
    _apply_samba(cfg)
    _audit(user["sub"], "samba.config.update", "success",
           f"Raw custom SMB config updated ({len(text)} bytes) & reloaded")
    return {"ok": True}

