"""Tests for the v2 nginx generator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.nginx import CONFD_DIR, VHOST_DIR, NginxGenerator  # noqa: E402


def _cfg(*vhosts):
    cfg = fc.ForgeOSConfig()
    cfg.nginx.vhosts = list(vhosts)
    return cfg


def _vhost_files(files):
    """Just the per-site vhost files (exclude conf.d include + default-deny)."""
    return [f for f in files
            if f.path.startswith(VHOST_DIR) and not f.path.endswith("00-default-deny.conf")]


def _first_vhost(cfg):
    return _vhost_files(NginxGenerator().render(cfg))[0].content


def test_disabled_renders_nothing():
    cfg = fc.ForgeOSConfig()
    cfg.nginx.enabled = False
    cfg.nginx.vhosts = [fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080)]
    assert NginxGenerator().render(cfg) == []


def test_no_vhosts_renders_nothing():
    assert NginxGenerator().render(fc.ForgeOSConfig()) == []


def test_emits_confd_include():
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    files = NginxGenerator().render(cfg)
    inc = [f for f in files if f.path == f"{CONFD_DIR}/forgeos.conf"]
    assert len(inc) == 1
    # the include must pull in our vhost dir (stock nginx ignores forgeos.d)
    assert f"include {VHOST_DIR}/*.conf;" in inc[0].content


def test_one_file_per_vhost():
    cfg = _cfg(
        fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080),
        fc.NginxVhost(name="grafana", domain="grafana.nas.local", upstream_port=3000),
    )
    paths = {f.path for f in _vhost_files(NginxGenerator().render(cfg))}
    assert paths == {f"{VHOST_DIR}/ui.conf", f"{VHOST_DIR}/grafana.conf"}


def test_vhost_has_upstream_and_servername():
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "server 127.0.0.1:5080;" in c
    assert "server_name nas.local" in c   # may also carry _ when default
    assert "proxy_pass http://forgeos_ui;" in c


def test_single_vhost_is_default_server():
    # A lone vhost must be default_server so the box answers on its IP and
    # localhost, not only its domain (the bug that 444'd real access).
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "default_server" in c
    assert "server_name nas.local _;" in c


def test_forgeos_ui_is_default_not_app_vhosts():
    # forgeos-ui owns the catch-all; app vhosts match only their server_name.
    cfg = _cfg(
        fc.NginxVhost(name="grafana", domain="grafana.nas.local", upstream_port=3000),
        fc.NginxVhost(name="forgeos-ui", domain="nas.local", upstream_port=5080),
    )
    files = {f.path.split("/")[-1]: f.content for f in NginxGenerator().render(cfg)}
    assert "default_server" in files["forgeos-ui.conf"]
    assert "default_server" not in files["grafana.conf"]


def test_websocket_emits_upgrade_headers():
    cfg = _cfg(fc.NginxVhost(name="ws", domain="ws.nas.local", upstream_port=8070, websocket=True))
    c = _first_vhost(cfg)
    assert "proxy_set_header Upgrade $http_upgrade;" in c
    # Connection now follows the upgrade map (fixes keepalive hang on plain
    # requests), not a hardcoded "upgrade".
    assert "proxy_set_header Connection $forgeos_connection_upgrade;" in c


def test_non_websocket_omits_upgrade_headers():
    cfg = _cfg(fc.NginxVhost(name="plain", domain="p.nas.local", upstream_port=8085))
    c = _first_vhost(cfg)
    assert "Upgrade $http_upgrade" not in c


def test_cert_falls_back_to_snakeoil_when_no_le(monkeypatch):
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "ssl-cert-snakeoil.pem" in c


def test_rejects_bad_port():
    with pytest.raises(ValueError):
        fc.NginxVhost(name="x", domain="d", upstream_port=99999)


def test_rejects_duplicate_vhosts():
    with pytest.raises(ValueError):
        fc.NginxConfig(vhosts=[
            fc.NginxVhost(name="ui", domain="a", upstream_port=80),
            fc.NginxVhost(name="UI", domain="b", upstream_port=81),
        ])


def test_apply_creates_vhost_dir(tmp_path, monkeypatch):
    import generators.nginx as ng
    monkeypatch.setattr(ng, "VHOST_DIR", str(tmp_path / "etc" / "nginx" / "forgeos.d"))
    monkeypatch.setattr(ng, "CONFD_DIR", str(tmp_path / "etc" / "nginx" / "conf.d"))
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    written = ng.NginxGenerator().apply(cfg, do_reload=False)
    assert (tmp_path / "etc" / "nginx" / "forgeos.d" / "ui.conf").exists()
    assert (tmp_path / "etc" / "nginx" / "conf.d" / "forgeos.conf").exists()
    # include + one vhost (no separate default-deny anymore — the UI vhost is
    # itself the default_server)
    assert len(written) == 2


def test_apply_removes_stale_vhosts(tmp_path, monkeypatch):
    # Regression: a stale 00-default-deny.conf (return 444, default_server)
    # left on disk after we stopped generating it kept dropping ALL traffic
    # (ERR_EMPTY_RESPONSE). apply() must reconcile forgeos.d/ — remove any
    # ForgeOS .conf it no longer produces.
    import sys
    sys.path.insert(0, "src")
    import generators.nginx as ng
    import forgeos_config as fc

    monkeypatch.setattr(ng, "VHOST_DIR", str(tmp_path))
    monkeypatch.setattr(ng, "CONFD_DIR", str(tmp_path))
    (tmp_path / "00-default-deny.conf").write_text("server { return 444; }")
    (tmp_path / "old-app.conf").write_text("server {}")

    cfg = fc.ForgeOSConfig()
    cfg.nginx.vhosts.append(
        fc.NginxVhost(name="forgeos-ui", domain="nas.local",
                      upstream_port=5080, websocket=True))
    gen = ng.NginxGenerator()
    gen.reload = lambda: None
    gen.apply(cfg, do_reload=False)

    names = {p.name for p in tmp_path.glob("*.conf")}
    assert "00-default-deny.conf" not in names   # stale dropper removed
    assert "old-app.conf" not in names           # stale app vhost removed
    assert "forgeos-ui.conf" in names            # current vhost kept


# --- N1: advanced proxy options ---

def test_defaults_preserve_legacy_behaviour():
    # a vhost defined the old way (name/domain/port) must still emit the same
    # hardcoded-era directives: 301 redirect, http2 on, HSTS, localhost http upstream
    c = _first_vhost(_cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080)))
    assert "return 301 https://$host$request_uri;" in c
    assert "http2 on;" in c
    assert "Strict-Transport-Security" in c
    assert "server 127.0.0.1:5080;" in c
    assert "proxy_pass http://forgeos_ui;" in c


def test_custom_upstream_host_and_scheme():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=9000,
                                        upstream_host="10.0.0.50", upstream_scheme="https")))
    assert "server 10.0.0.50:9000;" in c
    assert "proxy_pass https://forgeos_a;" in c


def test_http2_can_be_disabled():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, http2=False)))
    assert "http2 on;" not in c


def test_hsts_can_be_disabled():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, hsts=False)))
    assert "Strict-Transport-Security" not in c


def test_force_ssl_off_serves_http_instead_of_redirecting():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, force_ssl=False)))
    assert "return 301" not in c
    # the :80 server now proxies (the location appears twice: :80 and :443)
    assert c.count("proxy_pass http://forgeos_a;") == 2


def test_client_max_body_size_and_timeout():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                                        client_max_body_size="200m", proxy_read_timeout=300)))
    assert "client_max_body_size 200m;" in c
    assert "proxy_read_timeout 300s;" in c


def test_gzip_toggle():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, gzip=True)))
    assert "gzip on;" in c
    plain = _first_vhost(_cfg(fc.NginxVhost(name="b", domain="b.lan", upstream_port=80)))
    assert "gzip on;" not in plain


def test_block_common_exploits():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                                        block_common_exploits=True)))
    assert "return 403;" in c


def test_ip_allowlist_emits_allow_then_deny_all():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                                        allow_ips=["10.0.0.0/24", "192.168.1.5"])))
    assert "allow 10.0.0.0/24;" in c
    assert "allow 192.168.1.5;" in c
    assert "deny all;" in c


def test_ip_blocklist_emits_deny():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                                        deny_ips=["1.2.3.4"])))
    assert "deny 1.2.3.4;" in c


def test_custom_snippet_is_injected():
    c = _first_vhost(_cfg(fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                                        custom_snippet='add_header X-Test "1";')))
    assert 'add_header X-Test "1";' in c


def test_invalid_ip_rejected():
    with pytest.raises(ValueError):
        fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, allow_ips=["999.1.1.1"])


def test_invalid_body_size_rejected():
    with pytest.raises(ValueError):
        fc.NginxVhost(name="a", domain="a.lan", upstream_port=80, client_max_body_size="big")


def test_upstream_host_rejects_injection():
    with pytest.raises(ValueError):
        fc.NginxVhost(name="a", domain="a.lan", upstream_port=80,
                      upstream_host="127.0.0.1; }")


class TestSharedCertSelection:
    """cert_name lets a vhost point at a shared/wildcard cert dir instead of
    one named after its own domain — the whole point of issue-once-select-many."""

    def test_cert_name_selects_shared_dir(self, tmp_path, monkeypatch):
        # wildcard cert lives at live/example.com/, vhost is mail.example.com
        live = tmp_path / "example.com"; live.mkdir()
        (live / "fullchain.pem").write_text("x"); (live / "privkey.pem").write_text("y")
        import generators.nginx as ng
        monkeypatch.setattr(ng, "Path", lambda p: tmp_path / str(p).split("/live/")[-1]
                            if "/live/" in str(p) else Path(p))
        cert, key = ng.NginxGenerator._cert_paths("example.com")
        assert cert.endswith("example.com/fullchain.pem")

    def test_cert_name_defaults_to_domain(self):
        v = fc.NginxVhost(name="m", domain="mail.example.com", upstream_port=8080)
        assert v.cert_name == ""            # "" => generator uses domain

    def test_cert_name_in_dump(self):
        v = fc.NginxVhost(name="m", domain="mail.example.com", upstream_port=8080,
                          cert_name="example.com")
        assert v.model_dump()["cert_name"] == "example.com"

    def test_cert_name_rejects_traversal(self):
        for bad in ("../etc", "a/b", "..", "x\x00y"):
            with pytest.raises(Exception):
                fc.NginxVhost(name="m", domain="d.example.com",
                              upstream_port=80, cert_name=bad)

    def test_generator_uses_cert_name(self, tmp_path, monkeypatch):
        # vhost mail.example.com with cert_name=example.com must emit the
        # example.com cert path, NOT mail.example.com.
        import generators.nginx as ng
        def fake_paths(cert_name, external=None):
            return (f"/etc/letsencrypt/live/{cert_name}/fullchain.pem",
                    f"/etc/letsencrypt/live/{cert_name}/privkey.pem")
        monkeypatch.setattr(ng.NginxGenerator, "_cert_paths", staticmethod(fake_paths))
        cfg = _cfg(fc.NginxVhost(name="mail", domain="mail.example.com",
                                 upstream_port=8080, cert_name="example.com",
                                 force_ssl=True))
        out = _vhost_files(ng.NginxGenerator().render(cfg))[0].content
        assert "/live/example.com/fullchain.pem" in out
        assert "/live/mail.example.com/" not in out


class TestExternalCertResolution:
    def test_external_cert_wins_over_le(self, tmp_path, monkeypatch):
        import generators.nginx as ng
        # external cert present on disk
        ext_fc = tmp_path / "ext-fc.pem"; ext_fc.write_text("x")
        ext_pk = tmp_path / "ext-pk.pem"; ext_pk.write_text("y")
        cert, key = ng.NginxGenerator._cert_paths(
            "wild", {"wild": (str(ext_fc), str(ext_pk))})
        assert cert == str(ext_fc) and key == str(ext_pk)

    def test_external_missing_files_falls_through(self, tmp_path):
        import generators.nginx as ng
        cert, key = ng.NginxGenerator._cert_paths(
            "wild", {"wild": ("/nope/fc.pem", "/nope/pk.pem")})
        # neither external (missing) nor LE -> snakeoil
        assert "snakeoil" in cert

    def test_generator_uses_external_cert(self, tmp_path, monkeypatch):
        import generators.nginx as ng
        ext_fc = tmp_path / "fc.pem"; ext_fc.write_text("x")
        ext_pk = tmp_path / "pk.pem"; ext_pk.write_text("y")
        cfg = _cfg(fc.NginxVhost(name="mail", domain="mail.example.com",
                                 upstream_port=8081, cert_name="wildcert",
                                 force_ssl=True))
        cfg.nginx.external_certs = [fc.ExternalCert(
            name="wildcert", fullchain_path=str(ext_fc), privkey_path=str(ext_pk))]
        out = _vhost_files(ng.NginxGenerator().render(cfg))[0].content
        assert str(ext_fc) in out


class TestExternalCertModel:
    def test_rejects_bad_name(self):
        for bad in ("../x", "a/b", "..", "x y"):
            with pytest.raises(Exception):
                fc.ExternalCert(name=bad, fullchain_path="/a", privkey_path="/b")

    def test_valid(self):
        c = fc.ExternalCert(name="example.com", fullchain_path="/a/fc.pem", privkey_path="/a/pk.pem")
        assert c.name == "example.com"


class TestDomainCertMatching:
    def test_vhost_inherits_matching_domain_cert(self, monkeypatch):
        import generators.nginx as ng
        # domain example.com managed; vhost test.example.com should use
        # the example.com cert dir (named after the domain).
        def fake_paths(cert_name, external=None):
            return (f"/etc/letsencrypt/live/{cert_name}/fullchain.pem",
                    f"/etc/letsencrypt/live/{cert_name}/privkey.pem")
        monkeypatch.setattr(ng.NginxGenerator, "_cert_paths", staticmethod(fake_paths))
        cfg = _cfg(fc.NginxVhost(name="t", domain="test.example.com",
                                 upstream_port=8081, force_ssl=True))
        cfg.nginx.domains = [fc.Domain(name="example.com", provider="porkbun", wildcard=True)]
        out = _vhost_files(ng.NginxGenerator().render(cfg))[0].content
        assert "/live/example.com/fullchain.pem" in out
        assert "/live/test.example.com/" not in out

    def test_longest_domain_wins(self):
        import generators.nginx as ng
        m = ng.NginxGenerator._match_domain(
            "a.sub.example.com", ["example.com", "sub.example.com"])
        assert m == "sub.example.com"

    def test_no_match_returns_none(self):
        import generators.nginx as ng
        assert ng.NginxGenerator._match_domain("nas.local", ["example.com"]) is None

    def test_exact_domain_matches(self):
        import generators.nginx as ng
        assert ng.NginxGenerator._match_domain("example.com", ["example.com"]) == "example.com"


class TestDomainModel:
    def test_valid(self):
        d = fc.Domain(name="example.com", provider="porkbun", wildcard=True)
        assert d.name == "example.com" and d.wildcard

    def test_rejects_bad_domain(self):
        for bad in ("not a domain", "-bad.com", "x"):
            with pytest.raises(Exception):
                fc.Domain(name=bad, provider="porkbun")

    def test_provider_code_normalized(self):
        p = fc.DnsProvider(code="PorkBun", creds_path="/x")
        assert p.code == "porkbun"

    def test_provider_rejects_bad_code(self):
        with pytest.raises(Exception):
            fc.DnsProvider(code="bad code!", creds_path="/x")


class TestExploitBlockRegexValid:
    """The block_common_exploits traversal regex was malformed
    (\\.\\./|\\.\\.\\\\) -> nginx pcre2_compile() 'missing closing parenthesis',
    which failed `nginx -t` and took down EVERY vhost. Guard the rendered
    form so it can't regress."""

    def test_traversal_regex_is_balanced(self):
        cfg = _cfg(fc.NginxVhost(name="t", domain="t.example.com",
                                 upstream_port=8081, block_common_exploits=True))
        out = _vhost_files(NginxGenerator().render(cfg))[0].content
        # the traversal rule is the one containing the escaped ".." dots
        cand = [l for l in out.splitlines()
                if "return 403" in l and r"\." in l]
        assert cand, "traversal block rule missing"
        rule = cand[0]
        assert rule.count("(") == rule.count(")"), rule   # balanced (was the bug)
        assert r"\)" not in rule.split("~*")[1], rule       # no stray escaped paren
        import re
        m = re.search(r'~\*\s+"(.*?)"\)\s*\{', rule)
        assert m, "could not extract quoted pattern: " + rule
        re.compile(m.group(1))                              # raises if malformed

    def test_no_exploit_block_when_disabled(self):
        cfg = _cfg(fc.NginxVhost(name="t", domain="t.example.com",
                                 upstream_port=8081, block_common_exploits=False))
        out = _vhost_files(NginxGenerator().render(cfg))[0].content
        assert "return 403" not in out


