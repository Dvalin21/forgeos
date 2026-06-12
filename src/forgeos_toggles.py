"""ForgeOS base-feature toggles: ForgeFileDB, Coral TPU, GPU.

These are base features that are install/uninstall TOGGLES rather than
always-on services. Coral + GPU are also HARDWARE-GATED: enabling them only
does anything if the hardware is actually present.

The decision logic (plan_toggle) is pure and unit-tested: given the desired
state, whether the hardware is present, and whether the component is
currently installed, it returns exactly one action. Hardware detection and
package install/remove are injected so the planning is testable without
lspci, apt, or root.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    INSTALL = "install"
    UNINSTALL = "uninstall"
    NOOP = "noop"                 # already in desired state
    BLOCKED_NO_HARDWARE = "blocked_no_hardware"  # enabled but hw absent


@dataclass(frozen=True)
class TogglePlan:
    feature: str
    action: Action
    reason: str = ""


def plan_toggle(
    feature: str,
    *,
    desired_enabled: bool,
    hardware_present: bool,
    currently_installed: bool,
    hardware_gated: bool,
) -> TogglePlan:
    """Pure decision: what to do for one feature.

    Truth table:
      desired=on, hw-gated, no hw            -> BLOCKED_NO_HARDWARE
      desired=on, (hw ok or not gated), inst -> NOOP
      desired=on, (hw ok or not gated), !inst-> INSTALL
      desired=off, installed                 -> UNINSTALL
      desired=off, not installed             -> NOOP
    """
    if desired_enabled:
        if hardware_gated and not hardware_present:
            return TogglePlan(feature, Action.BLOCKED_NO_HARDWARE,
                              "enabled but no compatible hardware detected")
        if currently_installed:
            return TogglePlan(feature, Action.NOOP, "already installed")
        return TogglePlan(feature, Action.INSTALL, "enabling feature")
    else:
        if currently_installed:
            return TogglePlan(feature, Action.UNINSTALL, "disabling feature")
        return TogglePlan(feature, Action.NOOP, "already absent")


# ---- hardware detection (injectable) ----

def detect_coral(run) -> bool:
    """True if a Coral TPU (PCIe vendor:device 089a) is present."""
    r = run(["lspci", "-nn"])
    return "089a" in (r.stdout or "")


def detect_gpu(run) -> bool:
    """True if an NVIDIA/AMD/Intel-Arc GPU is present."""
    r = run(["lspci"])
    out = (r.stdout or "").lower()
    return any(k in out for k in ("nvidia", "amd/ati", "vga compatible controller"))


# ---- feature definitions ----

@dataclass(frozen=True)
class Feature:
    name: str
    hardware_gated: bool
    detect = None        # callable(run)->bool, or None if not hw-gated
    packages: tuple = ()
    marker: str = ""     # a path whose existence means "installed"


FEATURES: dict[str, dict] = {
    "forgefiledb": {
        "hardware_gated": False,
        "detect": None,
        "marker": "/opt/forgeos/filedb/forgeos-filedb.py",
    },
    "coral": {
        "hardware_gated": True,
        "detect": detect_coral,
        "marker": "/opt/forgeos/apps/coral/.installed",
    },
    "gpu": {
        "hardware_gated": True,
        "detect": detect_gpu,
        "marker": "/opt/forgeos/.gpu-installed",
    },
}


class ToggleManager:
    """Plans + (optionally) executes feature toggles. Deps injectable."""

    def __init__(self, *, run=None, is_installed=None):
        import subprocess

        self._run = run or (
            lambda cmd: subprocess.run(cmd, check=False, capture_output=True, text=True)
        )
        self._is_installed = is_installed or self._marker_installed

    def _marker_installed(self, feature: str) -> bool:
        from pathlib import Path

        marker = FEATURES[feature]["marker"]
        return bool(marker) and Path(marker).exists()

    def plan(self, cfg) -> list[TogglePlan]:
        """Plan all three toggles from the config DB. Pure given injected deps."""
        out: list[TogglePlan] = []
        desired = {
            "forgefiledb": cfg.toggles.forgefiledb,
            "coral": cfg.toggles.coral,
            "gpu": cfg.toggles.gpu,
        }
        for name, want in desired.items():
            spec = FEATURES[name]
            hw = True
            if spec["hardware_gated"] and spec["detect"] is not None:
                hw = spec["detect"](self._run)
            out.append(plan_toggle(
                name,
                desired_enabled=want,
                hardware_present=hw,
                currently_installed=self._is_installed(name),
                hardware_gated=spec["hardware_gated"],
            ))
        return out
