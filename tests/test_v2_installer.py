"""Tests for the v2 installer core — injected deps, no root/apt/systemd."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "install" / "v2"))

import forgeos_config as fc  # noqa: E402
import forgeos_install as fi  # noqa: E402


class OK:
    returncode = 0
    stdout = ""
    stderr = ""


class FAIL:
    returncode = 1
    stdout = ""
    stderr = "boom"


def _installer(choices=None, run=None, tmp_cfg=None):
    choices = choices or fi.InstallChoices()
    saved = {}
    inst = fi.Installer(choices=choices)
    inst.run = run or (lambda cmd: OK())
    inst.save_cfg = lambda cfg, path=None: saved.__setitem__("cfg", cfg)
    inst.generate = lambda: []
    inst.apply_toggles = lambda cfg: []
    inst._saved = saved
    return inst


def test_build_config_from_choices():
    ch = fi.InstallChoices(domain="home.lan", security_profile="high",
                           lan_cidr="192.168.1.0/24", enable_wireguard=True,
                           enable_nfs=True, enable_coral=True)
    inst = _installer(ch)
    cfg = inst.build_config()
    assert cfg.domain == "home.lan"
    assert cfg.security.profile == "high"
    assert cfg.security.lan_cidr == "192.168.1.0/24"
    assert cfg.wireguard.enabled is True
    assert cfg.nfs.enabled is True
    assert cfg.nfs.lan_cidr == "192.168.1.0/24"
    assert cfg.toggles.coral is True


def test_base_packages_phase_ok():
    inst = _installer()
    res = inst.phase_base_packages()
    assert res.ok


def test_base_packages_phase_failure():
    inst = _installer(run=lambda cmd: FAIL())
    res = inst.phase_base_packages()
    assert not res.ok
    assert "boom" in res.detail


def test_seed_config_saves():
    inst = _installer()
    res = inst.phase_seed_config()
    assert res.ok
    assert "cfg" in inst._saved
    assert inst._saved["cfg"].domain == "nas.local"


def test_keystores_skipped_when_no_wireguard():
    inst = _installer(fi.InstallChoices(enable_wireguard=False))
    res = inst.phase_keystores()
    assert res.ok
    assert "skipped" in res.detail


def test_keystores_runs_genkey_when_wireguard():
    cmds = []
    def run(cmd):
        cmds.append(cmd)
        return OK()
    inst = _installer(fi.InstallChoices(enable_wireguard=True), run=run)
    res = inst.phase_keystores()
    assert res.ok
    assert any("wg genkey" in " ".join(c) for c in cmds)


def test_generate_phase_reports_failure():
    class R:
        def __init__(self, svc, ok): self.service, self.ok = svc, ok
    inst = _installer()
    inst.generate = lambda: [R("samba", True), R("nginx", False)]
    res = inst.phase_generate()
    assert not res.ok
    assert "nginx" in res.detail


def test_generate_phase_ok():
    class R:
        def __init__(self, svc, ok): self.service, self.ok = svc, ok
    inst = _installer()
    inst.generate = lambda: [R("samba", True), R("nginx", True)]
    res = inst.phase_generate()
    assert res.ok


def test_run_all_stops_on_failure():
    inst = _installer(run=lambda cmd: FAIL())   # base packages fails first
    results = inst.run_all(stop_on_fail=True)
    # only the first phase ran
    assert len(results) == 1
    assert results[0].phase == "base_packages"
    assert not results[0].ok


def test_run_all_full_success():
    inst = _installer()
    results = inst.run_all()
    phases = [r.phase for r in results]
    assert phases == ["base_packages", "seed_config", "keystores",
                      "generate", "toggles"]
    assert all(r.ok for r in results)


def test_base_package_list_has_core_services():
    # sanity: the base list covers each base service family
    pkgs = set(fi.BASE_PACKAGES)
    assert "samba" in pkgs
    assert "nginx" in pkgs
    assert "wireguard" in pkgs
    assert "nfs-kernel-server" in pkgs
    assert "fail2ban" in pkgs
    assert "restic" in pkgs
