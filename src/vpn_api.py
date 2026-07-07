"""ForgeOS — WireGuard VPN API (v2, config-DB backed).

Peers live in cfg.wireguard.peers[] (config-DB); the wireguard generator
renders /etc/wireguard/wg0.conf from that list and reloads. This replaces the
legacy forgeos-vpn bash CLI (deleted v1 installer), which is not present
on v2 and was the "CLI not installed" failure.

Client private keys are RETURN-ONCE: generated at add-peer, embedded in the
client .conf returned in that one response, never persisted. The server config
only ever stores peer PUBLIC keys. Consequence: no QR/config regeneration later
— the client is shown its config exactly once, at creation.
"""
from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import forgeos_config as fc
from forgeos_auth import verify_token
from generators import registry
from generators.wireguard import WireGuardGenerator

router = APIRouter()

_audit: Optional[Callable[..., None]] = None
_apply = None  # test seam


def set_helpers(run_args: Callable[..., str] = None, audit: Callable[..., None] = None) -> None:
    global _audit
    _audit = audit


def set_apply(fn) -> None:
    global _apply
    _apply = fn


def _admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


def _apply_wg(cfg) -> None:
    if _apply is not None:
        _apply(cfg)
        return
    res = registry.apply_one("wireguard", cfg=cfg)
    if not res.ok:
        raise HTTPException(500, f"wireguard apply failed: {res.error}")
    # Converge ufw too: the listen-port guard must open/close with VPN state.
    # Full reset+rebuild is idempotent; a failure here is a real firewall
    # problem and must surface, not be swallowed.
    res = registry.apply_one("ufw", cfg=cfg)
    if not res.ok:
        raise HTTPException(500, f"ufw apply failed: {res.error}")
    fc.save(cfg)


