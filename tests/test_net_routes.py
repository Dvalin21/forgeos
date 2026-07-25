"""Static route writes — routes emitted INTO the interface's .network file
(networkd validates a route's gateway against a local address in the same
file; a routes-only file fails to install them). Temp networkd dir + JSON
store + mocked networkctl/ip; no real commands."""
import json
import pytest


@pytest.fixture
def routefs(tmp_path, monkeypatch, test_client):
    import net_networkd as ni
    netdir = tmp_path / "network"
    netdir.mkdir()
    # a ForgeOS-managed interface file WITH an address (routes attach here)
    (netdir / "10-forgeos-ens18.network").write_text(
        "# Managed by ForgeOS\n[Match]\nName=ens18\n\n[Network]\n"
        "Address=10.0.0.69/24\nGateway=10.0.0.1\n")
    monkeypatch.setattr(ni, "NETWORKD_DIR", netdir)
    monkeypatch.setattr(ni, "ROUTES_STORE", tmp_path / "managed-routes.json")
    calls = []
    def fake_run(args, timeout=None):
        calls.append(args)
        if args[:3] == ["ip", "-j", "route"]:
            return '[{"dst":"default","gateway":"10.0.0.1","dev":"ens18"}]'
        return ""
    monkeypatch.setattr(ni, "_run_args", fake_run)
    return {"ni": ni, "netdir": netdir, "calls": calls}


class TestRoutesInInterfaceFile:
    def test_route_written_into_interface_file_with_address(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes({"ens18": [
            {"destination": "192.168.99.0/24", "gateway": "10.0.0.1", "metric": 0}]})
        content = (routefs["netdir"] / "10-forgeos-ens18.network").read_text()
        # the route and the address are in the SAME file — what networkd needs
        assert "Address=10.0.0.69/24" in content
        assert "[Route]" in content
        assert "Destination=192.168.99.0/24" in content
        # and the interface was reconfigured, not just reloaded
        assert ["networkctl", "reconfigure", "ens18"] in routefs["calls"]

    def test_rerender_does_not_duplicate_routes(self, routefs):
        ni = routefs["ni"]
        r = {"destination": "10.5.0.0/24", "gateway": "10.0.0.1", "metric": 0}
        ni.apply_routes({"ens18": [r]})
        ni.apply_routes({"ens18": [r]})            # apply the same set again
        content = (routefs["netdir"] / "10-forgeos-ens18.network").read_text()
        assert content.count("[Route]") == 1
        assert content.count("Address=10.0.0.69/24") == 1

    def test_removing_all_routes_clears_them_from_the_file(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes({"ens18": [
            {"destination": "10.6.0.0/24", "gateway": "10.0.0.1", "metric": 0}]})
        assert "[Route]" in (routefs["netdir"] / "10-forgeos-ens18.network").read_text()
        ni.apply_routes({"ens18": []})
        content = (routefs["netdir"] / "10-forgeos-ens18.network").read_text()
        assert "[Route]" not in content
        assert "Address=10.0.0.69/24" in content    # addressing preserved

    def test_metric_emitted_when_nonzero(self, routefs):
        ni = routefs["ni"]
        ni.apply_routes({"ens18": [
            {"destination": "10.7.0.0/24", "gateway": "10.0.0.1", "metric": 200}]})
        assert "Metric=200" in (routefs["netdir"] / "10-forgeos-ens18.network").read_text()

    def test_interface_edit_preserves_routes(self, routefs):
        """render_network_file (used on an interface edit) must re-emit stored
        routes, or editing the interface would silently drop them."""
        ni = routefs["ni"]
        from network_api import InterfaceConfig
        ni.apply_routes({"ens18": [
            {"destination": "10.8.0.0/24", "gateway": "10.0.0.1", "metric": 0}]})
        # simulate an interface edit re-rendering the file
        cfg = InterfaceConfig(name="ens18", method="static", address="10.0.0.69/24",
                              gateway="10.0.0.1", dns=["1.1.1.1"], mtu=1500)
        rendered = ni.render_network_file(cfg)
        assert "Destination=10.8.0.0/24" in rendered
        assert rendered.count("[Route]") == 1


class TestRouteEndpoints:
    def test_add_route_defaults_to_primary_interface(self, routefs, test_client, auth_headers):
        r = test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "192.168.44.0/24", "gateway": "10.0.0.254", "metric": 100})
        assert r.status_code == 200, r.text
        routes = r.json()["routes"]
        assert any(x["destination"] == "192.168.44.0/24" and x["interface"] == "ens18"
                   for x in routes)

    def test_add_explicit_interface(self, routefs, test_client, auth_headers):
        r = test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.20.0.0/16", "gateway": "10.0.0.1", "interface": "ens18"})
        assert r.status_code == 200
        assert any(x["interface"] == "ens18" for x in r.json()["routes"])

    def test_duplicate_destination_replaces(self, routefs, test_client, auth_headers):
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.5.0.0/24", "gateway": "10.0.0.1", "interface": "ens18"})
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.5.0.0/24", "gateway": "10.0.0.9", "interface": "ens18"})
        routes = test_client.get("/api/net/routes/managed", headers=auth_headers).json()["routes"]
        same = [r for r in routes if r["destination"] == "10.5.0.0/24"]
        assert len(same) == 1 and same[0]["gateway"] == "10.0.0.9"

    def test_delete_route(self, routefs, test_client, auth_headers):
        test_client.post("/api/net/routes", headers=auth_headers, json={
            "destination": "10.6.0.0/24", "gateway": "10.0.0.1", "interface": "ens18"})
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

    def test_managed_empty_initially(self, routefs, test_client, auth_headers):
        assert test_client.get("/api/net/routes/managed",
                               headers=auth_headers).json()["routes"] == []

    def test_writes_require_admin(self, routefs, test_client, user_headers):
        assert test_client.post("/api/net/routes", headers=user_headers, json={
            "destination": "10.0.0.0/24", "gateway": "10.0.0.1"}).status_code == 403
        assert test_client.delete("/api/net/routes?destination=10.0.0.0/24",
                                  headers=user_headers).status_code == 403
