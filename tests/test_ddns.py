"""DDNS — provider clients, credential handling, endpoints.
All provider HTTP is mocked; no network calls in the suite."""
import json
import stat

import pytest

import ddns


@pytest.fixture
def store(tmp_path, monkeypatch):
    f = tmp_path / "ddns.json"
    monkeypatch.setattr(ddns, "DDNS_FILE", f)
    return f


# ── provider clients ───────────────────────────────────────────────
class TestDyndns2:
    def _reply(self, monkeypatch, body):
        seen = {}
        def fake(url, headers=None):
            seen["url"] = url; seen["headers"] = headers or {}
            return 200, body
        monkeypatch.setattr(ddns, "_get", fake)
        return seen

    def test_good_is_ok(self, monkeypatch):
        seen = self._reply(monkeypatch, "good 203.0.113.7\n")
        r = ddns._update_dyndns2("noip", "nas.example.com",
                                 {"username": "u", "password": "p"}, "203.0.113.7")
        assert r.status == "ok" and r.ip == "203.0.113.7"
        assert "dynupdate.no-ip.com" in seen["url"]
        assert seen["headers"]["Authorization"].startswith("Basic ")

    def test_nochg_counts_as_success(self, monkeypatch):
        self._reply(monkeypatch, "nochg 203.0.113.7")
        r = ddns._update_dyndns2("dyndns", "h", {"username": "u", "password": "p"}, "203.0.113.7")
        assert r.status == "nochg" and r.success

    @pytest.mark.parametrize("code", ["badauth", "nohost", "notfqdn", "abuse"])
    def test_fatal_codes_stop_retrying(self, monkeypatch, code):
        self._reply(monkeypatch, code)
        r = ddns._update_dyndns2("noip", "h", {"username": "u", "password": "p"}, "203.0.113.7")
        assert r.status == "fatal" and not r.success
        assert r.message                      # a human-readable reason, not the raw code

    @pytest.mark.parametrize("code", ["911", "dnserr"])
    def test_retryable_codes(self, monkeypatch, code):
        self._reply(monkeypatch, code)
        r = ddns._update_dyndns2("noip", "h", {"username": "u", "password": "p"}, "203.0.113.7")
        assert r.status == "retry"

    def test_missing_credentials_is_fatal(self):
        r = ddns._update_dyndns2("noip", "h", {}, "203.0.113.7")
        assert r.status == "fatal"

    def test_sends_a_user_agent(self, monkeypatch):
        # the dyndns2 spec requires one; clients without it get refused
        assert ddns.USER_AGENT


class TestDuckDns:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(ddns, "_get", lambda u, h=None: (200, "OK"))
        r = ddns._update_duckdns("mybox", {"token": "t"}, "203.0.113.7")
        assert r.status == "ok"

    def test_ko_is_fatal(self, monkeypatch):
        monkeypatch.setattr(ddns, "_get", lambda u, h=None: (200, "KO"))
        r = ddns._update_duckdns("mybox", {"token": "t"}, "203.0.113.7")
        assert r.status == "fatal"

    def test_strips_duckdns_suffix(self, monkeypatch):
        """Passing the full x.duckdns.org is a documented way to get KO."""
        seen = {}
        def fake(u, h=None):
            seen["url"] = u; return 200, "OK"
        monkeypatch.setattr(ddns, "_get", fake)
        ddns._update_duckdns("mybox.duckdns.org", {"token": "t"}, "203.0.113.7")
        assert "domains=mybox&" in seen["url"]

    def test_token_required(self):
        assert ddns._update_duckdns("h", {}, "203.0.113.7").status == "fatal"


class TestCloudflare:
    def _api(self, monkeypatch, record_ip="198.51.100.1", patch_ok=True):
        calls = []
        def fake(url, token, method="GET", payload=None):
            calls.append((method, url, payload))
            if "/zones?" in url:
                return 200, {"result": [{"id": "zone1"}]}
            if "/dns_records?" in url:
                return 200, {"result": [{"id": "rec1", "content": record_ip}]}
            return (200, {"success": True}) if patch_ok else \
                   (400, {"success": False, "errors": [{"message": "nope"}]})
        monkeypatch.setattr(ddns, "_json_req", fake)
        return calls

    def test_updates_via_patch(self, monkeypatch):
        calls = self._api(monkeypatch)
        r = ddns._update_cloudflare("nas.example.com", {"token": "t"}, "203.0.113.7")
        assert r.status == "ok"
        # PATCH, not PUT — only content changes
        assert calls[-1][0] == "PATCH"
        assert calls[-1][2] == {"content": "203.0.113.7"}

    def test_same_ip_is_nochg_without_writing(self, monkeypatch):
        calls = self._api(monkeypatch, record_ip="203.0.113.7")
        r = ddns._update_cloudflare("nas.example.com", {"token": "t"}, "203.0.113.7")
        assert r.status == "nochg"
        assert all(c[0] != "PATCH" for c in calls)

    def test_bad_token_is_fatal(self, monkeypatch):
        monkeypatch.setattr(ddns, "_json_req", lambda *a, **k: (403, {}))
        r = ddns._update_cloudflare("nas.example.com", {"token": "t"}, "203.0.113.7")
        assert r.status == "fatal" and r.code == "badauth"

    def test_missing_record_is_fatal(self, monkeypatch):
        def fake(url, token, method="GET", payload=None):
            if "/zones?" in url:
                return 200, {"result": [{"id": "z"}]}
            return 200, {"result": []}
        monkeypatch.setattr(ddns, "_json_req", fake)
        r = ddns._update_cloudflare("nas.example.com", {"token": "t"}, "203.0.113.7")
        assert r.status == "fatal" and r.code == "norecord"