def _wg_dump(interface: str) -> dict:
    """pubkey -> {endpoint, handshake, rx, tx}, live from `wg show dump`.
    Empty if the interface is down. Line 1 is the interface itself; peer
    lines are: pubkey psk endpoint allowed-ips handshake rx tx keepalive."""
    try:
        out = subprocess.run(["wg", "show", interface, "dump"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    peers = {}
    for line in out.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 7:
            continue
        peers[f[0]] = {
            "endpoint": "" if f[2] == "(none)" else f[2],
            "handshake": int(f[4]) if f[4].isdigit() else 0,
            "rx": int(f[5]) if f[5].isdigit() else 0,
            "tx": int(f[6]) if f[6].isdigit() else 0,
        }
    return peers


def _detect_ips() -> dict:
    """Best-effort LAN + public IP for the endpoint field. Both nullable —
    detection is a convenience, never a dependency."""
    lan = pub = None
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("9.9.9.9", 53))            # no packet sent; routes only
        lan = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    try:
        from urllib.request import urlopen
        raw = urlopen("https://checkip.amazonaws.com", timeout=5).read()
        cand = raw.decode("ascii", "replace").strip()
        ipaddress.ip_address(cand)            # trust boundary: must parse as IP
        pub = cand
    except (OSError, ValueError):
        pass
    return {"lan_ip": lan, "public_ip": pub}


def _next_ip(cfg) -> str:
    """Lowest free /32 in the subnet, skipping the server address."""
    net = ipaddress.ip_network(cfg.wireguard.subnet, strict=False)
    taken = {ipaddress.ip_address(cfg.wireguard.server_address)}
    for p in cfg.wireguard.peers:
        taken.add(ipaddress.ip_address(p.address.split("/")[0]))
    for host in net.hosts():
        if host not in taken:
            return str(host)
    raise HTTPException(507, "subnet exhausted — no free address")


@router.get("/api/vpn/status")
async def vpn_status(user=Depends(verify_token)):
    wg = fc.load().wireguard
    up = False
    try:
        r = subprocess.run(["wg", "show", wg.interface], capture_output=True, timeout=5)
        up = r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        fwd = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip() == "1"
    except OSError:
        fwd = None
    try:
        from generators.wireguard import resolve_egress_nic
        nic = resolve_egress_nic(wg)
        nic_ok = True
    except Exception as e:
        nic, nic_ok = str(e), False
    return {"running": up, "interface": wg.interface, "enabled": wg.enabled,
            "listen_port": wg.listen_port, "peer_count": len(wg.peers),
            "endpoint": wg.endpoint, "ip_forward": fwd,
            "egress_nic": nic, "egress_nic_ok": nic_ok}


@router.get("/api/vpn/settings")
async def get_settings(user=Depends(verify_token)):
    wg = fc.load().wireguard
    return {"endpoint": wg.endpoint, "listen_port": wg.listen_port,
            "subnet": wg.subnet}


@router.put("/api/vpn/settings")
async def put_settings(body: dict, user=Depends(verify_token)):
    """Only `endpoint` is settable here — it is client-conf-only, so no
    generator re-render is needed, just persist."""
    _admin(user)
    cfg = fc.load()
    try:
        # No validate_assignment in this codebase — construct a throwaway
        # model so the endpoint validator actually runs.
        validated = fc.WireGuardConfig(endpoint=str(body.get("endpoint", "")).strip()).endpoint
    except ValueError as e:
        raise HTTPException(400, f"invalid endpoint: {e}")
    cfg.wireguard.endpoint = validated
    fc.save(cfg)
    assert _audit is not None
    _audit(user["sub"], "vpn.settings", "success", f"endpoint '{cfg.wireguard.endpoint}'")
    return {"ok": True, "endpoint": cfg.wireguard.endpoint}


@router.get("/api/vpn/detect-endpoint")
async def detect_endpoint(user=Depends(verify_token)):
    _admin(user)
    return _detect_ips()


@router.get("/api/vpn/peers")
async def list_peers(user=Depends(verify_token)):
    wg = fc.load().wireguard
    live = _wg_dump(wg.interface)
    peers = []
    for p in wg.peers:
        d = live.get(p.public_key, {})
        epoch = d.get("handshake", 0)
        peers.append({"name": p.name, "address": p.address,
                      "online": epoch > 0,
                      "last_handshake_epoch": epoch,
                      "remote": d.get("endpoint", ""),
                      "rx_bytes": d.get("rx", 0),
                      "tx_bytes": d.get("tx", 0)})
    return {"peers": peers, "count": len(peers)}


@router.post("/api/vpn/peers")
async def add_peer(body: dict, user=Depends(verify_token)):
    """Create a peer. Returns the client .conf ONCE (private key never stored)."""
    _admin(user)
    cfg = fc.load()
    name = str(body.get("name", "")).strip()
    try:
        # model validator enforces charset + uniqueness on assignment below
        if any(p.name.lower() == name.lower() for p in cfg.wireguard.peers):
            raise HTTPException(409, f"peer '{name}' already exists")
        endpoint = str(body.get("endpoint", "")).strip() or cfg.wireguard.endpoint
        if not endpoint:
            raise HTTPException(400, "Server endpoint not set. Use Detect on the "
                                     "VPN page (or enter your public IP/hostname) "
                                     "before adding devices.")
        dns = str(body.get("dns", "1.1.1.1")).strip() or "1.1.1.1"
        allowed = str(body.get("allowed_ips", "0.0.0.0/0")).strip() or "0.0.0.0/0"
        for val in (dns, allowed):
            for token in val.replace(" ", "").split(","):
                ipaddress.ip_network(token, strict=False) if "/" in token else ipaddress.ip_address(token)

        gen = WireGuardGenerator()
        server_pub = gen.ensure_server_key()
        client_priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout.strip()
        client_pub = subprocess.run(["wg", "pubkey"], input=client_priv, capture_output=True, text=True, check=True).stdout.strip()
        addr = _next_ip(cfg)

        cfg.wireguard.peers.append(fc.WireGuardPeer(
            name=name, public_key=client_pub, address=addr + "/32"))
    except ValueError as e:
        raise HTTPException(400, detail=f"invalid peer: {e}")

    _apply_wg(cfg)  # re-render server conf + reload

    client_conf = (
        f"[Interface]\n"
        f"PrivateKey = {client_priv}\n"
        f"Address = {addr}/32\n"
        f"DNS = {dns}\n\n"
        f"[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"AllowedIPs = {allowed}\n"
        f"Endpoint = {endpoint}:{cfg.wireguard.listen_port}\n"
        f"PersistentKeepalive = 25\n"
    )
    qr_png = None
    try:
        r = subprocess.run(["qrencode", "-t", "PNG", "-o", "-"], input=client_conf.encode(),
                          capture_output=True, timeout=10)
        if r.returncode == 0:
            import base64
            qr_png = "data:image/png;base64," + base64.b64encode(r.stdout).decode()
    except (OSError, subprocess.SubprocessError):
        pass

    assert _audit is not None
    _audit(user["sub"], "vpn.peer.add", "success", f"peer '{name}' ({addr})")
    return {"ok": True, "name": name, "address": addr + "/32",
            "config": client_conf, "qr": qr_png,
            "warning": "Save this now — the private key is shown only once."}


@router.delete("/api/vpn/peers/{name}")
async def remove_peer(name: str, user=Depends(verify_token)):
    _admin(user)
    cfg = fc.load()
    before = len(cfg.wireguard.peers)
    cfg.wireguard.peers = [p for p in cfg.wireguard.peers if p.name != name]
    if len(cfg.wireguard.peers) == before:
        raise HTTPException(404, f"peer '{name}' not found")
    _apply_wg(cfg)
    assert _audit is not None
    _audit(user["sub"], "vpn.peer.remove", "success", f"peer '{name}'")
    return {"ok": True, "name": name}


@router.post("/api/vpn/control/{action}")
async def vpn_control(action: str, user=Depends(verify_token)):
    _admin(user)
    if action not in ("start", "stop", "restart"):
        raise HTTPException(400, "action must be start, stop, or restart")
    wg = fc.load().wireguard
    unit = f"wg-quick@{wg.interface}"
    verb = {"start": "start", "stop": "stop", "restart": "restart"}[action]
    try:
        r = subprocess.run(["systemctl", verb, unit], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(500, f"{action} failed: {e}")
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or f"{action} failed")
    assert _audit is not None
    _audit(user["sub"], f"vpn.{action}", "success", f"WireGuard {action}")
    return {"ok": True, "action": action}
