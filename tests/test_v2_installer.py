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
    inst.deploy_web = lambda repo, opt: None
    inst._write_file = lambda p, c, m: None
    inst._make_dirs = lambda dirs: None
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


def test_build_config_seeds_ui_vhost():
    inst = _installer(fi.InstallChoices(domain="home.lan"))
    cfg = inst.build_config()
    ui = [v for v in cfg.nginx.vhosts if v.name == "forgeos-ui"]
    assert len(ui) == 1
    assert ui[0].domain == "home.lan"
    assert ui[0].upstream_port == fi.WEBUI_BACKEND_PORT
    assert ui[0].websocket is True


def test_web_phase_deploys_and_starts():
    cmds = []
    deployed = {}
    writes = []
    made_dirs = []
    inst = _installer(run=lambda cmd: cmds.append(cmd) or OK())
    inst.deploy_web = lambda repo, opt: deployed.update(repo=repo, opt=opt)
    inst._write_file = lambda p, c, m: writes.append(p)
    inst._make_dirs = lambda dirs: made_dirs.extend(dirs)
    res = inst.phase_web()
    assert res.ok
    assert deployed["opt"] == fi.FORGEOS_OPT
    assert "/etc/forgeos/api.env" in writes
    assert "/etc/systemd/system/forgeos-api.service" in writes
    # the runtime dirs the systemd hardening needs must be created
    assert "/var/log/forgeos" in made_dirs
    assert "/var/lib/forgeos" in made_dirs
    joined = [" ".join(c) for c in cmds]
    assert any("enable --now forgeos-api" in j for j in joined)


def test_runtime_dirs_match_readwritepaths():
    # regression: every RUNTIME_DIR must be created so ProtectSystem=strict +
    # ReadWritePaths can bind-mount it (missing dir -> 226/NAMESPACE crash).
    for d in ("/var/log/forgeos", "/var/lib/forgeos", "/etc/forgeos"):
        assert d in fi.RUNTIME_DIRS
        assert d in fi._API_SERVICE_UNIT


def test_web_phase_reports_start_failure():
    inst = _installer(run=lambda cmd: FAIL() if "enable" in cmd else OK())
    inst.deploy_web = lambda repo, opt: None
    inst._write_file = lambda p, c, m: None
    res = inst.phase_web()
    assert not res.ok


def test_run_all_full_success():
    inst = _installer()
    results = inst.run_all()
    phases = [r.phase for r in results]
    assert phases == ["base_packages", "seed_config", "keystores",
                      "web", "generate", "toggles"]
    assert all(r.ok for r in results)


def test_base_package_list_has_core_services():
    # sanity: the base list covers each base service family
    pkgs = set(fi.BASE_PACKAGES)
    assert "samba" in pkgs
    assert "nginx" in pkgs
    assert "ssl-cert" in pkgs   # snakeoil cert -> nginx can open :443 pre-LE
    assert "wireguard" in pkgs
    assert "nfs-kernel-server" in pkgs
    assert "fail2ban" in pkgs
    assert "restic" in pkgs


def test_repo_root_auto_derived_not_hardcoded_root():
    # regression: repo_root must derive from the module location, never a
    # hardcoded /root/forgeos (broke installs cloned to /home/<user>).
    inst = fi.Installer(choices=fi.InstallChoices())
    assert inst.repo_root != "/root/forgeos"
    import os
    # it derives to wherever the code actually lives, and src/ is there
    assert os.path.isdir(os.path.join(inst.repo_root, "src"))


def test_explicit_repo_root_respected():
    inst = fi.Installer(choices=fi.InstallChoices(), repo_root="/custom/path")
    assert inst.repo_root == "/custom/path"
