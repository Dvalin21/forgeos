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
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from net_rollback import RollbackEngine

logger = logging.getLogger("forgeos-api")

# ── paths (module-level → redirectable in tests) ──
NETWORKD_DIR = Path("/etc/systemd/network")
RESOLV_CONF = Path("/etc/resolv.conf")

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
def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fnet-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
        _atomic_write(NETWORKD_DIR / name, content)
    if snap.get("resolv") is not None:
        _atomic_write(RESOLV_CONF, snap["resolv"])


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
    _atomic_write(_netfile_path(cfg.name), render_network_file(cfg))
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


# Single engine instance for interface changes (60s confirm window).
engine = RollbackEngine(_snapshot, _apply, _revert, window_seconds=60)


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
        _atomic_write(RESOLV_CONF, render_resolv_conf(dns, domain))