class TestCustom:
    def test_template_substitution(self, monkeypatch):
        seen = {}
        def fake(u, h=None):
            seen["url"] = u; return 200, "fine"
        monkeypatch.setattr(ddns, "_get", fake)
        r = ddns._update_custom("nas.example.com",
                                {"url": "https://x.test/u?h={hostname}&a={ip}"},
                                "203.0.113.7")
        assert r.status == "ok"
        assert "h=nas.example.com" in seen["url"] and "a=203.0.113.7" in seen["url"]

    def test_non_http_url_rejected(self):
        r = ddns._update_custom("h", {"url": "file:///etc/passwd"}, "203.0.113.7")
        assert r.status == "fatal"


class TestUpdateDispatch:
    def test_unparseable_ip_is_not_sent(self):
        r = ddns.update({"provider": "duckdns", "hostname": "h",
                         "credentials": {"token": "t"}}, "not-an-ip")
        assert r.status == "retry" and r.code == "noip"

    def test_unknown_provider(self):
        assert ddns.update({"provider": "nope", "hostname": "h"}, "203.0.113.7").status == "fatal"


class TestPublicIp:
    def test_rejects_non_ip_response(self, monkeypatch):
        monkeypatch.setattr(ddns.urllib.request, "urlopen",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
        assert ddns.detect_public_ip() == ""


# ── storage + endpoints ────────────────────────────────────────────
class TestCredentialSafety:
    def test_public_view_never_includes_credentials(self, store):
        cfg = {"provider": "duckdns", "hostname": "h",
               "credentials": {"token": "SUPER-SECRET"}}
        view = ddns.public_view(cfg)
        assert "SUPER-SECRET" not in json.dumps(view)
        assert "credentials" not in view
        assert view["has_credentials"] is True

    def test_saved_file_is_0600(self, store):
        ddns.save({"provider": "duckdns", "credentials": {"token": "x"}})
        assert stat.S_IMODE(store.stat().st_mode) == 0o600


class TestDdnsEndpoints:
    def _put(self, client, headers, **over):
        body = {"provider": "duckdns", "hostname": "mybox", "enabled": True,
                "interval_minutes": 5, "credentials": {"token": "SECRET-TOKEN"}}
        body.update(over)
        return client.put("/api/net/ddns", headers=headers, json=body)

    def test_put_then_get_never_leaks_the_token(self, store, test_client, auth_headers):
        assert self._put(test_client, auth_headers).status_code == 200
        r = test_client.get("/api/net/ddns", headers=auth_headers)
        assert r.status_code == 200
        assert "SECRET-TOKEN" not in json.dumps(r.json())
        assert r.json()["has_credentials"] is True
        # ...but it really was stored
        assert ddns.load()["credentials"]["token"] == "SECRET-TOKEN"

    def test_put_response_never_leaks_the_token(self, store, test_client, auth_headers):
        r = self._put(test_client, auth_headers)
        assert "SECRET-TOKEN" not in json.dumps(r.json())

    def test_omitting_credentials_keeps_the_stored_ones(self, store, test_client, auth_headers):
        self._put(test_client, auth_headers)
        r = test_client.put("/api/net/ddns", headers=auth_headers, json={
            "provider": "duckdns", "hostname": "renamed", "interval_minutes": 10})
        assert r.status_code == 200
        stored = ddns.load()
        assert stored["hostname"] == "renamed"
        assert stored["credentials"]["token"] == "SECRET-TOKEN"

    def test_invalid_provider_rejected(self, store, test_client, auth_headers):
        assert self._put(test_client, auth_headers, provider="haxx").status_code == 422

    def test_control_chars_in_credentials_rejected(self, store, test_client, auth_headers):
        r = self._put(test_client, auth_headers, credentials={"token": "a\nb"})
        assert r.status_code == 422

    def test_delete_clears_credentials(self, store, test_client, auth_headers):
        self._put(test_client, auth_headers)
        assert test_client.delete("/api/net/ddns", headers=auth_headers).status_code == 200
        assert ddns.load() == {}

    def test_writes_require_admin(self, store, test_client, user_headers):
        assert self._put(test_client, user_headers).status_code == 403
        assert test_client.delete("/api/net/ddns", headers=user_headers).status_code == 403
        assert test_client.post("/api/net/ddns/test", headers=user_headers).status_code == 403

    def test_test_endpoint_reports_provider_result(self, store, test_client,
                                                   auth_headers, monkeypatch):
        self._put(test_client, auth_headers)
        monkeypatch.setattr(ddns, "detect_public_ip", lambda: "203.0.113.7")
        monkeypatch.setattr(ddns, "_get", lambda u, h=None: (200, "OK"))
        r = test_client.post("/api/net/ddns/test", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert ddns.load()["last_ip"] == "203.0.113.7"

    def test_test_endpoint_surfaces_failure(self, store, test_client,
                                            auth_headers, monkeypatch):
        self._put(test_client, auth_headers)
        monkeypatch.setattr(ddns, "detect_public_ip", lambda: "203.0.113.7")
        monkeypatch.setattr(ddns, "_get", lambda u, h=None: (200, "KO"))
        r = test_client.post("/api/net/ddns/test", headers=auth_headers)
        assert r.json()["success"] is False
        assert r.json()["status"] == "fatal"

    def test_test_without_config_is_400(self, store, test_client, auth_headers):
        assert test_client.post("/api/net/ddns/test",
                                headers=auth_headers).status_code == 400
