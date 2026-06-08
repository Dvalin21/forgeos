"""ForgeOS — WireGuard VPN API surface (LTH-001).

Mounts under the existing FastAPI app via:

    from vpn_api import router as vpn_router, set_helpers as set_vpn_helpers
    set_vpn_helpers(run_args=_run_args, audit=_audit)
    app.include_router(vpn_router)

Routes (/api/vpn/*):
  GET    /api/vpn/status              server + interface status
  GET    /api/vpn/peers               structured peer list (+ live handshake)
  POST   /api/vpn/peers               add a peer            (admin)
  DELETE /api/vpn/peers/{name}        remove a peer         (admin)
  GET    /api/vpn/peers/{name}/config download the .conf    (admin)
  GET    /api/vpn/peers/{name}/qr     QR code (PNG)         (admin)
  POST   /api/vpn/control/{action}    start|stop|restart    (admin)

Design: this module is a thin wrapper over the `forgeos-vpn` CLI that the
installer (install/modules/11-vpn.sh) places at /usr/local/bin/forgeos-vpn.
The CLI owns the WireGuard logic (key generation, IP allocation, server
config mutation, hot-reload). Reimplementing that here would create two
sources of truth that could drift. We read structured peer metadata
directly from the peers directory because the CLI's `list` output is
human-formatted text, unsuitable for an API.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Where the installer stores per-peer metadata and configs.
PEERS_DIR = Path("/etc/forgeos/vpn/peers")
WG_INTERFACE = "wg0"

# Peer names must be safe to use as a directory name and a CLI argument.
# The installer keys peers by name under PEERS_DIR/<name>/, so we constrain
# to a conservative charset and reject anything else up front.
_PEER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

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


def _require_admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


def _validate_peer_name(name: str) -> str:
    """Reject anything that isn't a safe peer name before it reaches the CLI."""
    if not _PEER_NAME_RE.match(name):
        raise HTTPException(
            400,
            "Invalid peer name. Use 1-32 chars: letters, digits, hyphen, "
            "underscore; must start with a letter or digit.",
        )
    return name


def _run_checked(args: list[str], timeout: int = 15) -> str:
    """Run a mutating command and FAIL LOUDLY on nonzero exit.

    _run_args (the injected helper) swallows errors and returns "" — fine
    for reads, dangerous for mutations because the API would report success
    when nothing happened. Mutations use this instead.
    """
    try:
        proc = subprocess.run(
            args, shell=False, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"Command timed out: {' '.join(args[:2])}")
    except FileNotFoundError:
        raise HTTPException(
            503,
            "forgeos-vpn CLI not found. Is the WireGuard installer module "
            "(11-vpn.sh) installed on this system?",
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "command failed").strip()
        raise HTTPException(400, detail[:300])
    return proc.stdout.strip()


