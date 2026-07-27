"""First-boot network conversion: DHCP → static at the leased address.

Runs once, at the end of a fresh ISO install. Does exactly one thing, on
Keith's explicit instruction after DHCP pool-range detection was found to be
impossible from a client (the protocol never exposes the server's scope to
it) — so this does NOT attempt to detect or warn about DHCP pool conflicts.
It lets DHCP hand out an address, then pins that same address as static:

  1. bring the primary interface up under DHCP long enough to get a lease
  2. read the leased address/gateway/DNS via `ip -j`
  3. write it back as STATIC using the exact same .network generator the
     Network page uses (net_networkd.render_network_file /
     forgeos_atomic.atomic_write) — so there is only one way ForgeOS ever
     writes interface config, not a second install-time implementation that
     could drift from the runtime one
  4. reconfigure so the static config takes effect without a reboot

Deliberately NOT built: any inference about the router's DHCP pool. Verified
there is no protocol-level way for a client to learn a DHCP server's pool
range (leases expose the assigned address/gateway/DNS/lease-server, never
the scope) — a heuristic guess would be presented as fact, so it is not
offered. If a leased address is later reused elsewhere, that's a router
configuration matter (a DHCP reservation), not something this script can
know.

Idempotent: safe to re-run. If the interface is already static (a
ForgeOS-managed .network file with an Address= exists), it does nothing.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Callable, Optional

logger = logging.getLogger("forgeos-firstboot")

# Injected by main() / tests — same DI pattern as net_networkd.set_runner.
_run_args: Optional[Callable[..., str]] = None


def set_runner(run_args: Callable[..., str]) -> None:
    global _run_args
    _run_args = run_args


def _run(args: list[str], timeout: int = 30) -> str:
    assert _run_args is not None, "set_runner() must be called first"
    return _run_args(args, timeout)


# ════════════════════════════════════════════════════════════════════
# DISCOVERY
# ════════════════════════════════════════════════════════════════════
def primary_interface() -> str:
    """The interface with the default route — the one DHCP configured.

    Empty string if none found (e.g. no network yet); caller must handle.
    """
    out = _run(["ip", "-j", "route", "show", "default"])
    try:
        data = json.loads(out) if out else []
    except (json.JSONDecodeError, ValueError):
        data = []
    if data and isinstance(data, list) and data[0].get("dev"):
        return data[0]["dev"]
    return ""


def read_lease(iface: str) -> Optional[dict]:
    """Current DHCP-assigned address/gateway/DNS for `iface`, or None if the
    interface has no dynamic address yet (DORA not complete)."""
    addr_out = _run(["ip", "-j", "addr", "show", iface])
    route_out = _run(["ip", "-j", "route", "show", "default", "dev", iface])
    try:
        addrs = json.loads(addr_out) if addr_out else []
    except (json.JSONDecodeError, ValueError):
        addrs = []
    try:
        routes = json.loads(route_out) if route_out else []
    except (json.JSONDecodeError, ValueError):
        routes = []

    address = None
    for entry in addrs:
        for a in entry.get("addr_info", []):
            if a.get("family") == "inet" and a.get("local"):
                plen = a.get("prefixlen")
                address = f"{a['local']}/{plen}" if plen is not None else a["local"]
                break
        if address:
            break
    if not address:
        return None

    gateway = None
    for r in routes:
        if r.get("gateway"):
            gateway = r["gateway"]
            break

    dns = _read_resolv_dns()
    return {"address": address, "gateway": gateway, "dns": dns}


def _read_resolv_dns() -> list[str]:
    """DNS servers DHCP wrote to /etc/resolv.conf. Best-effort — an empty
    list is fine, the Network page lets the admin set DNS afterward."""
    try:
        with open("/etc/resolv.conf") as f:
            return [line.split()[1] for line in f
                    if line.startswith("nameserver") and len(line.split()) > 1]
    except OSError:
        return []


def wait_for_lease(iface: str, attempts: int = 10, delay: float = 2.0) -> Optional[dict]:
    """Poll for a DHCP lease. DORA isn't instantaneous; give it real time
    rather than assuming the first check succeeds."""
    for _ in range(attempts):
        lease = read_lease(iface)
        if lease:
            return lease
        time.sleep(delay)
    return None


# ════════════════════════════════════════════════════════════════════
# ALREADY-CONVERTED CHECK  (idempotency)
# ════════════════════════════════════════════════════════════════════
def already_static(iface: str) -> bool:
    """True if a ForgeOS-managed .network file already gives this interface
    a static Address= (i.e. this script already ran, or the Network page has
    already been used to set one)."""
    import net_networkd as ni
    path = ni._netfile_path(iface)
    if not path.exists():
        return False
    try:
        content = path.read_text()
    except OSError:
        return False
    return "Address=" in content


# ════════════════════════════════════════════════════════════════════
# CONVERSION
# ════════════════════════════════════════════════════════════════════
def convert(iface: str, lease: dict) -> None:
    """Write the leased address back as static, using the SAME generator and
    writer the running Network page uses — not a separate implementation."""
    import net_networkd as ni
    from network_api import InterfaceConfig

    cfg = InterfaceConfig(
        name=iface, method="static",
        address=lease["address"], gateway=lease.get("gateway"),
        dns=lease.get("dns") or [], mtu=1500,
    )
    ni.atomic_write(ni._netfile_path(iface), ni.render_network_file(cfg))
    _run(["networkctl", "reload"])
    _run(["networkctl", "reconfigure", iface])


def enable_networkd() -> None:
    """Enable networkd/resolved, disable ifupdown's networking service.

    Mirrors exactly the manual migration Keith performed by hand on the dev
    VM (recorded: networkctl status showed routable/configured, no
    `dynamic`, after this same sequence).
    """
    _run(["systemctl", "enable", "--now", "systemd-networkd"])
    _run(["systemctl", "enable", "--now", "systemd-resolved"])
    _run(["systemctl", "disable", "networking"])


# ════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════
def run() -> int:
    """Returns a process exit code (0 success, 1 could not find a lease)."""
    enable_networkd()
    iface = primary_interface()
    if not iface:
        logger.error("firstboot: no interface with a default route found")
        return 1
    if already_static(iface):
        logger.info("firstboot: %s already has a managed static config, nothing to do", iface)
        return 0
    lease = wait_for_lease(iface)
    if not lease:
        logger.error("firstboot: no DHCP lease acquired on %s", iface)
        return 1
    convert(iface, lease)
    logger.info("firstboot: %s converted to static at %s", iface, lease["address"])
    return 0


if __name__ == "__main__":
    import subprocess

    def _real_run(args: list[str], timeout: int = 30) -> str:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.stdout if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    set_runner(_real_run)
    sys.exit(run())