class TestProxyKeepaliveHang:
    """Upstream has `keepalive 32` but the location only set proxy_http_version
    1.1 when websocket was on. Without it, keepalive on an HTTP/1.0 proxy hangs
    (0 bytes back) against keepalive-capable backends (aiohttp/MeTube). Every
    vhost must set http/1.1 + a correct Connection header."""

    def test_non_ws_vhost_has_http11_and_cleared_connection(self):
        cfg = _cfg(fc.NginxVhost(name="t", domain="t.example.com",
                                 upstream_port=8081, websocket=False, force_ssl=False))
        out = _vhost_files(NginxGenerator().render(cfg))[0].content
        assert "proxy_http_version 1.1;" in out
        assert 'proxy_set_header Connection "";' in out          # keepalive needs empty
        assert 'Connection "upgrade"' not in out                  # not for plain vhost

    def test_ws_vhost_uses_upgrade_map(self):
        cfg = _cfg(fc.NginxVhost(name="w", domain="w.example.com",
                                 upstream_port=8081, websocket=True, force_ssl=False))
        out = _vhost_files(NginxGenerator().render(cfg))[0].content
        assert "proxy_http_version 1.1;" in out
        assert "proxy_set_header Connection $forgeos_connection_upgrade;" in out
        assert "proxy_set_header Upgrade $http_upgrade;" in out

    def test_connection_upgrade_map_defined_once_in_confd(self):
        cfg = _cfg(fc.NginxVhost(name="t", domain="t.example.com", upstream_port=8081))
        files = {f.path: f.content for f in NginxGenerator().render(cfg)}
        confd = files[f"{CONFD_DIR}/forgeos.conf"]
        assert "map $http_upgrade $forgeos_connection_upgrade" in confd
        assert "default upgrade;" in confd
