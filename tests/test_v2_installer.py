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
    inst.stat_file = lambda path: (0o100600, 0)   # 0600, root — clean
    inst.get_hostname = lambda: "testbox"          # deterministic for naming
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
    assert inst._saved["cfg"].domain == "testbox.local"


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
                      "web", "generate", "toggles", "resolution",
                      "verify", "secaudit"]
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


def test_secaudit_passes_when_all_0600_root():
    inst = _installer()
    inst.stat_file = lambda path: (0o100600, 0)   # 0600 root
    r = inst.phase_secaudit()
    assert r.ok


def test_secaudit_fails_on_world_readable_secret():
    inst = _installer()
    # api-users.json is 0644 (group/other readable) -> must fail
    def stat(path):
        return (0o100644, 0) if path.endswith("api-users.json") else (0o100600, 0)
    inst.stat_file = stat
    r = inst.phase_secaudit()
    assert not r.ok
    assert "api-users.json" in r.detail


def test_secaudit_fails_on_non_root_owner():
    inst = _installer()
    def stat(path):
        return (0o100600, 1000) if path.endswith("api.env") else (0o100600, 0)
    inst.stat_file = stat
    r = inst.phase_secaudit()
    assert not r.ok
    assert "api.env" in r.detail


def test_secaudit_skips_absent_optional_files():
    inst = _installer()
    # wg key absent (VPN off) -> None -> skipped, not failed
    def stat(path):
        return None if "wireguard" in path else (0o100600, 0)
    inst.stat_file = stat
    r = inst.phase_secaudit()
    assert r.ok


def test_naming_derives_lan_name_from_hostname():
    # Option 3: no domain given -> lan_name = <hostname>.local, hostname untouched
    inst = _installer(fi.InstallChoices(domain=""))
    inst.get_hostname = lambda: "KeithTechCo"
    cfg = inst.build_config()
    assert cfg.naming.system_hostname == "KeithTechCo"
    assert cfg.naming.lan_name == "KeithTechCo.local"
    assert cfg.domain == "KeithTechCo.local"
    assert cfg.naming.public_fqdn == ""        # empty until mail/proxy sets it


def test_naming_custom_domain_kept():
    inst = _installer(fi.InstallChoices(domain="nas.local"))
    inst.get_hostname = lambda: "KeithTechCo"
    cfg = inst.build_config()
    assert cfg.naming.lan_name == "nas.local"
    assert cfg.naming.system_hostname == "KeithTechCo"   # NOT renamed


def test_resolution_hostname_default_is_noop_alias():
    inst = _installer(fi.InstallChoices(domain=""))
    inst.get_hostname = lambda: "testbox"
    writes = []
    inst._write_file = lambda p, c, m: writes.append(p)
    r = inst.phase_resolution()
    assert r.ok
    # default name needs no alias unit
    assert not any("mdns-alias" in w for w in writes)


def test_resolution_custom_local_publishes_alias():
    inst = _installer(fi.InstallChoices(domain="nas.local"))
    inst.get_hostname = lambda: "testbox"
    writes = []
    inst._write_file = lambda p, c, m: writes.append(p)
    r = inst.phase_resolution()
    assert r.ok
    assert any("mdns-alias" in w for w in writes)


def test_resolution_non_local_is_noop():
    inst = _installer(fi.InstallChoices(domain="home.lan"))
    inst.get_hostname = lambda: "testbox"
    r = inst.phase_resolution()
    assert r.ok
    assert "not mDNS" in r.detail


def test_service_config_dirs_in_readwritepaths():
    # Regression: generators write /etc/samba/smb.conf, /etc/nginx/*, and
    # /etc/fail2ban/* while the API runs under ProtectSystem=strict — so those
    # dirs MUST be in ReadWritePaths or the writes are silently denied (this is
    # exactly the bug where smb.conf never regenerated). '-' prefix = writable
    # if present, ignored if missing (no 226/NAMESPACE crash on minimal boxes).
    unit = fi._API_SERVICE_UNIT
    for d in ("/etc/samba", "/etc/nginx", "/etc/fail2ban",
              "/etc/letsencrypt", "/var/log/letsencrypt", "/var/lib/letsencrypt"):
        assert ("-" + d) in unit or (" " + d) in unit, f"{d} missing from ReadWritePaths"


def test_generator_writes_stay_within_readwritepaths():
    """INVARIANT: every path any registered generator emits must sit under a
    ReadWritePaths entry. Otherwise ProtectSystem=strict silently denies the
    write at runtime — the Samba / letsencrypt / exports / wireguard / rear bug
    class. Renders ALL generators against a fully-populated config and fails if
    any output escapes the writable set, so the class cannot silently regress.
    """
    import forgeos_config as fc
    from generators import registry

    rwp = next(l for l in fi._API_SERVICE_UNIT.splitlines()
               if l.strip().startswith("ReadWritePaths="))
    prefixes = [p.lstrip("-").replace("{opt}", "/opt/forgeos")
                for p in rwp.split("=", 1)[1].split()]

    def covered(path: str) -> bool:
        return any(path == pre or path.startswith(pre.rstrip("/") + "/")
                   for pre in prefixes)

    cfg = fc.ForgeOSConfig()
    cfg.nfs.enabled = True
    cfg.nfs.exports = [fc.NfsExport(path="/srv/nas/share", type="rw")]
    cfg.wireguard.enabled = True
    cfg.osbackup.enabled = True
    cfg.samba.enabled = True
    cfg.samba.shares = [fc.SambaShare(name="data", path="/srv/nas/data")]
    cfg.security.profile = "high"          # widest tool set
    cfg.nginx.enabled = True
    cfg.nginx.vhosts = [fc.NginxVhost(name="app", domain="app.lan", upstream_port=8080)]

    uncovered = []
    for name in registry.names():
        for rf in registry.get(name).render(cfg):
            if not covered(rf.path):
                uncovered.append((name, rf.path))
    assert not uncovered, f"generator writes escape ReadWritePaths: {uncovered}"
