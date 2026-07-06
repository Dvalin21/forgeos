"""Security P2 — fail2ban that actually bans.

Chain under test: auth failure -> /var/log/forgeos/auth.log line with the real
client IP -> generated filter matches it -> generated jail reads it. Plus the
status/unban/config endpoints.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import forgeos_auth  # noqa: E402
import forgeos_config as fc  # noqa: E402
import security_api  # noqa: E402
from generators.security import SecurityGenerator  # noqa: E402

FILTER_RE = r"^.*forgeos-auth FAILED \S+ user=\S+ ip=(\S+)\s*$"  # <HOST> stand-in


@pytest.fixture
def auth_log(tmp_path, monkeypatch):
    p = tmp_path / "auth.log"
    monkeypatch.setattr(forgeos_auth, "AUTH_LOG", p)
    monkeypatch.setattr(forgeos_auth, "_auth_logger", None)
    yield p
    # detach the handler so the next test's logger points at its own file
    import logging
    lg = logging.getLogger("forgeos.authlog")
    for h in list(lg.handlers):
        lg.removeHandler(h)
    forgeos_auth._auth_logger = None


class TestAuthLogLine:
    def test_line_matches_filter_grammar(self, auth_log):
        forgeos_auth.log_auth_failure("LOGIN", "keith", "10.0.0.59")
        line = auth_log.read_text().strip()
        m = re.match(FILTER_RE, line)
        assert m, line
        assert m.group(1) == "10.0.0.59"

    def test_hostile_username_cannot_spoof_line(self, auth_log):
        forgeos_auth.log_auth_failure("LOGIN", "x ip=6.6.6.6\nfake", "10.0.0.59")
        lines = auth_log.read_text().strip().splitlines()
        assert len(lines) == 1                      # newline injection dead
        assert re.match(FILTER_RE, lines[0]).group(1) == "10.0.0.59"

    def test_never_raises(self, monkeypatch):
        monkeypatch.setattr(forgeos_auth, "AUTH_LOG", Path("/nonexistent/x/auth.log"))
        monkeypatch.setattr(forgeos_auth, "_auth_logger", None)
        forgeos_auth.log_auth_failure("LOGIN", "u", "1.2.3.4")   # must not throw

    def test_failed_login_writes_real_ip(self, test_client, auth_log):
        users = forgeos_auth.load_users()
        users["keith"] = {"hash": forgeos_auth.pwd_ctx.hash("right"), "role": "admin"}
        forgeos_auth.save_users(users)
        r = test_client.post("/api/auth/login",
                             json={"username": "keith", "password": "wrong"})
        assert r.status_code == 401
        line = auth_log.read_text().strip()
        assert "FAILED LOGIN user=keith" in line and "ip=testclient" in line


class TestJailRender:
    def _render(self, **f2b):
        cfg = fc.ForgeOSConfig()
        for k, v in f2b.items():
            setattr(cfg.security.fail2ban, k, v)
        files = {f.path: f.content for f in SecurityGenerator().render(cfg)}
        return files

    def test_renders_jail_and_filter(self):
        files = self._render()
        jail = files["/etc/fail2ban/jail.d/forgeos.conf"]
        filt = files["/etc/fail2ban/filter.d/forgeos-api.conf"]
        assert "logpath = /var/log/forgeos/auth.log" in jail
        assert "filter = forgeos-api" in jail
        assert "backend = systemd" in jail                     # sshd on trixie
        assert "samba" not in jail                             # folklore jail deleted
        assert "ip=<HOST>" in filt

    def test_tunables_flow(self):
        jail = self._render(bantime="1d", maxretry=3)["/etc/fail2ban/jail.d/forgeos.conf"]
        assert "bantime = 1d" in jail and "maxretry = 3" in jail

    def test_disable_switches(self):
        jail = self._render(jail_nginx=False)["/etc/fail2ban/jail.d/forgeos.conf"]
        assert re.search(r"\[nginx-http-auth\]\nenabled = false", jail)
        jail = self._render(enabled=False)["/etc/fail2ban/jail.d/forgeos.conf"]
        assert "enabled = true" not in jail                    # master off = all off

    def test_filter_regex_matches_logged_line(self, auth_log):
        forgeos_auth.log_auth_failure("2FA", "keith", "203.0.113.9")
        filt = self._render()["/etc/fail2ban/filter.d/forgeos-api.conf"]
        fr = re.search(r"failregex = (.*)", filt).group(1).replace("<HOST>", r"(?P<host>\S+)")
        m = re.match(fr, auth_log.read_text().strip())
        assert m and m.group("host") == "203.0.113.9"


class TestFail2banEndpoints:
    @pytest.fixture
    def run_capture(self, monkeypatch):
        calls = []
        out = ("Status for the jail: sshd\n"
               "|- Filter\n`- Actions\n   |- Currently banned: 1\n"
               "   |- Total banned:\t4\n   `- Banned IP list:\t198.51.100.7 203.0.113.5\n")
        security_api.set_helpers(run_args=lambda cmd, **kw: (calls.append(cmd), out)[1],
                                 audit=lambda *a, **k: None)
        yield calls

    def test_status_parses_bans(self, test_client, auth_headers, run_capture):
        d = test_client.get("/api/security/fail2ban", headers=auth_headers).json()
        sshd = next(j for j in d["jails"] if j["name"] == "sshd")
        assert sshd["banned"] == ["198.51.100.7", "203.0.113.5"]
        assert sshd["total"] == 4

    def test_unban_validates_and_calls(self, test_client, auth_headers, run_capture):
        assert test_client.post("/api/security/fail2ban/unban", json={"ip": "not-an-ip"},
                                headers=auth_headers).status_code == 400
        r = test_client.post("/api/security/fail2ban/unban", json={"ip": "198.51.100.7"},
                             headers=auth_headers)
        assert r.status_code == 200
        assert ["fail2ban-client", "unban", "198.51.100.7"] in run_capture

    def test_unban_requires_admin(self, test_client, user_headers, run_capture):
        assert test_client.post("/api/security/fail2ban/unban", json={"ip": "1.2.3.4"},
                                headers=user_headers).status_code == 403

    def test_config_put_persists(self, test_client, auth_headers, run_capture):
        applied = []
        security_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
        try:
            r = test_client.put("/api/security/fail2ban",
                                json={"maxretry": 3, "jail_nginx": False},
                                headers=auth_headers)
            assert r.status_code == 200, r.text
            assert r.json()["fail2ban"]["maxretry"] == 3
            assert test_client.put("/api/security/fail2ban", json={"bantime": "; rm"},
                                   headers=auth_headers).status_code == 400
            assert len(applied) == 1
        finally:
            security_api.set_apply(None)


def test_uvicorn_trusts_loopback_proxy_only():
    """Regression guard: without proxy_headers, every failure logs 127.0.0.1
    and fail2ban bans localhost."""
    src = (Path(__file__).resolve().parent.parent / "src" / "forgeos-api.py").read_text()
    assert "proxy_headers=True" in src
    assert 'forwarded_allow_ips="127.0.0.1"' in src


class TestUpdatesEndpoints:
    def test_get_defaults(self, test_client, auth_headers):
        d = test_client.get("/api/security/updates", headers=auth_headers).json()
        assert d == {"enabled": True, "auto_reboot": False, "reboot_time": "02:00"}

    def test_put_persists_and_validates(self, test_client, auth_headers):
        import security_api, forgeos_config as fc
        applied = []
        security_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
        try:
            r = test_client.put("/api/security/updates",
                                json={"auto_reboot": True, "reboot_time": "03:30"},
                                headers=auth_headers)
            assert r.status_code == 200 and r.json()["updates"]["reboot_time"] == "03:30"
            assert test_client.put("/api/security/updates", json={"reboot_time": "25:99"},
                                   headers=auth_headers).status_code == 400
            assert len(applied) == 1
        finally:
            security_api.set_apply(None)

    def test_put_requires_admin(self, test_client, user_headers):
        assert test_client.put("/api/security/updates", json={"enabled": False},
                               headers=user_headers).status_code == 403
