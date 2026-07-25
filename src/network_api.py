"""Network configuration API — interfaces, addressing, DNS, DDNS, routes.

READ LAYER + VALIDATED MODELS (patch 1 of the Network page build).

This module exposes the current network state (interfaces, DNS resolvers,
static routes) and defines the strictly-validated request models that the
later write patches will consume. It writes NOTHING yet — every endpoint here
is a GET. The write paths (interface addressing, global DNS/hostname, DDNS,
routes) land in subsequent patches behind an apply→confirm→auto-revert engine,
because this host uses ifupdown (no `netplan try` to lean on) and the primary
interface is the one the web UI runs on — a bad address change would drop a
headless box off the network.

Backend facts this module is built against (verified on the target VM):
  • ifupdown: `networking` service active; netplan absent; NetworkManager off.
  • config: /etc/network/interfaces with `source /etc/network/interfaces.d/*`.
  • DNS: plain static /etc/resolv.conf (not a symlink); systemd-resolved off.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# ── injected helpers (wired from the main module via set_helpers) ──
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None
_conf_get: Optional[Callable[[str, str], str]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
    conf: Callable[[str, str], str],
) -> None:
    """Wire shared helpers from the main module (mirrors system_api)."""
    global _run_args, _audit, _conf_get
    _run_args = run_args
    _audit = audit
    _conf_get = conf


# ── paths (module-level so tests can redirect them off the real /etc) ──
RESOLV_CONF = Path("/etc/resolv.conf")
INTERFACES_D = Path("/etc/network/interfaces.d")

# Loopback and virtual bridges we don't surface as configurable NICs.
_HIDE_IFACE_RE = re.compile(r"^(lo|docker\d+|br-[0-9a-f]+|veth|virbr|wg\d+)")


# ════════════════════════════════════════════════════════════════════
# VALIDATED MODELS  (used by the write patches; defined here so the
# validation rules live with the read layer and can be unit-tested now)
# ════════════════════════════════════════════════════════════════════
class InterfaceConfig(BaseModel):
    """Per-interface addressing. Simple by design: IPv4/IPv6, DHCP/static, MTU
    (no VLAN/bonding/802.1X in v1)."""
    name: str = Field(..., min_length=1, max_length=15)
    method: str = Field(...)                       # "dhcp" | "static"
    address: Optional[str] = None                  # CIDR, e.g. 10.0.0.69/24
    gateway: Optional[str] = None
    dns: list[str] = Field(default_factory=list)
    mtu: int = Field(default=1500, ge=576, le=9000)

    @field_validator("name")
    @classmethod
    def _iface_name(cls, v: str) -> str:
        # Linux iface names: no whitespace, slash, or shell metacharacters.
        if not re.fullmatch(r"[A-Za-z0-9@._-]+", v):
            raise ValueError("invalid interface name")
        return v

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ("dhcp", "static"):
            raise ValueError("method must be 'dhcp' or 'static'")
        return v

    @field_validator("address")
    @classmethod
    def _address(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            # interface form (accepts host bits) — this is an address on a NIC
            ipaddress.ip_interface(v)
        except ValueError:
            raise ValueError(f"invalid IP/CIDR: {v}")
        return v

    @field_validator("gateway")
    @classmethod
    def _gateway(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"invalid gateway address: {v}")
        return v

    @field_validator("dns")
    @classmethod
    def _dns(cls, v: list[str]) -> list[str]:
        for s in v:
            try:
                ipaddress.ip_address(s)
            except ValueError:
                raise ValueError(f"invalid DNS server: {s}")
        return v

    def model_post_init(self, __context: Any) -> None:
        # static requires an address; a static gateway must be a plain host IP
        # on the same subnet as the address (catches fat-finger gateways that
        # would blackhole the box).
        if self.method == "static":
            if not self.address:
                raise ValueError("static addressing requires an address")
            if self.gateway:
                net = ipaddress.ip_interface(self.address).network
                if ipaddress.ip_address(self.gateway) not in net:
                    raise ValueError("gateway is not on the interface's subnet")


class GlobalNetConfig(BaseModel):
    """System-wide identity + resolvers (not tied to one interface)."""
    hostname: str = Field(..., min_length=1, max_length=63)
    domain: str = Field(default="", max_length=253)
    dns: list[str] = Field(default_factory=list)
    gateway: Optional[str] = None
    proxy: str = Field(default="", max_length=253)

    @field_validator("hostname")
    @classmethod
    def _hostname(cls, v: str) -> str:
        # RFC 1123 label: letters/digits/hyphen, not starting/ending with hyphen
        if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", v):
            raise ValueError("invalid hostname")
        return v

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        if v == "":
            return v
        if not re.fullmatch(r"[A-Za-z0-9.-]+", v) or ".." in v:
            raise ValueError("invalid domain")
        return v

    @field_validator("dns")
    @classmethod
    def _dns(cls, v: list[str]) -> list[str]:
        for s in v:
            try:
                ipaddress.ip_address(s)
            except ValueError:
                raise ValueError(f"invalid DNS server: {s}")
        return v

    @field_validator("gateway")
    @classmethod
    def _gateway(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"invalid gateway address: {v}")
        return v


class DdnsConfig(BaseModel):
    """DDNS settings. `credentials` is write-only — it is never echoed back."""
    provider: str
    hostname: str = Field(..., min_length=1, max_length=253)
    enabled: bool = True
    interval_minutes: int = Field(default=5, ge=5, le=1440)
    credentials: dict = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _provider(cls, v: str) -> str:
        import ddns
        if v not in ddns.PROVIDERS:
            raise ValueError(f"provider must be one of {', '.join(ddns.PROVIDERS)}")
        return v

    @field_validator("hostname")
    @classmethod
    def _hostname(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v) or ".." in v:
            raise ValueError("invalid hostname")
        return v

    @field_validator("credentials")
    @classmethod
    def _creds(cls, v: dict) -> dict:
        # values land in URLs and auth headers — keep control characters out
        for k, val in v.items():
            if not isinstance(val, str):
                raise ValueError(f"credential {k} must be a string")
            if any(c in val for c in "\n\r\x00"):
                raise ValueError(f"credential {k} contains control characters")
        return v


class StaticRoute(BaseModel):
    destination: str                               # CIDR
    gateway: str
    interface: Optional[str] = None
    metric: int = Field(default=0, ge=0, le=2**31 - 1)

    @field_validator("destination")
    @classmethod
    def _dest(cls, v: str) -> str:
        try:
            ipaddress.ip_network(v, strict=False)   # a destination network
        except ValueError:
            raise ValueError(f"invalid destination network: {v}")
        return v

    @field_validator("gateway")
    @classmethod
    def _gw(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"invalid gateway address: {v}")
        return v

    @field_validator("interface")
    @classmethod
    def _iface(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if not re.fullmatch(r"[A-Za-z0-9@._-]+", v):
            raise ValueError("invalid interface name")
        return v


# ════════════════════════════════════════════════════════════════════
# READ HELPERS
# ════════════════════════════════════════════════════════════════════
def _ip_json(*args: str) -> list:
    """Run `ip -j <args>` and parse JSON; [] on any failure."""
    assert _run_args is not None
    out = _run_args(["ip", "-j", *args], timeout=5)
    if not out:
        return []
    try:
        data = json.loads(out)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _read_link_stats() -> dict[str, tuple[int, int]]:
    """Per-interface (rx_bytes, tx_bytes) from `ip -s -j link`.

    Statistics live on `ip -s link`, NOT on `ip addr` — the address dump omits
    stats64, so counters must be read separately and merged by ifname.
    """
    stats: dict[str, tuple[int, int]] = {}
    for iface in _ip_json("-s", "link", "show"):
        if not isinstance(iface, dict):
            continue
        name = iface.get("ifname", "")
        s = iface.get("stats64", {}) or {}
        rx = (s.get("rx", {}) or {}).get("bytes", 0)
        tx = (s.get("tx", {}) or {}).get("bytes", 0)
        if name:
            stats[name] = (rx, tx)
    return stats


def _read_interfaces() -> list[dict]:
    """Enumerate real NICs with address/link/counter detail."""
    ifaces: list[dict] = []
    link_stats = _read_link_stats()          # rx/tx come from `ip -s link`
    addr_data = _ip_json("addr", "show")
    for iface in addr_data:
        if not isinstance(iface, dict):
            continue
        name = iface.get("ifname", "")
        if not name or _HIDE_IFACE_RE.match(name):
            continue
        ipv4, ipv6 = [], []
        for a in iface.get("addr_info", []):
            if not isinstance(a, dict):
                continue
            fam, local, plen = a.get("family"), a.get("local"), a.get("prefixlen")
            if fam == "inet" and local:
                ipv4.append(f"{local}/{plen}" if plen is not None else local)
            elif fam == "inet6" and local and a.get("scope") != "link":
                ipv6.append(f"{local}/{plen}" if plen is not None else local)
        rx, tx = link_stats.get(name, (0, 0))
        ifaces.append({
            "name": name,
            "state": iface.get("operstate", "UNKNOWN"),
            "mac": iface.get("address", ""),
            "mtu": iface.get("mtu", 0),
            "ipv4": ipv4,
            "ipv6": ipv6,
            "rx_bytes": rx,
            "tx_bytes": tx,
        })
    return ifaces


def _read_dns() -> list[str]:
    """Nameservers from /etc/resolv.conf (this host resolves via the static file)."""
    servers: list[str] = []
    try:
        for line in RESOLV_CONF.read_text().splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2:
                    servers.append(parts[1])
    except OSError:
        pass
    return servers


def _read_routes() -> list[dict]:
    """Current routing table (default + static)."""
    routes: list[dict] = []
    for r in _ip_json("route", "show"):
        if not isinstance(r, dict):
            continue
        routes.append({
            "destination": r.get("dst", ""),
            "gateway": r.get("gateway", ""),
            "interface": r.get("dev", ""),
            "metric": r.get("metric", 0),
            "protocol": r.get("protocol", ""),
        })
    return routes


# ════════════════════════════════════════════════════════════════════
# READ ENDPOINTS
# ════════════════════════════════════════════════════════════════════
@router.get("/api/net/interfaces")
async def list_interfaces(user=Depends(verify_token)):
    """Full per-interface detail (addresses, link state, MAC, MTU, counters)."""
    return {"interfaces": _read_interfaces()}


@router.get("/api/net/global")
async def get_global(user=Depends(verify_token)):
    """System-wide network identity + resolvers."""
    assert _run_args is not None
    assert _conf_get is not None
    dns = _read_dns()
    # default gateway from the routing table
    gw = ""
    for r in _read_routes():
        if r["destination"] in ("default", "0.0.0.0/0") and r["gateway"]:
            gw = r["gateway"]
            break
    return {
        "hostname": _run_args(["hostname"]).strip() or "forgeos",
        "domain": _conf_get("DOMAIN", ""),
        "dns": dns,
        "gateway": gw,
        "proxy": _conf_get("HTTP_PROXY", ""),
    }


@router.get("/api/net/routes")
async def get_routes(user=Depends(verify_token)):
    """Current routing table."""
    return {"routes": _read_routes()}


@router.get("/api/net/routes/managed")
async def get_managed_routes(user=Depends(verify_token)):
    """Only the routes ForgeOS manages, flattened to a list with the interface
    on each. The live table (GET /api/net/routes) also lists kernel/DHCP routes
    ForgeOS doesn't own and must not offer to delete; the UI edits this set.
    """
    import net_networkd as ni
    flat = []
    for iface, routes in ni.load_managed_routes().items():
        for r in routes:
            flat.append({**r, "interface": iface})
    return {"routes": flat}


@router.post("/api/net/routes")
async def add_route(route: StaticRoute, user=Depends(verify_token)):
    """Add a managed static route. Applied directly — a bad route doesn't drop
    the box the way a bad address does, so no rollback timer.

    Routes attach to an interface (they're written into that interface's
    .network file so networkd can validate the gateway). If the caller doesn't
    name one, the primary/default-route interface is used.
    """
    _require_admin(user)
    import net_networkd as ni
    iface = route.interface or ni.default_route_iface()
    if not iface:
        raise HTTPException(status_code=400,
                            detail="no interface for the route and no default route found")
    store = ni.load_managed_routes()
    lst = [r for r in store.get(iface, []) if r["destination"] != route.destination]
    lst.append({"destination": route.destination, "gateway": route.gateway,
                "metric": route.metric})
    store[iface] = lst
    try:
        ni.apply_routes(store)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not apply route: {e}")
    if _audit is not None:
        _audit(user["sub"], "net.route.add", "success",
               f"{route.destination} via {route.gateway} on {iface}")
    return await get_managed_routes(user)


@router.delete("/api/net/routes")
async def delete_route(destination: str, user=Depends(verify_token)):
    """Remove a managed route by destination network (across all interfaces)."""
    _require_admin(user)
    import net_networkd as ni
    store = ni.load_managed_routes()
    found = False
    for iface in list(store.keys()):
        kept = [r for r in store[iface] if r["destination"] != destination]
        if len(kept) != len(store[iface]):
            found = True
        store[iface] = kept
    if not found:
        raise HTTPException(status_code=404, detail="no managed route for that destination")
    try:
        ni.apply_routes(store)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not apply: {e}")
    if _audit is not None:
        _audit(user["sub"], "net.route.delete", "success", destination)
    return await get_managed_routes(user)


@router.get("/api/net/ddns")
async def get_ddns(user=Depends(verify_token)):
    """DDNS status. Credentials are NEVER returned — only whether they're set."""
    import ddns
    return ddns.public_view(ddns.load())


