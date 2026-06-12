"""Tests for base-feature toggles — pure planning, no lspci/apt/root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
import forgeos_toggles as tg  # noqa: E402
from forgeos_toggles import Action  # noqa: E402


# ---- pure decision table ----

def test_enable_not_installed_hw_present_installs():
    p = tg.plan_toggle("coral", desired_enabled=True, hardware_present=True,
                       currently_installed=False, hardware_gated=True)
    assert p.action == Action.INSTALL


def test_enable_hw_gated_no_hw_blocked():
    p = tg.plan_toggle("coral", desired_enabled=True, hardware_present=False,
                       currently_installed=False, hardware_gated=True)
    assert p.action == Action.BLOCKED_NO_HARDWARE


def test_enable_already_installed_noop():
    p = tg.plan_toggle("gpu", desired_enabled=True, hardware_present=True,
                       currently_installed=True, hardware_gated=True)
    assert p.action == Action.NOOP


def test_disable_installed_uninstalls():
    p = tg.plan_toggle("gpu", desired_enabled=False, hardware_present=True,
                       currently_installed=True, hardware_gated=True)
    assert p.action == Action.UNINSTALL


def test_disable_not_installed_noop():
    p = tg.plan_toggle("forgefiledb", desired_enabled=False, hardware_present=True,
                       currently_installed=False, hardware_gated=False)
    assert p.action == Action.NOOP


def test_non_hw_gated_enable_installs_without_hardware():
    # forgefiledb is not hardware-gated; hardware_present irrelevant
    p = tg.plan_toggle("forgefiledb", desired_enabled=True, hardware_present=False,
                       currently_installed=False, hardware_gated=False)
    assert p.action == Action.INSTALL


# ---- hardware detection (injected run) ----

def _run_returning(stdout):
    class R:
        def __init__(self, out): self.stdout = out; self.returncode = 0; self.stderr = ""
    return lambda cmd: R(stdout)


def test_detect_coral_true():
    run = _run_returning("01:00.0 0c80: 1ac1:089a")
    assert tg.detect_coral(run) is True


def test_detect_coral_false():
    run = _run_returning("01:00.0 ethernet")
    assert tg.detect_coral(run) is False


def test_detect_gpu_nvidia():
    run = _run_returning("01:00.0 VGA compatible controller: NVIDIA Corporation")
    assert tg.detect_gpu(run) is True


def test_detect_gpu_none():
    run = _run_returning("00:00.0 Host bridge: Intel")
    assert tg.detect_gpu(run) is False


# ---- manager.plan over the config DB ----

def test_manager_plans_all_three():
    cfg = fc.ForgeOSConfig()
    cfg.toggles.forgefiledb = True
    cfg.toggles.coral = True
    cfg.toggles.gpu = False

    # coral hw present; nothing installed yet
    mgr = tg.ToggleManager(
        run=_run_returning("1ac1:089a"),       # coral present
        is_installed=lambda f: False,
    )
    plans = {p.feature: p.action for p in mgr.plan(cfg)}
    assert plans["forgefiledb"] == Action.INSTALL
    assert plans["coral"] == Action.INSTALL
    assert plans["gpu"] == Action.NOOP          # disabled + not installed


def test_manager_blocks_coral_without_hardware():
    cfg = fc.ForgeOSConfig()
    cfg.toggles.coral = True
    mgr = tg.ToggleManager(
        run=_run_returning("no accelerator here"),   # no 089a
        is_installed=lambda f: False,
    )
    plans = {p.feature: p.action for p in mgr.plan(cfg)}
    assert plans["coral"] == Action.BLOCKED_NO_HARDWARE


def test_manager_uninstalls_when_disabled_but_installed():
    cfg = fc.ForgeOSConfig()
    cfg.toggles.gpu = False
    mgr = tg.ToggleManager(
        run=_run_returning(""),
        is_installed=lambda f: f == "gpu",          # gpu currently installed
    )
    plans = {p.feature: p.action for p in mgr.plan(cfg)}
    assert plans["gpu"] == Action.UNINSTALL


def test_toggles_default_all_off():
    t = fc.TogglesConfig()
    assert t.forgefiledb is False and t.coral is False and t.gpu is False
