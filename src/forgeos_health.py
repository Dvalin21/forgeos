"""ForgeOS service health watcher.

Periodically checks base services; when one transitions DOWN it fires an SMTP
alert, and when it comes back UP it fires a recovery notice. Alerts fire on
the TRANSITION only — not every cycle — so a persistently-down service does
not spam.

Design: the transition logic (diff_states) is pure and unit-tested. The
runner injects a "probe" function (systemctl is-active) and a "notify"
function (SMTP send) so the whole thing is testable without systemd or mail.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

DEFAULT_SERVICES: dict[str, str] = {
    "smbd": "Samba",
    "nginx": "nginx",
    "fail2ban": "fail2ban (security)",
    "docker": "Docker",
    "forgeos-rustfs": "RustFS",
    "nfs-kernel-server": "NFS",
    "wg-quick@wg0": "WireGuard",
}


@dataclass(frozen=True)
class Transition:
    unit: str
    name: str
    kind: str  # "down" | "up"


def probe_systemctl(unit: str) -> bool:
    """Return True if the unit is active. Real probe."""
    try:
        out = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() == "active"
    except Exception:
        return False


def diff_states(
    services: dict[str, str],
    previous: dict[str, bool],
    current: dict[str, bool],
) -> list[Transition]:
    """Pure: previous vs current up/down -> list of transitions to alert on.

    Only emits when state CHANGES. First run (empty previous) establishes a
    baseline and emits nothing.
    """
    if not previous:
        return []
    out: list[Transition] = []
    for unit, name in services.items():
        was = previous.get(unit)
        now = current.get(unit)
        if was is None or now is None or was == now:
            continue
        out.append(Transition(unit=unit, name=name, kind="up" if now else "down"))
    return out


class HealthWatcher:
    def __init__(self, services=None, *, probe=probe_systemctl):
        self.services = services or dict(DEFAULT_SERVICES)
        self._probe = probe
        self._state: dict[str, bool] = {}

    def snapshot(self) -> dict[str, bool]:
        return {unit: self._probe(unit) for unit in self.services}

    def tick(self, notify) -> list[Transition]:
        """One check cycle. `notify(subject, body)` is called per transition.
        Returns the transitions detected (for logging/testing).
        """
        current = self.snapshot()
        transitions = diff_states(self.services, self._state, current)
        for t in transitions:
            if t.kind == "down":
                notify(f"{t.name} is DOWN", f"Service {t.unit} stopped on ForgeOS.")
            else:
                notify(f"{t.name} recovered", f"Service {t.unit} is active again.")
        self._state = current
        return transitions
