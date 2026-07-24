"""systemd-networkd write backend for the Network page.

Replaces the ifupdown backend. networkd is the chosen stack for the ForgeOS
ISO: built into systemd, declarative .network files, per-interface
`networkctl reconfigure` — no external DHCP client (dhcpcd/dhclient) to fight,
no ifdown/ifup teardown races, no main-file stanza dedup.

Exposes the SAME interface the API layer expects from the ifupdown backend:
  • engine        — the RollbackEngine (interface changes: apply→60s→revert)
  • set_runner()  — inject the shared command runner
  • apply_global()— hostname + DNS, applied directly (no rollback timer)

Why interface changes need the rollback timer: reconfiguring the NIC the web
UI answers on can drop a headless box off the network. Global changes
(hostname/DNS) don't drop the IP session, so they apply directly.

Config model:
  /etc/systemd/network/10-forgeos-<iface>.network   — one file per managed NIC

  [Match]
  Name=ens18
  [Network]
  DHCP=yes                    # dhcp
    -- or --
  Address=10.0.0.69/24        # static
  Gateway=10.0.0.1
  DNS=1.1.1.1
  [Link]
  MTUBytes=9000               # only when non-default

Apply = write the file + `networkctl reload` (re-read .network files) +
`networkctl reconfigure <iface>` (apply to that NIC). Revert = restore the
snapshot files + reconfigure. All paths module-level so tests redirect them;
networkctl runs through the injected runner so tests mock it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from forgeos_atomic import atomic_write
from net_rollback import RollbackEngine

logger = logging.getLogger("forgeos-api")

# ── paths (module-level → redirectable in tests) ──
NETWORKD_DIR = Path("/etc/systemd/network")
RESOLV_CONF = Path("/etc/resolv.conf")
ROUTES_FILE = Path("/etc/systemd/network/20-forgeos-routes.network")

_MANAGED_MARK = "# Managed by ForgeOS — edits here are overwritten\n"

# injected from the main module (same _run_args the rest of the API uses)
_run_args: Optional[Callable[..., str]] = None


def set_runner(run_args: Callable[..., str]) -> None:
    global _run_args
    _run_args = run_args


# ════════════════════════════════════════════════════════════════════
# CONFIG GENERATION  (pure — unit-testable)
# ════════════════════════════════════════════════════════════════════
def render_network_file(cfg: Any) -> str:
    """Render a systemd .network file for an InterfaceConfig-like object.

    cfg has: name, method ('dhcp'|'static'), address (CIDR|None),
    gateway (str|None), dns (list[str]), mtu (int).
    """
    lines = [_MANAGED_MARK, "[Match]\n", f"Name={cfg.name}\n", "\n", "[Network]\n"]
    if cfg.method == "dhcp":
        lines.append("DHCP=yes\n")
        for d in cfg.dns:                     # optional explicit DNS even on DHCP
            lines.append(f"DNS={d}\n")
    else:
        lines.append(f"Address={cfg.address}\n")
        if cfg.gateway:
            lines.append(f"Gateway={cfg.gateway}\n")
        for d in cfg.dns:
            lines.append(f"DNS={d}\n")
    if cfg.mtu and cfg.mtu != 1500:
        lines += ["\n", "[Link]\n", f"MTUBytes={cfg.mtu}\n"]
    return "".join(lines)


def render_resolv_conf(dns: list[str], domain: str = "") -> str:
    lines = [_MANAGED_MARK]
    if domain:
        lines.append(f"search {domain}\n")
    for s in dns:
        lines.append(f"nameserver {s}\n")
    return "".join(lines)


# ════════════════════════════════════════════════════════════════════
# LOW-LEVEL FILE + RELOAD
# ════════════════════════════════════════════════════════════════════
def _netfile_path(iface: str) -> Path:
    # 10- prefix so ForgeOS files sort before any distro defaults
    return NETWORKD_DIR / f"10-forgeos-{iface}.network"


def _reload(iface: Optional[str]) -> None:
    """Re-read .network files and apply. networkd has no external DHCP client
    to fight, so this is deterministic: reload config, reconfigure the NIC."""
    assert _run_args is not None
    _run_args(["networkctl", "reload"], timeout=15)
    if iface:
        _run_args(["networkctl", "reconfigure", iface], timeout=30)


# ════════════════════════════════════════════════════════════════════
# SNAPSHOT / APPLY / REVERT  (wired into the rollback engine)
# ════════════════════════════════════════════════════════════════════
def _snapshot() -> dict:
    """Capture all .network files + resolv.conf in memory."""
    files: dict[str, str] = {}
    if NETWORKD_DIR.is_dir():
        for p in NETWORKD_DIR.iterdir():
            if p.is_file() and p.suffix == ".network":
                try:
                    files[p.name] = p.read_text()
                except OSError:
                    pass
    return {
        "files": files,
        "resolv": RESOLV_CONF.read_text() if RESOLV_CONF.exists() else None,
    }


def _restore(snap: dict) -> None:
    """Restore a snapshot exactly (all .network files + resolv.conf)."""
    # delete any current .network file, then restore the snapshot set
    if NETWORKD_DIR.is_dir():
        for p in list(NETWORKD_DIR.iterdir()):
            if p.is_file() and p.suffix == ".network":
                try:
                    p.unlink()
                except OSError:
                    pass
    for name, content in snap.get("files", {}).items():
        atomic_write(NETWORKD_DIR / name, content)
    if snap.get("resolv") is not None:
        # DNS is NOT lockout-critical — the .network restore above is what
        # brings the box back. A resolv.conf failure must never abort the
        # revert before the link gets reconfigured (it did exactly that on
        # hardware: EROFS here left the box stranded on the applied address).
        try:
            atomic_write(RESOLV_CONF, snap["resolv"])
        except OSError as e:
            logger.error("revert: could not restore resolv.conf: %s", e)


# Which interface the pending change touched. The engine allows exactly one
# pending change at a time, so a single slot is sufficient. _revert needs this
# because the engine hands it only the snapshot — and restoring the .network
# file is NOT enough: the live link keeps the applied address until that
# interface is explicitly reconfigured.
_pending_iface: Optional[str] = None


def _apply(change: dict) -> None:
    """Apply a pending interface change, then reload. change = {'cfg': cfg}."""
    global _pending_iface
    cfg = change["cfg"]
    _pending_iface = cfg.name
    atomic_write(_netfile_path(cfg.name), render_network_file(cfg))
    _reload(cfg.name)


def _revert(snap: dict) -> None:
    """Restore the snapshot AND reconfigure the affected link.

    Restoring the file alone leaves the interface on the applied (possibly
    unreachable) address — `networkctl reload` re-reads config but does not
    reliably re-apply it to an already-configured link. Reconfiguring the
    specific interface is what actually brings the box back.
    """
    global _pending_iface
    iface = _pending_iface
    _restore(snap)
    _reload(iface)
    _pending_iface = None


# ════════════════════════════════════════════════════════════════════
# STATIC ROUTES  (separate file — survives interface-file regeneration)
# ════════════════════════════════════════════════════════════════════
# Managed routes live in their own 20-forgeos-routes.network, NOT in the
# per-interface files: those regenerate wholesale on every interface edit and
# would wipe any [Route] sections written into them. networkd applies every
# .network file whose [Match] selects a present link, so a routes-only file
# matched to the primary interface adds its routes without owning addressing.
#
# Lower stakes than interface changes: a bad route doesn't drop the box the way
# a bad address does, so these apply directly — no rollback timer. Still
# admin-gated and validated at the API boundary.

def render_routes_file(routes: list, match_iface: str) -> str:
    """Render 20-forgeos-routes.network for a list of route dicts.

    Each route: {destination (CIDR), gateway, metric}. `match_iface` binds the
    file to a present link so networkd applies it.
    """
    lines = [_MANAGED_MARK, "[Match]\n", f"Name={match_iface}\n"]
    for r in routes:
        lines.append("\n[Route]\n")
        lines.append(f"Destination={r['destination']}\n")
        if r.get("gateway"):
            lines.append(f"Gateway={r['gateway']}\n")
        m = int(r.get("metric", 0) or 0)
        if m:
            lines.append(f"Metric={m}\n")
    return "".join(lines)


def load_managed_routes() -> list:
    """Parse the managed routes back out of 20-forgeos-routes.network.

    The file is the source of truth for what ForgeOS manages (the live routing
    table also holds kernel/DHCP routes we don't own).
    """
    if not ROUTES_FILE.exists():
        return []
    out, cur = [], None
    try:
        text = ROUTES_FILE.read_text()
    except OSError:
        return []
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[Route]":
            cur = {"destination": "", "gateway": "", "metric": 0}
            out.append(cur)
        elif cur is not None and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip().lower()
            if k == "destination":
                cur["destination"] = v.strip()
            elif k == "gateway":
                cur["gateway"] = v.strip()
            elif k == "metric":
                try:
                    cur["metric"] = int(v.strip())
                except ValueError:
                    pass
    return [r for r in out if r["destination"]]


def _match_iface_for_routes() -> str:
    """Which link to bind the routes file to: the primary (default-route) NIC.

    Falls back to the first ForgeOS-managed interface file, then to a wildcard,
    so routes still load on a single-NIC box regardless of its name.
    """
    assert _run_args is not None
    try:
        import json as _json
        out = _run_args(["ip", "-j", "route", "show", "default"], timeout=10)
        data = _json.loads(out) if out else []
        if data and isinstance(data, list) and data[0].get("dev"):
            return data[0]["dev"]
    except Exception:
        pass
    if NETWORKD_DIR.is_dir():
        for p in sorted(NETWORKD_DIR.glob("10-forgeos-*.network")):
            name = p.stem.replace("10-forgeos-", "")
            if name:
                return name
    return "en*"


def apply_routes(routes: list) -> None:
    """Persist the managed route set and reload networkd.

    Writing an empty list removes the managed-routes file entirely rather than
    leaving a [Match]-only stub.
    """
    if not routes:
        if ROUTES_FILE.exists():
            try:
                ROUTES_FILE.unlink()
            except OSError as e:
                logger.warning("routes: could not remove %s: %s", ROUTES_FILE, e)
    else:
        atomic_write(ROUTES_FILE, render_routes_file(routes, _match_iface_for_routes()))
    _reload(None)


# Single engine instance for interface changes (60s confirm window).
# 120s, not 60: an address change moves the box to a new origin, so the admin
# has to reconnect AND sign in again at the new address before they can
# confirm. 60s is not enough for that round trip.
engine = RollbackEngine(_snapshot, _apply, _revert, window_seconds=120)


# ════════════════════════════════════════════════════════════════════
# GLOBAL (hostname + DNS) — low-risk, applied DIRECTLY (no rollback timer)
# ════════════════════════════════════════════════════════════════════
def apply_global(hostname: str, dns: list[str], domain: str) -> None:
    assert _run_args is not None
    _run_args(["hostnamectl", "set-hostname", hostname], timeout=10)
    if dns:
        # Written directly to resolv.conf. If systemd-resolved manages
        # resolv.conf as a symlink, the ISO provisioning decides that; here we
        # write the file the system actually reads.
        atomic_write(RESOLV_CONF, render_resolv_conf(dns, domain))
