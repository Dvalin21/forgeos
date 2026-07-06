"""Security generator (post-P3): fail2ban jails/filter + AppArmor, nothing else.

auditd/AIDE/rkhunter/crowdsec and the tier system are deleted (owner decision:
small-business NAS threat model). ufw is owned by the firewall generator.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import forgeos_config as fc  # noqa: E402
import generators.security as sg  # noqa: E402
from generators.security import SecurityGenerator  # noqa: E402


def _files(cfg=None):
    return {f.path: f.content for f in SecurityGenerator().render(cfg or fc.ForgeOSConfig())}


def test_renders_jails_and_filter_only():
    files = _files()
    assert set(files) == {"/etc/fail2ban/jail.d/forgeos.conf",
                          "/etc/fail2ban/filter.d/forgeos-api.conf"}
    jail = files["/etc/fail2ban/jail.d/forgeos.conf"]
    for j in ("[sshd]", "[nginx-http-auth]", "[forgeos-api]", "[recidive]"):
        assert j in jail
    for gone in ("crowdsec", "aide", "rkhunter", "auditd", "samba"):
        assert gone not in jail.lower()


def test_recidive_reads_fail2ban_own_log():
    jail = _files()["/etc/fail2ban/jail.d/forgeos.conf"]
    m = re.search(r"\[recidive\]\n(.*?)\n\n", jail, re.S)
    assert m and "logpath = /var/log/fail2ban.log" in m.group(1)
    assert "bantime = 1w" in m.group(1)


def test_jail_switches():
    cfg = fc.ForgeOSConfig()
    cfg.security.fail2ban.jail_recidive = False
    jail = _files(cfg)["/etc/fail2ban/jail.d/forgeos.conf"]
    assert re.search(r"\[recidive\]\nenabled = false", jail)


def _apply_capture(monkeypatch, tmp_path, cfg):
    g = SecurityGenerator()
    calls = []
    ok = type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})
    monkeypatch.setattr(g, "_run", lambda cmd, check=True: (calls.append(cmd), ok())[1])
    monkeypatch.setattr(g, "_atomic_write", lambda *a, **k: None)
    monkeypatch.setattr(sg, "_have", lambda c: True)
    orig = sg.Path
    monkeypatch.setattr(sg, "Path",
                        lambda p: orig(str(tmp_path) + str(p))
                        if str(p).startswith("/var/log") else orig(p))
    g.apply(cfg, do_reload=True)
    return calls


def test_apply_enables_fail2ban_and_apparmor(monkeypatch, tmp_path):
    calls = _apply_capture(monkeypatch, tmp_path, fc.ForgeOSConfig())
    flat = [" ".join(c) for c in calls]
    assert "systemctl enable --now fail2ban" in flat
    assert "systemctl enable --now apparmor" in flat
    assert "systemctl reload fail2ban" in flat
    assert not any(t in " ".join(flat) for t in ("aide", "rkhunter", "auditd", "crowdsec", "ufw"))


def test_apply_disables_fail2ban_when_off(monkeypatch, tmp_path):
    cfg = fc.ForgeOSConfig(); cfg.security.fail2ban.enabled = False
    flat = [" ".join(c) for c in _apply_capture(monkeypatch, tmp_path, cfg)]
    assert "systemctl disable --now fail2ban" in flat
    assert "systemctl reload fail2ban" not in flat
    assert "systemctl enable --now apparmor" in flat   # apparmor unconditional


def test_apply_touches_both_logpaths(monkeypatch, tmp_path):
    _apply_capture(monkeypatch, tmp_path, fc.ForgeOSConfig())
    assert (tmp_path / "var/log/forgeos/auth.log").exists()
    assert (tmp_path / "var/log/fail2ban.log").exists()
