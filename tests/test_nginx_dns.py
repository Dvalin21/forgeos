"""
DNS-01 / certbot-dns-multi tests (Reverse Proxy N2): provider credential
management (write-only 0600 store) and the DNS-01 cert request command.

The credentials file path is module-level so we isolate it to a temp file; the
certbot invocation is checked by mocking subprocess.run (we never run certbot).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import nginx_api  # noqa: E402


def _mock_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


@pytest.fixture
def dns_creds(tmp_path, monkeypatch):
    """Isolate the credentials file to a temp path (never touch /etc/letsencrypt)."""
    p = tmp_path / "dns-multi.ini"
    monkeypatch.setattr(nginx_api, "DNS_CREDS_FILE", p)
    return p


class TestDnsProviderConfig:
    def test_get_requires_admin(self, test_client, user_headers, dns_creds):
        assert test_client.get("/api/nginx/acme/dns", headers=user_headers).status_code == 403

    def test_put_requires_admin(self, test_client, user_headers, dns_creds):
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "cloudflare", "credentials": {"X_TOKEN": "y"}},
                            headers=user_headers)
        assert r.status_code == 403

    def test_unconfigured_returns_false(self, test_client, auth_headers, dns_creds):
        r = test_client.get("/api/nginx/acme/dns", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"configured": False, "provider": None}

    def test_put_writes_0600_creds_file(self, test_client, auth_headers, dns_creds):
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "cloudflare",
                                  "credentials": {"CLOUDFLARE_DNS_API_TOKEN": "secret123"}},
                            headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["provider"] == "cloudflare"
        content = dns_creds.read_text()
        assert "dns_multi_provider = cloudflare" in content
        assert "CLOUDFLARE_DNS_API_TOKEN = secret123" in content
        assert (dns_creds.stat().st_mode & 0o777) == 0o600   # secrets

    def test_get_after_put_never_echoes_secret(self, test_client, auth_headers, dns_creds):
        test_client.put("/api/nginx/acme/dns",
                        json={"provider": "cloudflare",
                              "credentials": {"CLOUDFLARE_DNS_API_TOKEN": "topsecret"}},
                        headers=auth_headers)
        r = test_client.get("/api/nginx/acme/dns", headers=auth_headers)
        assert r.json() == {"configured": True, "provider": "cloudflare"}
        assert "topsecret" not in r.text

    def test_rejects_bad_provider(self, test_client, auth_headers, dns_creds):
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "Cloud Flare!", "credentials": {"X_TOKEN": "y"}},
                            headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_bad_credential_key(self, test_client, auth_headers, dns_creds):
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "cloudflare", "credentials": {"bad-key": "y"}},
                            headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_newline_in_value_injection(self, test_client, auth_headers, dns_creds):
        # a newline could inject another ini directive — must be rejected
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "cloudflare",
                                  "credentials": {"CF_TOKEN": "y\ndns_multi_provider = evil"}},
                            headers=auth_headers)
        assert r.status_code == 400
        assert not dns_creds.exists()   # nothing written on rejection

    def test_rejects_empty_credentials(self, test_client, auth_headers, dns_creds):
        r = test_client.put("/api/nginx/acme/dns",
                            json={"provider": "cloudflare", "credentials": {}},
                            headers=auth_headers)
        assert r.status_code == 400

    def test_delete_removes_creds(self, test_client, auth_headers, dns_creds):
        test_client.put("/api/nginx/acme/dns",
                        json={"provider": "cloudflare", "credentials": {"CF_TOKEN": "y"}},
                        headers=auth_headers)
        assert dns_creds.exists()
        r = test_client.delete("/api/nginx/acme/dns", headers=auth_headers)
        assert r.status_code == 200 and r.json()["removed"] is True
        assert not dns_creds.exists()
        assert test_client.get("/api/nginx/acme/dns",
                               headers=auth_headers).json()["configured"] is False


class TestDnsCertRequest:
    def test_requires_admin(self, test_client, user_headers, dns_creds):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        r = test_client.post("/api/nginx/cert/dns",
                             json={"domain": "example.com"}, headers=user_headers)
        assert r.status_code == 403

    def test_requires_provider_configured(self, test_client, auth_headers, dns_creds):
        # no creds file present
        r = test_client.post("/api/nginx/cert/dns",
                             json={"domain": "example.com"}, headers=auth_headers)
        assert r.status_code == 400

    def _capture_start_task(self, monkeypatch):
        import nginx_api
        calls = []
        monkeypatch.setattr(nginx_api, "_start_task",
                            lambda cmd, tool, action, timeout=600: (calls.append((cmd, timeout)), "tid-1")[1])
        return calls

    def test_builds_certbot_dns_multi_command(self, test_client, auth_headers, dns_creds, monkeypatch):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        tasks = self._capture_start_task(monkeypatch)
        r = test_client.post("/api/nginx/cert/dns",
                             json={"domain": "example.com", "email": "me@example.com"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["task_id"] == "tid-1"
        cmd, timeout = tasks[0]
        # propagation ceiling must cover the slowest provider default (3600s)
        assert timeout >= 3700
        assert "dns-multi" in cmd
        assert "--dns-multi-credentials" in cmd
        assert "-d" in cmd and "example.com" in cmd
        assert "*.example.com" not in cmd          # no wildcard unless asked

    def test_wildcard_adds_star_label(self, test_client, auth_headers, dns_creds, monkeypatch):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        tasks = self._capture_start_task(monkeypatch)
        r = test_client.post("/api/nginx/cert/dns",
                             json={"domain": "example.com", "wildcard": True},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        cmd, _ = tasks[0]
        assert "*.example.com" in cmd
        assert "example.com" in cmd                # apex + wildcard

    def test_rejects_bad_domain(self, test_client, auth_headers, dns_creds):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        r = test_client.post("/api/nginx/cert/dns",
                             json={"domain": "bad;rm -rf"}, headers=auth_headers)
        assert r.status_code == 400


class TestVhostCertState:
    def test_list_reports_cert_state(self, test_client, auth_headers, tmp_path, monkeypatch):
        import nginx_api
        # exact-domain LE dir present
        live = tmp_path / "live" / "app.example.com"
        live.mkdir(parents=True); (live / "fullchain.pem").write_text("x")
        real_exists = nginx_api.Path.exists
        monkeypatch.setattr(nginx_api, "_cert_state",
                            lambda d: "letsencrypt" if d == "app.example.com" else "self-signed")
        r = test_client.get("/api/nginx/vhosts", headers=auth_headers)
        assert r.status_code == 200
        for v in r.json()["vhosts"]:
            assert v["cert"] in ("letsencrypt", "self-signed")

    def test_cert_state_wildcard_parent(self, tmp_path, monkeypatch):
        import sys; sys.path.insert(0, "src")
        import nginx_api
        def fake_exists(self):
            return str(self) == "/etc/letsencrypt/live/example.com/fullchain.pem"
        monkeypatch.setattr(type(nginx_api.Path("/x")), "exists", fake_exists)
        assert nginx_api._cert_state("app.example.com") == "letsencrypt"   # parent wildcard
        assert nginx_api._cert_state("example.com") == "letsencrypt"
        assert nginx_api._cert_state("other.net") == "self-signed"

    def test_apply_endpoint(self, test_client, auth_headers, user_headers, monkeypatch):
        import nginx_api
        called = []
        monkeypatch.setattr(nginx_api, "_apply_nginx", lambda cfg: called.append(1))
        assert test_client.post("/api/nginx/apply", headers=user_headers).status_code == 403
        r = test_client.post("/api/nginx/apply", headers=auth_headers)
        assert r.status_code == 200 and called


class TestCertsEndpoint:
    def test_lists_issued_certs_with_sans(self, test_client, auth_headers, tmp_path, monkeypatch):
        import nginx_api
        live = tmp_path / "example.com"; live.mkdir()
        (live / "fullchain.pem").write_text("x")
        monkeypatch.setattr(nginx_api, "Path", lambda p: tmp_path if str(p) == "/etc/letsencrypt/live" else __import__("pathlib").Path(p))
        monkeypatch.setattr(nginx_api, "_cert_sans", lambda fc: ["example.com", "*.example.com"])
        r = test_client.get("/api/nginx/certs", headers=auth_headers)
        assert r.status_code == 200
        certs = r.json()["certs"]
        assert certs and certs[0]["name"] == "example.com"
        assert "*.example.com" in certs[0]["covers"]

    def test_certs_requires_auth(self, test_client):
        assert test_client.get("/api/nginx/certs").status_code in (401, 403)


class TestCertLifecycleEndpoints:
    def test_register_external_cert(self, test_client, auth_headers, tmp_path):
        import forgeos_config as fcfg
        fcp = tmp_path / "fc.pem"; fcp.write_text("x")
        pk = tmp_path / "pk.pem"; pk.write_text("y")
        r = test_client.post("/api/nginx/certs/register", headers=auth_headers,
                             json={"name": "wild", "fullchain_path": str(fcp),
                                   "privkey_path": str(pk)})
        assert r.status_code == 200, r.text
        assert any(c.name == "wild" for c in fcfg.load().nginx.external_certs)

    def test_register_missing_file_400(self, test_client, auth_headers):
        r = test_client.post("/api/nginx/certs/register", headers=auth_headers,
                             json={"name": "x", "fullchain_path": "/nope/a",
                                   "privkey_path": "/nope/b"})
        assert r.status_code == 400

    def test_register_requires_admin(self, test_client, user_headers, tmp_path):
        fcp = tmp_path / "fc.pem"; fcp.write_text("x")
        assert test_client.post("/api/nginx/certs/register", headers=user_headers,
                                json={"name": "x", "fullchain_path": str(fcp),
                                      "privkey_path": str(fcp)}).status_code == 403

    def test_delete_refuses_if_in_use(self, test_client, auth_headers, tmp_path):
        import forgeos_config as fcfg
        fcp = tmp_path / "fc.pem"; fcp.write_text("x")
        pk = tmp_path / "pk.pem"; pk.write_text("y")
        cfg = fcfg.load()
        cfg.nginx.external_certs.append(fcfg.ExternalCert(name="shared", fullchain_path=str(fcp), privkey_path=str(pk)))
        cfg.nginx.vhosts.append(fcfg.NginxVhost(name="mail", domain="mail.example.com", upstream_port=80, cert_name="shared"))
        fcfg.save(cfg)
        r = test_client.delete("/api/nginx/certs/shared", headers=auth_headers)
        assert r.status_code == 409

    def test_delete_external_unregisters(self, test_client, auth_headers, tmp_path):
        import forgeos_config as fcfg
        fcp = tmp_path / "fc.pem"; fcp.write_text("x")
        pk = tmp_path / "pk.pem"; pk.write_text("y")
        cfg = fcfg.load()
        cfg.nginx.external_certs.append(fcfg.ExternalCert(name="lonely", fullchain_path=str(fcp), privkey_path=str(pk)))
        fcfg.save(cfg)
        r = test_client.delete("/api/nginx/certs/lonely", headers=auth_headers)
        assert r.status_code == 200 and r.json()["source"] == "external"
        assert not any(c.name == "lonely" for c in fcfg.load().nginx.external_certs)


class TestDns01ApexWildcard:
    def _cap(self, monkeypatch):
        import nginx_api
        calls = []
        monkeypatch.setattr(nginx_api, "_start_task",
                            lambda cmd, tool, action, timeout=600: (calls.append(cmd), "t")[1])
        return calls

    def test_apex_only(self, test_client, auth_headers, dns_creds, monkeypatch):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        c = self._cap(monkeypatch)
        test_client.post("/api/nginx/cert/dns", headers=auth_headers,
                         json={"domain": "example.com", "apex": True, "wildcard": False})
        cmd = c[0]
        assert "example.com" in cmd and "*.example.com" not in cmd

    def test_wildcard_and_apex(self, test_client, auth_headers, dns_creds, monkeypatch):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        c = self._cap(monkeypatch)
        test_client.post("/api/nginx/cert/dns", headers=auth_headers,
                         json={"domain": "example.com", "apex": True, "wildcard": True})
        cmd = c[0]
        assert "example.com" in cmd and "*.example.com" in cmd

    def test_wildcard_only(self, test_client, auth_headers, dns_creds, monkeypatch):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        c = self._cap(monkeypatch)
        test_client.post("/api/nginx/cert/dns", headers=auth_headers,
                         json={"domain": "example.com", "apex": False, "wildcard": True})
        cmd = c[0]
        assert "*.example.com" in cmd
        # apex bare domain NOT a -d target (but IS the --cert-name)
        i = cmd.index("--cert-name")
        d_targets = [cmd[j+1] for j, tok in enumerate(cmd) if tok == "-d"]
        assert "example.com" not in d_targets

    def test_nothing_selected_400(self, test_client, auth_headers, dns_creds):
        dns_creds.write_text("dns_multi_provider = cloudflare\n")
        r = test_client.post("/api/nginx/cert/dns", headers=auth_headers,
                             json={"domain": "example.com", "apex": False, "wildcard": False})
        assert r.status_code == 400
