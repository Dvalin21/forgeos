"""Port allocator for app-store apps.

Each installed app gets a stable host port for its web UI (the WEBUI_PORT
magic variable). The platform picks a free port at install time and RECORDS
it in the config DB so it stays stable across restarts/regeneration.

The allocation logic is pure (given the set of used ports, pick a free one
in a range), so it's unit-testable. Probing the live system for ports in
use is a separate, injectable concern.
"""

from __future__ import annotations

import socket

# Default range for app web UIs. Avoids well-known ports and the ForgeOS
# base service ports (e.g. RustFS 9000/9001, Grafana-as-app will get a port
# from here rather than the legacy hardcoded 3000).
DEFAULT_RANGE = (20000, 29999)


class NoFreePortError(RuntimeError):
    pass


def pick_free_port(
    used: set[int],
    *,
    preferred: int | None = None,
    port_range: tuple[int, int] = DEFAULT_RANGE,
) -> int:
    """Pure: choose a free port not in `used`.

    If `preferred` is given and free (and in range), it's returned — so an
    app that asks for a specific port gets it when possible, but never
    collides. Otherwise the lowest free port in range is returned.
    """
    lo, hi = port_range
    if preferred is not None and lo <= preferred <= hi and preferred not in used:
        return preferred
    for port in range(lo, hi + 1):
        if port not in used:
            return port
    raise NoFreePortError(f"no free port in range {lo}-{hi}")


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Probe whether a port is currently bound (live-system check)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


def allocate_port(
    used_by_apps: set[int],
    *,
    preferred: int | None = None,
    probe=port_in_use,
    port_range: tuple[int, int] = DEFAULT_RANGE,
) -> int:
    """Pick a port free both in the config DB (used_by_apps) AND on the live
    system. `probe` is injectable so tests don't touch real sockets.
    """
    lo, hi = port_range
    candidate_used = set(used_by_apps)
    # First try the pure pick; if that port is live-bound by something not in
    # our records, mark it used and try again.
    for _ in range(lo, hi + 1):
        port = pick_free_port(candidate_used, preferred=preferred, port_range=port_range)
        if not probe(port):
            return port
        candidate_used.add(port)
        preferred = None  # preferred was taken on the live system
    raise NoFreePortError(f"no free port in range {lo}-{hi}")