def _read_peer_meta(name: str) -> dict:
    """Read a peer's meta.json, returning {} if absent/unreadable."""
    meta_file = PEERS_DIR / name / "meta.json"
    try:
        return json.loads(meta_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _live_handshakes() -> dict[str, str]:
    """Map peer public key -> latest handshake string, from `wg show`.

    Returns {} if wg isn't running or readable.
    """
    assert _run_args is not None
    out = _run_args(["wg", "show", WG_INTERFACE, "latest-handshakes"])
    handshakes: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            pubkey, epoch = parts
            handshakes[pubkey] = epoch
    return handshakes


@router.get("/api/vpn/status")
async def vpn_status(user=Depends(verify_token)):
    """Server + interface status. Read-only, any authenticated user."""
    assert _run_args is not None
    raw = _run_args(["forgeos-vpn", "status"])
    running = bool(raw) and "not running" not in raw.lower()
    return {"running": running, "interface": WG_INTERFACE, "raw": raw}


@router.get("/api/vpn/peers")
async def list_peers(user=Depends(verify_token)):
    """Structured peer list with live handshake status.

    Reads meta.json per peer (authoritative for name/ip/created/allowed_ips)
    and overlays live handshake state from `wg show`.
    """
    handshakes = _live_handshakes()
    peers = []
    if PEERS_DIR.is_dir():
        for peer_dir in sorted(PEERS_DIR.iterdir()):
            if not peer_dir.is_dir():
                continue
            name = peer_dir.name
            meta = _read_peer_meta(name)
            pub = ""
            try:
                pub = (peer_dir / "public.key").read_text().strip()
            except OSError:
                pass
            hs = handshakes.get(pub, "0")
            peers.append({
                "name": meta.get("name", name),
                "ip": meta.get("ip", "—"),
                "created": meta.get("created", ""),
                "allowed_ips": meta.get("allowed_ips", ""),
                "online": hs not in ("", "0"),
                "last_handshake_epoch": int(hs) if hs.isdigit() else 0,
            })
    return {"peers": peers, "count": len(peers)}


@router.post("/api/vpn/peers")
async def add_peer(body: dict, user=Depends(verify_token)):
    """Add a WireGuard peer. Admin only.

    Body: {"name": str (required),
           "dns": str (optional, default 1.1.1.1),
           "allowed_ips": str (optional, default 0.0.0.0/0)}
    """
    _require_admin(user)
    name = _validate_peer_name(str(body.get("name", "")).strip())

    if (PEERS_DIR / name).exists():
        raise HTTPException(409, f"Peer '{name}' already exists")

    dns = str(body.get("dns", "1.1.1.1")).strip() or "1.1.1.1"
    allowed_ips = str(body.get("allowed_ips", "0.0.0.0/0")).strip() or "0.0.0.0/0"

    # Basic shape checks — the CLI ultimately validates, but reject obvious junk.
    if not re.match(r"^[0-9.,:/ a-fA-F]+$", dns):
        raise HTTPException(400, "Invalid dns value")
    if not re.match(r"^[0-9.,:/ a-fA-F]+$", allowed_ips):
        raise HTTPException(400, "Invalid allowed_ips value")

    out = _run_checked(["forgeos-vpn", "add", name, dns, allowed_ips])
    assert _audit is not None
    _audit(user["sub"], "vpn.peer.add", "success", f"Peer '{name}' ({allowed_ips})")
    return {"ok": True, "name": name, "message": out}


@router.delete("/api/vpn/peers/{name}")
async def remove_peer(name: str, user=Depends(verify_token)):
    """Remove a WireGuard peer. Admin only."""
    _require_admin(user)
    name = _validate_peer_name(name)
    if not (PEERS_DIR / name).exists():
        raise HTTPException(404, f"Peer '{name}' not found")
    out = _run_checked(["forgeos-vpn", "remove", name])
    assert _audit is not None
    _audit(user["sub"], "vpn.peer.remove", "success", f"Peer '{name}' removed")
    return {"ok": True, "name": name, "message": out}


@router.get("/api/vpn/peers/{name}/config", response_class=PlainTextResponse)
async def peer_config(name: str, user=Depends(verify_token)):
    """Return the peer's WireGuard .conf as text. Admin only (contains keys)."""
    _require_admin(user)
    name = _validate_peer_name(name)
    conf = PEERS_DIR / name / f"{name}.conf"
    try:
        return PlainTextResponse(conf.read_text())
    except OSError:
        raise HTTPException(404, f"Config for peer '{name}' not found")


@router.get("/api/vpn/peers/{name}/qr")
async def peer_qr(name: str, user=Depends(verify_token)):
    """Return a PNG QR code of the peer config. Admin only.

    Uses qrencode (installed by 11-vpn.sh) to render the .conf as a PNG.
    """
    _require_admin(user)
    name = _validate_peer_name(name)
    conf = PEERS_DIR / name / f"{name}.conf"
    if not conf.is_file():
        raise HTTPException(404, f"Config for peer '{name}' not found")
    try:
        proc = subprocess.run(
            ["qrencode", "-t", "PNG", "-o", "-", "-r", str(conf)],
            capture_output=True, timeout=10,
        )
    except FileNotFoundError:
        raise HTTPException(503, "qrencode not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "qrencode timed out")
    if proc.returncode != 0:
        raise HTTPException(500, "Failed to generate QR code")
    return Response(content=proc.stdout, media_type="image/png")


@router.post("/api/vpn/control/{action}")
async def vpn_control(action: str, user=Depends(verify_token)):
    """Start / stop / restart the WireGuard service. Admin only."""
    _require_admin(user)
    if action not in ("start", "stop", "restart"):
        raise HTTPException(400, "action must be start, stop, or restart")
    out = _run_checked(["forgeos-vpn", action])
    assert _audit is not None
    _audit(user["sub"], f"vpn.{action}", "success", f"WireGuard {action}")
    return {"ok": True, "action": action, "message": out}
