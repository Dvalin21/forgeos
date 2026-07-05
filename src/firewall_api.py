"""Firewall API (v2) — config-DB backed, ufw-generator applied.

Same paths and response shapes as the legacy pages_api endpoints (frontend
unchanged), but the source of truth is now cfg.firewall: rules survive backup/
restore, are reproducible, and never regex-scraped from `ufw status`.
"""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

import forgeos_config as fc
from forgeos_auth import verify_token
from generators import registry

router = APIRouter()

_audit: Optional[Callable] = None


def set_helpers(audit: Callable) -> None:
    global _audit
    _audit = audit


# Save + converge. Overridable in tests so they never touch ufw.
_apply = None


def _apply_fw(cfg) -> None:
    if _apply is not None:
        _apply(cfg)
        return
    # Converge live ufw FIRST; persist only if it took. Otherwise a partial
    # converge (e.g. EROFS mid-sequence) leaves config-DB claiming state the
    # firewall rejected — DB and live silently diverge.
    res = registry.apply_one("ufw", cfg=cfg)
    if not res.ok:
        raise HTTPException(500, f"firewall apply failed: {res.error}")
    fc.save(cfg)


def set_apply(fn) -> None:
    global _apply
    _apply = fn


def _admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


FIREWALL_SERVICES = [
    {"id": "ssh",    "label": "SSH (remote shell)",      "port": "22/tcp"},
    {"id": "smb",    "label": "File sharing (SMB)",      "port": "445/tcp"},
    {"id": "nfs",    "label": "File sharing (NFS)",      "port": "2049/tcp"},
    {"id": "http",   "label": "Web (HTTP)",              "port": "80/tcp"},
    {"id": "https",  "label": "Web (HTTPS)",             "port": "443/tcp"},
    {"id": "wg",     "label": "VPN (WireGuard)",         "port": "51820/udp"},
    {"id": "dns",    "label": "DNS",                     "port": "53"},
    {"id": "custom", "label": "Custom port…",            "port": ""},
]


def _split_port(spec: str) -> tuple[str, str]:
    """'443/tcp' -> ('443','tcp'); '53' -> ('53','any') — legacy body format."""
    spec = str(spec).strip()
    if "/" in spec:
        port, proto = spec.rsplit("/", 1)
        return port.strip(), proto.strip().lower()
    return spec, "any"


def _rule_view(i: int, r: fc.FirewallRule) -> dict:
    to = r.port if r.proto == "any" else f"{r.port}/{r.proto}"
    return {"num": i + 1, "to": to, "from": r.from_ip, "action": r.action.upper(),
            "family": r.family, "comment": r.comment}


@router.get("/api/firewall/status")
async def firewall_status(user=Depends(verify_token)):
    fw = fc.load().firewall
    return {
        "active": fw.enabled,
        "defaults": {"incoming": fw.default_incoming, "outgoing": fw.default_outgoing},
        "logging": fw.logging,
        "rules": [_rule_view(i, r) for i, r in enumerate(fw.rules)],
    }


@router.get("/api/firewall/services")
async def firewall_services(user=Depends(verify_token)):
    return {"services": FIREWALL_SERVICES}


@router.post("/api/firewall/toggle")
async def firewall_toggle(body: dict, user=Depends(verify_token)):
    _admin(user)
    on = bool(body.get("enable", True))
    cfg = fc.load()
    cfg.firewall.enabled = on
    _apply_fw(cfg)
    assert _audit is not None
    _audit(user["sub"], "firewall.toggle", "success", "enabled" if on else "disabled")
    return {"ok": True, "active": on}


@router.post("/api/firewall/rule")
async def firewall_add_rule(body: dict, user=Depends(verify_token)):
    """Legacy body: action, port ('443/tcp'|'53'|'1000:2000/udp'),
    from ('any'|IP|CIDR), family (both|ipv4|ipv6), comment (new, optional)."""
    _admin(user)
    port, proto = _split_port(body.get("port", ""))
    try:
        rule = fc.FirewallRule(
            port=port, proto=proto,
            action=str(body.get("action", "allow")).lower(),
            from_ip=str(body.get("from", "any")),
            family=str(body.get("family", "both")),
            comment=str(body.get("comment", "")),
        )
    except (ValidationError, ValueError) as e:
        raise HTTPException(400, detail=f"invalid rule: {e}")
    cfg = fc.load()
    cfg.firewall.rules.append(rule)
    _apply_fw(cfg)
    assert _audit is not None
    _audit(user["sub"], "firewall.rule.add", "success",
           f"{rule.action} {rule.port}/{rule.proto} from {rule.from_ip}")
    return {"ok": True, "rule": _rule_view(len(cfg.firewall.rules) - 1, rule)}


@router.delete("/api/firewall/rule/{num}")
async def firewall_delete_rule(num: int, user=Depends(verify_token)):
    _admin(user)
    cfg = fc.load()
    if not (1 <= num <= len(cfg.firewall.rules)):
        raise HTTPException(404, detail=f"no rule #{num}")
    gone = cfg.firewall.rules.pop(num - 1)
    _apply_fw(cfg)
    assert _audit is not None
    _audit(user["sub"], "firewall.rule.delete", "success",
           f"#{num}: {gone.action} {gone.port}/{gone.proto}")
    return {"ok": True}


@router.put("/api/firewall/defaults")
async def firewall_defaults(body: dict, user=Depends(verify_token)):
    _admin(user)
    cfg = fc.load()
    changed = False
    for direction, attr in (("incoming", "default_incoming"), ("outgoing", "default_outgoing")):
        pol = body.get(direction)
        if pol is None:
            continue
        if pol not in ("allow", "deny", "reject"):
            raise HTTPException(400, detail=f"invalid policy for {direction}: {pol!r}")
        setattr(cfg.firewall, attr, pol)
        changed = True
    if changed:
        _apply_fw(cfg)
    assert _audit is not None
    _audit(user["sub"], "firewall.defaults", "success", str(body))
    return {"ok": True}
