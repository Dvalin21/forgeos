"""ifupdown config writer + the real snapshot/apply/revert for interface changes.

This is the LIVE-config layer: it writes /etc/network/interfaces.d/ drop-ins,
edits /etc/network/interfaces, rewrites /etc/resolv.conf, and reloads the
interface. Interface (address/gateway/MTU) changes go through the rollback
engine from net_rollback (snapshot → apply → arm 60s revert), because those
are the changes that can drop a headless box off the network.

Verified stack facts this is built against:
  • ifupdown; /etc/network/interfaces with `source .../interfaces.d/*`.
  • The primary NIC (ens18) is defined in the MAIN interfaces file, not a
    drop-in — so writing a drop-in for it would create a DUPLICATE `iface`
    stanza (ifupdown undefined behaviour). apply() therefore comments the
    managed interface's lines OUT of the main file and writes the drop-in;
    the snapshot captures the original main file so revert restores it.
  • DNS is a plain static /etc/resolv.conf (no resolvconf/systemd-resolved),
    so DNS is written there directly rather than via `dns-nameservers`.
  • Reload is runtime-detected: `ifreload -a` (ifupdown2) if present, else
    `ifdown <iface> --force; ifup <iface>` (classic ifupdown).

All paths are module-level so tests redirect them to a temp dir; the reload
runs through the injected _run_args so tests mock it (no real ip/ifupdown).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from net_rollback import RollbackEngine

logger = logging.getLogger("forgeos-api")

# ── paths (module-level → redirectable in tests) ──
INTERFACES_MAIN = Path("/etc/network/interfaces")
INTERFACES_D = Path("/etc/network/interfaces.d")
RESOLV_CONF = Path("/etc/resolv.conf")

_MANAGED_PREFIX = "forgeos-"          # our drop-in files are forgeos-<iface>.cfg
_MANAGED_MARK = "# Managed by ForgeOS — edits here are overwritten\n"

# injected from the main module (same _run_args the rest of the API uses)
_run_args: Optional[Callable[..., str]] = None


def set_runner(run_args: Callable[..., str]) -> None:
    global _run_args
    _run_args = run_args


# ════════════════════════════════════════════════════════════════════
# CONFIG GENERATION  (pure — easy to unit-test)
# ════════════════════════════════════════════════════════════════════
def render_interface_stanza(cfg: Any) -> str:
    """Render an ifupdown stanza for an InterfaceConfig-like object.

    cfg has: name, method ('dhcp'|'static'), address (CIDR|None),
    gateway (str|None), dns (list[str]), mtu (int).
    """
    lines = [_MANAGED_MARK, f"allow-hotplug {cfg.name}\n"]
    if cfg.method == "dhcp":
        lines.append(f"iface {cfg.name} inet dhcp\n")
    else:
        lines.append(f"iface {cfg.name} inet static\n")
        # address is a CIDR (e.g. 10.0.0.69/24) — ifupdown accepts CIDR form
        lines.append(f"    address {cfg.address}\n")
        if cfg.gateway:
            lines.append(f"    gateway {cfg.gateway}\n")
        if cfg.dns:
            # harmless even without resolvconf; global DNS still writes resolv.conf
            lines.append(f"    dns-nameservers {' '.join(cfg.dns)}\n")
    if cfg.mtu and cfg.mtu != 1500:
        lines.append(f"    mtu {cfg.mtu}\n")
    return "".join(lines)


def _comment_out_iface_in_main(content: str, iface: str) -> str:
    """Comment out any auto/allow-hotplug/iface lines (and the indented body of
    an iface block) for `iface` in the main interfaces file, so the drop-in is
    the single definition. Idempotent — already-commented lines are left alone.
    """
    out: list[str] = []
    in_block = False
    # matches the start of a stanza for THIS iface
    start_re = re.compile(rf"^\s*(auto|allow-hotplug|iface)\s+{re.escape(iface)}(\s|$)")
    # any new stanza start ends the previous iface block's indented body
    any_start_re = re.compile(r"^\s*(auto|allow-hotplug|iface|source|mapping)\s")
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if in_block:
            # indented continuation of the iface block → comment it, unless a new
            # stanza starts (then fall through to normal handling)
            if line[:1] in (" ", "\t") and not any_start_re.match(line):
                out.append("# " + line if not stripped.startswith("#") else line)
                continue
            in_block = False
        if start_re.match(line):
            out.append("# " + line if not stripped.startswith("#") else line)
            # if this was the `iface` line, its indented body follows
            if stripped.split()[0:1] == ["iface"]:
                in_block = True
            continue
        out.append(line)
    return "".join(out)


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


def _dropin_path(iface: str) -> Path:
    return INTERFACES_D / f"{_MANAGED_PREFIX}{iface}.cfg"


def _reload(iface: Optional[str]) -> None:
    """Reload networking. Runtime-detects ifupdown2 vs classic ifupdown."""
    assert _run_args is not None
    if shutil.which("ifreload"):
        _run_args(["ifreload", "-a"], timeout=30)
    elif iface:
        # classic: bounce just the changed interface (bringing everything down
        # with `ifdown -a` on a remote box is a footgun)
        _run_args(["ifdown", iface, "--force"], timeout=15)
        _run_args(["ifup", iface], timeout=30)


# ════════════════════════════════════════════════════════════════════
# SNAPSHOT / APPLY / REVERT  (wired into the rollback engine)
# ════════════════════════════════════════════════════════════════════
def _snapshot() -> dict:
    """Capture everything an interface change can touch, in memory."""
    dropins: dict[str, str] = {}
    if INTERFACES_D.is_dir():
        for p in INTERFACES_D.iterdir():
            if p.is_file():
                try:
                    dropins[p.name] = p.read_text()
                except OSError:
                    pass
    return {
        "main": INTERFACES_MAIN.read_text() if INTERFACES_MAIN.exists() else None,
        "dropins": dropins,
        "resolv": RESOLV_CONF.read_text() if RESOLV_CONF.exists() else None,
    }


def _restore(snap: dict) -> None:
    """Restore a snapshot exactly (main file, ALL drop-ins, resolv.conf)."""
    if snap.get("main") is not None:
        _atomic_write(INTERFACES_MAIN, snap["main"])
    # reconcile drop-ins: delete any current file, then restore the snapshot set
    if INTERFACES_D.is_dir():
        for p in list(INTERFACES_D.iterdir()):
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
    for name, content in snap.get("dropins", {}).items():
        _atomic_write(INTERFACES_D / name, content)
    if snap.get("resolv") is not None:
        _atomic_write(RESOLV_CONF, snap["resolv"])


def _apply(change: dict) -> None:
    """Apply a pending interface change, then reload. change = {'cfg': cfg}."""
    cfg = change["cfg"]
    # 1. write the managed drop-in
    _atomic_write(_dropin_path(cfg.name), render_interface_stanza(cfg))
    # 2. ensure the interface isn't ALSO defined in the main file (dedup)
    if INTERFACES_MAIN.exists():
        main = INTERFACES_MAIN.read_text()
        deduped = _comment_out_iface_in_main(main, cfg.name)
        if deduped != main:
            _atomic_write(INTERFACES_MAIN, deduped)
    # 3. reload networking on the changed interface
    _reload(cfg.name)


def _revert(snap: dict) -> None:
    _restore(snap)
    _reload(None)          # ifreload -a; classic path reloads via restored config


# Single engine instance for interface changes (60s confirm window).
engine = RollbackEngine(_snapshot, _apply, _revert, window_seconds=60)


# ════════════════════════════════════════════════════════════════════
# GLOBAL (hostname + DNS) — low-risk, applied DIRECTLY (no rollback timer,
# since these don't drop the IP-based admin session)
# ════════════════════════════════════════════════════════════════════
def apply_global(hostname: str, dns: list[str], domain: str) -> None:
    assert _run_args is not None
    # hostname via hostnamectl (persistent + runtime)
    _run_args(["hostnamectl", "set-hostname", hostname], timeout=10)
    # DNS straight into resolv.conf (this host has no resolvconf/resolved)
    if dns:
        _atomic_write(RESOLV_CONF, render_resolv_conf(dns, domain))