@router.put("/api/net/ddns")
async def set_ddns(cfg: DdnsConfig, user=Depends(verify_token)):
    """Save DDNS settings. Credentials are stored at 0600 and never echoed.

    Omitting `credentials` keeps the ones already stored, so the UI can save
    a hostname or interval change without having to re-enter a token it was
    never allowed to read back.
    """
    _require_admin(user)
    import ddns
    existing = ddns.load()
    creds = cfg.credentials or existing.get("credentials") or {}
    stored = {
        "provider": cfg.provider,
        "hostname": cfg.hostname,
        "enabled": cfg.enabled,
        "interval_minutes": cfg.interval_minutes,
        "credentials": creds,
        # Saving new settings clears any parked state and forces the next tick
        # to run: the user is very likely fixing whatever caused a fatal, and a
        # stale last_status="fatal" / last_ip would keep the loop parked or make
        # it skip as "unchanged". Observed history (last_update text) is kept.
        "last_ip": "",
        "last_ts": 0,
        "last_status": "",
        "last_message": "",
        "last_update": existing.get("last_update", ""),
    }
    try:
        ddns.save(stored)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not save: {e}")
    if _audit is not None:
        _audit(user["sub"], "net.ddns.save", "success",
               f"{cfg.provider} {cfg.hostname}")
    return ddns.public_view(stored)


