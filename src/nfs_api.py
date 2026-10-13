"""ForgeOS — NFS API surface.

NFS existed as a config model (NfsConfig) and a generator
(generators/nfs.py) but had NO endpoint anywhere, so it could not be
configured or enabled through ForgeOS at all — the generator was dead code
reachable only by hand-editing /etc/forgeos/config.json.

Mounts under the existing FastAPI app via:

    from nfs_api import router as nfs_router, set_helpers as set_nfs_helpers
    set_nfs_helpers(audit=_audit)
    app.include_router(nfs_router)

Routes (/api/nfs/*):
  • GET  /api/nfs            — current exports + resolved state
  • POST /api/nfs            — add an export        (admin)
  • PUT  /api/nfs            — replace the whole set (admin)
  • POST /api/nfs/toggle     — enable/disable       (admin)
  • DELETE /api/nfs/{index}  — remove one by index  (admin)

Deliberately mirrors samba_api's shape: the config-DB is saved, then the
generator renders /etc/exports.d/forgeos.exports and runs `exportfs -ra`.
One source of truth, one path to apply it, the same as every other service.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token
import forgeos_config as fc
from generators import GeneratorError, registry

logger = logging.getLogger("forgeos-api")

router = APIRouter()

_audit: Optional[Callable[..., None]] = None


def set_helpers(audit: Callable[..., None]) -> None:
    global _audit
    _audit = audit


# Save + regenerate + reload, overridable in tests so they touch neither
# /etc nor exportfs. Same seam samba_api uses.
_apply = None


def _apply_nfs(cfg) -> None:
    """Save, then render + reload. Raises on failure.

    registry.apply_one() deliberately NEVER raises — it returns an
    ApplyResult(ok=False, error=...). Checking only for GeneratorError and
    ignoring the result made every write failure look like a success: the API
    answered 200 while the file never existed. The result must be inspected.
    """
    if _apply is not None:
        _apply(cfg)
        return
    fc.save(cfg)
    res = registry.apply_one("nfs", cfg=cfg)
    if not res.ok:
        raise GeneratorError(res.error or "NFS apply failed")


def set_apply(fn) -> None:
    """Test seam: inject a fake apply (save + generate + reload)."""
    global _apply
    _apply = fn


def _view(cfg) -> dict:
    nfs = cfg.nfs
    return {
        "enabled": nfs.enabled,
        "nas_root": nfs.nas_root,
        "lan_cidr": nfs.lan_cidr,
        "exports": [
            {"index": i, "path": e.path, "type": e.type}
            for i, e in enumerate(nfs.exports)
        ],
    }


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


def _check_dir(path: str) -> None:
    """Reject an export whose folder isn't there.

    exportfs silently drops an entry whose path doesn't exist ('Failed to
    stat'), and the generator reloads with check=False, so the API used to
    answer 'applied' while the folder was never actually shared. Catching it
    here turns a silent no-op into a message the user can act on.
    """
    if not Path(path).is_dir():
        raise HTTPException(400, f"That folder doesn't exist on this NAS yet: {path}")


@router.get("/api/nfs")
async def get_nfs(user=Depends(verify_token)):
    """Current NFS configuration. Any authenticated user may read it - it
    describes which folders this box offers to the LAN, which is exactly the
    sort of thing a user on the LAN can already see."""
    return _view(fc.load())


@router.post("/api/nfs")
async def add_export(body: dict, user=Depends(verify_token)):
    """Add one export. The path must be absolute; the type comes from the
    fixed set the generator knows how to render (rw/ro/public/backup) so a
    freeform option string can never reach /etc/exports."""
    _require_admin(user)
    cfg = fc.load()
    path = str(body.get("path", "")).strip()
    etype = str(body.get("type", "rw")).strip()
    if not path.startswith("/"):
        raise HTTPException(400, "Path must be absolute")
    try:
        export = fc.NfsExport(path=path, type=etype)
    except Exception as exc:                      # noqa: BLE001 - pydantic message is the useful part
        raise HTTPException(400, f"Bad export: {exc}")
    _check_dir(export.path)
    if any(e.path == export.path for e in cfg.nfs.exports):
        raise HTTPException(400, f"Already exported: {export.path}")
    cfg.nfs.exports.append(export)
    try:
        _apply_nfs(cfg)
    except GeneratorError as exc:
        raise HTTPException(500, f"Could not apply the NFS exports: {exc}")
    if _audit:
        _audit(user["sub"], "nfs.export.add", "success", f"{export.path} ({export.type})")
    return _view(cfg)


@router.put("/api/nfs")
async def replace_exports(body: dict, user=Depends(verify_token)):
    """Replace the whole export set in one shot (what the UI's list editor
    saves). Deliberately replace-and-apply rather than N sequential
    single-adds: one exportfs -ra, one audit row, no half-applied state if a
    later export fails validation."""
    _require_admin(user)
    cfg = fc.load()
    raw = body.get("exports")
    if not isinstance(raw, list):
        raise HTTPException(400, "exports must be a list")
    try:
        cfg.nfs.exports = [fc.NfsExport(path=str(x.get("path", "")).strip(),
                                        type=str(x.get("type", "rw")).strip())
                           for x in raw]
    except Exception as exc:                      # noqa: BLE001
        raise HTTPException(400, f"Bad export set: {exc}")
    for e in cfg.nfs.exports:
        _check_dir(e.path)
    if "lan_cidr" in body:
        cfg.nfs.lan_cidr = str(body["lan_cidr"]).strip()
    try:
        _apply_nfs(cfg)
    except GeneratorError as exc:
        raise HTTPException(500, f"Could not apply the NFS exports: {exc}")
    if _audit:
        _audit(user["sub"], "nfs.export.replace", "success",
               f"{len(cfg.nfs.exports)} export(s)")
    return _view(cfg)


@router.post("/api/nfs/toggle")
async def toggle_nfs(body: dict, user=Depends(verify_token)):
    _require_admin(user)
    cfg = fc.load()
    cfg.nfs.enabled = bool(body.get("enabled", not cfg.nfs.enabled))
    try:
        _apply_nfs(cfg)
    except GeneratorError as exc:
        raise HTTPException(500, f"Could not apply the NFS exports: {exc}")
    if _audit:
        _audit(user["sub"], "nfs.toggle", "success", f"enabled={cfg.nfs.enabled}")
    return _view(cfg)


@router.delete("/api/nfs/{index}")
async def delete_export(index: int, user=Depends(verify_token)):
    """Remove by position. Exports are an ordered list in the config-DB, and
    their rendered order in /etc/exports is meaningful to the client, so
    there is no stable id to address them by - same pattern the firewall rules
    already use."""
    _require_admin(user)
    cfg = fc.load()
    if index < 0 or index >= len(cfg.nfs.exports):
        raise HTTPException(404, f"No export at position {index}")
    removed = cfg.nfs.exports.pop(index)
    try:
        _apply_nfs(cfg)
    except GeneratorError as exc:
        raise HTTPException(500, f"Could not apply the NFS exports: {exc}")
    if _audit:
        _audit(user["sub"], "nfs.export.delete", "success", removed.path)
    return _view(cfg)