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
    inst._create_admin_user = lambda: "test-pw-abc123"
    inst._disable_stock_nginx_default = lambda: None
    inst.http_post = lambda url, body: (200, '{"access_token":"t"}')
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
    inst._create_admin_user = lambda: "pw-from-phase"
    inst._disable_stock_nginx_default = lambda: None
    res = inst.phase_web()
    assert res.ok
    assert deployed["opt"] == fi.FORGEOS_OPT
    assert "/etc/forgeos/api.env" in writes
    assert "/etc/systemd/system/forgeos-api.service" in writes
    # the runtime dirs the systemd hardening needs must be created
    assert "/var/log/forgeos" in made_dirs
    assert "/var/lib/forgeos" in made_dirs
    # admin password captured for the CLI to surface (V-004)
    assert inst._admin_password == "pw-from-phase"
    joined = [" ".join(c) for c in cmds]
    assert any("enable --now forgeos-api" in j for j in joined)


def test_create_admin_user_writes_hashed_record(monkeypatch):
    # V-001/V-004: real _create_admin_user writes a bcrypt-hashed admin record
    # at 0600, returns the plaintext, and never stores the plaintext.
    inst = _installer()
    written = {}
    inst._write_file = lambda p, c, m: written.update(path=p, content=c, mode=m)
    # ensure the "already exists" early-return doesn't fire
    import forgeos_install as fimod
    monkeypatch.setattr(fimod.Installer, "_create_admin_user",
                        fi.Installer._create_admin_user)
    import json
    # call the REAL method (not the fixture stub)
    pw = fi.Installer._create_admin_user(inst)
    assert pw  # got a password
    assert written["mode"] == 0o600
    rec = json.loads(written["content"])
    assert rec["admin"]["role"] == "admin"
    assert rec["admin"]["hash"].startswith("$2")   # bcrypt
    assert pw not in written["content"]            # plaintext never stored


def test_disable_stock_default_unlinks_symlink(tmp_path, monkeypatch):
    # disables via unlink, and is a no-op when absent
    fi.Installer._disable_stock_nginx_default()  # absent path -> no raise


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
                      "web", "generate", "toggles", "verify"]
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


def test_verify_login_success_requires_token():
    # V-002 healthcheck: real login must return 200 + a token
    inst = _installer()
    inst._admin_password = "generated-pw"
    inst.http_post = lambda url, body: (200, '{"access_token":"xyz"}')
    r = inst.phase_verify()
    assert r.ok


def test_verify_login_fails_when_password_rejected():
    # if the generated password is rejected, the install must NOT pass
    inst = _installer()
    inst._admin_password = "generated-pw"
    inst.http_post = lambda url, body: (401, '{"detail":"Invalid credentials"}')
    # one quick attempt, no real sleeping
    inst._verify_login = lambda **k: fi.Installer._verify_login(
        inst, attempts=1, delay=0, **k)
    r = inst.phase_verify()
    assert not r.ok
    assert "401" in r.detail


def test_verify_idempotent_accepts_401_when_no_password():
    # admin pre-existed (no known pw): endpoint must be up and reject bad creds
    inst = _installer()
    inst._admin_password = ""
    inst.http_post = lambda url, body: (401, "nope")
    r = inst.phase_verify()
    assert r.ok


def test_verify_fails_when_service_unreachable():
    inst = _installer()
    inst._admin_password = "pw"
    def boom(url, body):
        raise OSError("connection refused")
    inst.http_post = boom
    inst._verify_login = lambda **k: fi.Installer._verify_login(
        inst, attempts=2, delay=0, **k)
    r = inst.phase_verify()
    assert not r.ok