@router.delete("/api/net/ddns")
async def clear_ddns(user=Depends(verify_token)):
    """Remove the DDNS configuration and its stored credentials."""
    _require_admin(user)
    import ddns
    try:
        ddns.save({})
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not clear: {e}")
    if _audit is not None:
        _audit(user["sub"], "net.ddns.clear", "success", "")
    return {"ok": True}


@router.post("/api/net/ddns/test")
async def test_ddns(user=Depends(verify_token)):
    """Run one update now and report what the provider said.

    A real update attempt, not a dry run — reaching the provider with the
    stored credentials is the only thing that actually proves they work.
    The outcome is recorded so the UI can show it.
    """
    _require_admin(user)
    import ddns
    from datetime import datetime, timezone
    cfg = ddns.load()
    if not cfg.get("provider"):
        raise HTTPException(status_code=400, detail="No DDNS provider configured")
    ip = ddns.detect_public_ip()
    if not ip:
        raise HTTPException(status_code=502, detail="Could not determine the public IP")
    res = ddns.update(cfg, ip)
    cfg["last_status"] = res.status
    cfg["last_message"] = res.message
    cfg["last_update"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if res.success:
        cfg["last_ip"] = res.ip or ip
    try:
        ddns.save(cfg)
    except OSError:
        logger.warning("ddns: could not persist the test result")
    if _audit is not None:
        _audit(user["sub"], "net.ddns.test", res.status, res.code)
    return {"status": res.status, "code": res.code, "message": res.message,
            "ip": res.ip or ip, "success": res.success}


# ════════════════════════════════════════════════════════════════════
# WRITE ENDPOINTS  (admin-only)
#
# Interface changes go through the rollback engine (apply → 60s confirm →
# auto-revert) because they can drop the box off the network. Global changes
# (hostname/DNS) are applied directly — they don't drop the IP session.
# ════════════════════════════════════════════════════════════════════
def _require_admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")


@router.put("/api/net/interface/{name}")
async def set_interface(name: str, cfg: InterfaceConfig, user=Depends(verify_token)):
    """Apply an interface's addressing behind the rollback safeguard.

    Returns a confirm token + window. The client MUST call /api/net/confirm
    with the token from the NEW address within the window, or the change is
    automatically reverted (so a bad address can't lock you out).
    """
    _require_admin(user)
    if cfg.name != name:
        raise HTTPException(status_code=400, detail="interface name mismatch")
    import net_networkd as ni
    label = (f"{cfg.name} → {cfg.method}"
             + (f" {cfg.address}" if cfg.method == "static" else ""))
    try:
        res = ni.engine.apply({"cfg": cfg}, label)
    except Exception as e:
        # RollbackError (already-pending / apply-failed-and-restored) → 409
        raise HTTPException(status_code=409, detail=str(e))
    if _audit is not None:
        _audit(user["sub"], "net.interface.apply", "pending", label)
    return res


@router.post("/api/net/confirm")
async def confirm_change(body: dict, user=Depends(verify_token)):
    """Confirm a pending interface change (cancels the auto-revert)."""
    _require_admin(user)
    import net_networkd as ni
    token = str(body.get("token", ""))
    try:
        res = ni.engine.confirm(token)
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    if _audit is not None:
        _audit(user["sub"], "net.interface.confirm", "success", res.get("label", ""))
    return res


@router.post("/api/net/cancel")
async def cancel_change(user=Depends(verify_token)):
    """Immediately revert the pending interface change (discard)."""
    _require_admin(user)
    import net_networkd as ni
    try:
        res = ni.engine.cancel()
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    if _audit is not None:
        _audit(user["sub"], "net.interface.cancel", "success", res.get("label", ""))
    return res


@router.get("/api/net/pending")
async def pending_change(user=Depends(verify_token)):
    """Status of any pending interface change (for the confirm countdown UI).

    Includes the confirm token. An address change moves the box to a new
    origin, where localStorage — and therefore the token the browser held —
    is gone; the admin has to reconnect and sign in at the new address, and
    the UI needs a way to DISCOVER the pending change there. Confirming is
    already admin-only, so handing an admin the token over an authenticated
    request is the intended flow, not a downgrade: the token exists to stop a
    stale confirm validating a NEWER change, not to be a secret.
    """
    _require_admin(user)
    import net_networkd as ni
    st = ni.engine.status()
    if st.get("pending"):
        st["token"] = ni.engine.pending_token()
    return st


@router.put("/api/net/global")
async def set_global(cfg: GlobalNetConfig, user=Depends(verify_token)):
    """Apply hostname + DNS directly (low-risk — no rollback timer)."""
    _require_admin(user)
    import net_networkd as ni
    try:
        ni.apply_global(cfg.hostname, cfg.dns, cfg.domain)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to apply: {e}")
    if _audit is not None:
        _audit(user["sub"], "net.global.apply", "success",
               f"hostname={cfg.hostname} dns={','.join(cfg.dns)}")
    return {"ok": True}
