"""Static route writes (systemd-networkd 20-forgeos-routes.network).
Temp networkd dir + mocked networkctl/ip — no real commands."""
import pytest


@pytest.fixture
def routefs(tmp_path, monkeypatch, test_client):
    import net_networkd as ni
    netdir = tmp_path / "network"
    netdir.mkdir()
    (netdir / "10-forgeos-ens18.network").write_text(
        "[Match]\nName=ens18\n[Network]\nAddress=10.0.0.69/24\n")
    monkeypatch.setattr(ni, "NETWORKD_DIR", netdir)
    monkeypatch.setattr(ni, "ROUTES_FILE", netdir / "20-forgeos-routes.network")
    calls = []
    def fake_run(args, timeout=None):
        calls.append(args)
        if args[:3] == ["ip", "-j", "route"]:
            return '[{"dst":"default","gateway":"10.0.0.1","dev":"ens18"}]'
        return ""
    monkeypatch.setattr(ni, "_run_args", fake_run)
    return {"ni": ni, "netdir": netdir, "calls": calls}


class TestRouteGenerator:
    def test_render_and_parse_roundtrip(self, routefs):
        ni = routefs["ni"]
        routes = [{"destination": "192.168.9.0/24", "gateway": "10.0.0.254", "metric": 50}]
        ni.ROUTES_FILE.write_text(ni.render_routes_file(routes, "ens18"))
        back = ni.load_managed_routes()
        assert back == [{"destination": "192.168.9.0/24", "gateway": "10.0.0.254", "metric": 50}]

    def test_metric_zero_omitted(self, routefs):
        ni = routefs["ni"]
        out = ni.render_routes_file([{"destination": "10.8.0.0/24", "gateway": "10.0.0.1", "metric": 0}], "ens18")
        assert "Metric=" not in out


class TestApplyRoutes:
    def test_apply_writes_file_and_reloads(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes([{"destination": "172.16.0.0/12", "gateway": "10.0.0.2", "metric": 0}])
        assert ni.ROUTES_FILE.exists()
        assert "Destination=172.16.0.0/12" in ni.ROUTES_FILE.read_text()
        assert ["networkctl", "reload"] in routefs["calls"]

    def test_apply_empty_removes_file(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes([{"destination": "10.9.0.0/24", "gateway": "10.0.0.1", "metric": 0}])
        assert ni.ROUTES_FILE.exists()
        ni.apply_routes([])                      # remove all
        assert not ni.ROUTES_FILE.exists()

    def test_match_iface_uses_default_route_dev(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes([{"destination": "10.7.0.0/24", "gateway": "10.0.0.1", "metric": 0}])
        assert "Name=ens18" in ni.ROUTES_FILE.read_text()


class TestRouteEndpoints:
    def test_add_route(self, routefs, test_client, auth_headers):
        r = test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "192.168.44.0/24", "gateway": "10.0.0.254", "metric": 100})
        assert r.status_code == 200
        dests = [x["destination"] for x in r.json()["routes"]]
        assert "192.168.44.0/24" in dests

    def test_add_duplicate_destination_replaces(self, routefs, test_client, auth_headers):
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.5.0.0/24", "gateway": "10.0.0.1", "metric": 0})
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.5.0.0/24", "gateway": "10.0.0.9", "metric": 5})
        managed = test_client.get("/api/net/routes/managed", headers=auth_headers).json()["routes"]
        same = [r for r in managed if r["destination"] == "10.5.0.0/24"]
        assert len(same) == 1 and same[0]["gateway"] == "10.0.0.9"

    def test_delete_route(self, routefs, test_client, auth_headers):
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.6.0.0/24", "gateway": "10.0.0.1", "metric": 0})
        d = test_client.delete("/api/net/routes?destination=10.6.0.0/24", headers=auth_headers)
        assert d.status_code == 200
        assert all(r["destination"] != "10.6.0.0/24" for r in d.json()["routes"])

    def test_delete_unknown_is_404(self, routefs, test_client, auth_headers):
        assert test_client.delete("/api/net/routes?destination=1.2.3.0/24",
                                  headers=auth_headers).status_code == 404

    def test_invalid_destination_422(self, routefs, test_client, auth_headers):
        assert test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "not-a-network", "gateway": "10.0.0.1"}).status_code == 422

    def test_invalid_gateway_422(self, routefs, test_client, auth_headers):
        assert test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.0.0.0/24", "gateway": "999.0.0.1"}).status_code == 422

    def test_managed_only_lists_forgeos_routes(self, routefs, test_client, auth_headers):
        # the live table has kernel/DHCP routes; managed starts empty
        assert test_client.get("/api/net/routes/managed",
                               headers=auth_headers).json()["routes"] == []

    def test_writes_require_admin(self, routefs, test_client, user_headers):
        assert test_client.post("/api/net/routes", headers=user_headers, json={
            "destination": "10.0.0.0/24", "gateway": "10.0.0.1"}).status_code == 403
        assert test_client.delete("/api/net/routes?destination=10.0.0.0/24",
                                  headers=user_headers).status_code == 403
