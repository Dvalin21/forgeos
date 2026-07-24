"""Network API — read layer + validated models (patch 1)."""
import pytest
from pydantic import ValidationError


class TestInterfaceConfigModel:
    def test_static_on_subnet_gateway_ok(self):
        from network_api import InterfaceConfig
        c = InterfaceConfig(name="ens18", method="static",
                            address="10.0.0.69/24", gateway="10.0.0.1", mtu=1500)
        assert c.gateway == "10.0.0.1"

    def test_static_off_subnet_gateway_rejected(self):
        from network_api import InterfaceConfig
        with pytest.raises((ValidationError, ValueError)):
            InterfaceConfig(name="ens18", method="static",
                            address="10.0.0.69/24", gateway="192.168.1.1")

    def test_static_requires_address(self):
        from network_api import InterfaceConfig
        with pytest.raises((ValidationError, ValueError)):
            InterfaceConfig(name="ens18", method="static")

    def test_dhcp_needs_no_address(self):
        from network_api import InterfaceConfig
        assert InterfaceConfig(name="ens18", method="dhcp").method == "dhcp"

    @pytest.mark.parametrize("bad", [
        {"name": "ens18;rm", "method": "dhcp"},
        {"name": "ens18", "method": "bridge"},
        {"name": "ens18", "method": "static", "address": "10.0.0.999/24"},
        {"name": "ens18", "method": "dhcp", "mtu": 100},
        {"name": "ens18", "method": "dhcp", "mtu": 99999},
        {"name": "ens18", "method": "dhcp", "dns": ["1.1.1.1", "nope"]},
    ])
    def test_invalid_rejected(self, bad):
        from network_api import InterfaceConfig
        with pytest.raises((ValidationError, ValueError)):
            InterfaceConfig(**bad)


class TestGlobalNetConfigModel:
    def test_valid(self):
        from network_api import GlobalNetConfig
        c = GlobalNetConfig(hostname="forgeos", domain="example.com",
                            dns=["1.1.1.1", "9.9.9.9"], gateway="10.0.0.1")
        assert c.hostname == "forgeos"

    @pytest.mark.parametrize("bad", [
        {"hostname": "-bad"},
        {"hostname": "a.b"},                       # dot isn't a single label
        {"hostname": "ok", "domain": "a..b"},
        {"hostname": "ok", "dns": ["not-ip"]},
        {"hostname": "ok", "gateway": "999.1.1.1"},
    ])
    def test_invalid_rejected(self, bad):
        from network_api import GlobalNetConfig
        with pytest.raises((ValidationError, ValueError)):
            GlobalNetConfig(**bad)


class TestStaticRouteModel:
    def test_valid(self):
        from network_api import StaticRoute
        r = StaticRoute(destination="10.8.0.0/24", gateway="10.0.0.1",
                        interface="ens18", metric=100)
        assert r.destination == "10.8.0.0/24"

    @pytest.mark.parametrize("bad", [
        {"destination": "notacidr", "gateway": "10.0.0.1"},
        {"destination": "10.8.0.0/24", "gateway": "999.1.1.1"},
        {"destination": "10.8.0.0/24", "gateway": "10.0.0.1", "metric": -1},
        {"destination": "10.8.0.0/24", "gateway": "10.0.0.1", "interface": "e;rm"},
    ])
    def test_invalid_rejected(self, bad):
        from network_api import StaticRoute
        with pytest.raises((ValidationError, ValueError)):
            StaticRoute(**bad)


class TestReadEndpoints:
    """Read endpoints parse `ip -j` output + resolv.conf. Mock the injected
    _run_args so no real network commands run."""

    def _mock_ip(self, monkeypatch):
        import network_api as n
        # `ip -j addr` carries addresses but NOT stats64
        addr_json = (
            '[{"ifname":"lo","operstate":"UNKNOWN","addr_info":[]},'
            '{"ifname":"ens18","operstate":"UP","address":"bc:24:11:f2:3b:1e",'
            '"mtu":1500,'
            '"addr_info":[{"family":"inet","local":"10.0.0.69","prefixlen":24},'
            '{"family":"inet6","local":"fe80::1","prefixlen":64,"scope":"link"}]},'
            '{"ifname":"docker0","operstate":"DOWN","addr_info":[]}]'
        )
        # `ip -s -j link` carries stats64 (real values from the target VM)
        link_json = (
            '[{"ifname":"ens18","stats64":{"rx":{"bytes":3800623959},'
            '"tx":{"bytes":204280987}}}]'
        )
        route_json = ('[{"dst":"default","gateway":"10.0.0.1","dev":"ens18"},'
                      '{"dst":"10.0.0.0/24","dev":"ens18","protocol":"kernel"}]')
        def fake_run(args, timeout=None):
            if args[:4] == ["ip", "-j", "-s", "link"]:
                return link_json
            if args[:3] == ["ip", "-j", "addr"]:
                return addr_json
            if args[:3] == ["ip", "-j", "route"]:
                return route_json
            if args[:1] == ["hostname"]:
                return "forgeos\n"
            return ""
        monkeypatch.setattr(n, "_run_args", fake_run)

    def test_interfaces_hides_lo_and_docker(self, test_client, auth_headers, monkeypatch):
        self._mock_ip(monkeypatch)
        r = test_client.get("/api/net/interfaces", headers=auth_headers)
        assert r.status_code == 200
        names = [i["name"] for i in r.json()["interfaces"]]
        assert names == ["ens18"]                  # lo + docker0 hidden
        eth = r.json()["interfaces"][0]
        assert eth["ipv4"] == ["10.0.0.69/24"]
        assert eth["mac"] == "bc:24:11:f2:3b:1e"
        assert eth["rx_bytes"] == 3800623959
        assert eth["tx_bytes"] == 204280987
        # link-local ipv6 excluded
        assert eth["ipv6"] == []

    def test_global_reads_gateway_and_dns(self, test_client, auth_headers, monkeypatch, tmp_path):
        import network_api as n
        self._mock_ip(monkeypatch)
        resolv = tmp_path / "resolv.conf"
        resolv.write_text("nameserver 1.1.1.1\nnameserver 9.9.9.9\n# comment\n")
        monkeypatch.setattr(n, "RESOLV_CONF", resolv)
        monkeypatch.setattr(n, "_conf_get", lambda k, d="": {"DOMAIN": "example.com"}.get(k, d))
        r = test_client.get("/api/net/global", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["hostname"] == "forgeos"
        assert body["gateway"] == "10.0.0.1"       # from default route
        assert body["dns"] == ["1.1.1.1", "9.9.9.9"]

    def test_ddns_never_returns_credentials(self, test_client, auth_headers,
                                            monkeypatch, tmp_path):
        """The GET endpoint reads the 0600 store; the token must not come back."""
        import ddns
        f = tmp_path / "ddns.json"
        monkeypatch.setattr(ddns, "DDNS_FILE", f)
        ddns.save({"provider": "cloudflare", "hostname": "nas.example.com",
                   "credentials": {"token": "SECRET-SHOULD-NOT-LEAK"}})
        r = test_client.get("/api/net/ddns", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "cloudflare"
        assert body["configured"] is True
        assert "SECRET-SHOULD-NOT-LEAK" not in str(body)
        assert "credentials" not in body and "token" not in body
