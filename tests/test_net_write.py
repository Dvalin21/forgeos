"""Interface/global write layer — snapshot/apply/revert + endpoints.
Uses a temp /etc/network and mocked reload — NO real ifupdown/ip commands."""
import time
import pytest


@pytest.fixture
def netfs(tmp_path, monkeypatch, test_client):
    """Redirect all ifupdown paths into a temp dir + capture reload calls.

    Depends on test_client so app startup (which calls set_runner with the real
    runner) happens FIRST — then we override _run_args with the mock.
    """
    import net_ifupdown as ni
    main = tmp_path / "interfaces"
    dropd = tmp_path / "interfaces.d"
    resolv = tmp_path / "resolv.conf"
    dropd.mkdir()
    main.write_text("source /etc/network/interfaces.d/*\n"
                    "auto lo\niface lo inet loopback\n"
                    "allow-hotplug ens18\niface ens18 inet dhcp\n")
    resolv.write_text("nameserver 10.0.0.1\n")
    monkeypatch.setattr(ni, "INTERFACES_MAIN", main)
    monkeypatch.setattr(ni, "INTERFACES_D", dropd)
    monkeypatch.setattr(ni, "RESOLV_CONF", resolv)
    calls = []
    monkeypatch.setattr(ni, "_run_args", lambda args, timeout=None: calls.append(args) or "")
    # force the classic ifdown/ifup path deterministically (no ifreload in test)
    monkeypatch.setattr(ni.shutil, "which", lambda _: None)
    # reset engine state between tests
    ni.engine._pending = None
    ni.engine._last_result = None
    return {"main": main, "dropd": dropd, "resolv": resolv, "calls": calls, "ni": ni}


class TestSnapshotRestore:
    def test_snapshot_then_restore_is_exact(self, netfs):
        ni = netfs["ni"]
        snap = ni._snapshot()
        # mutate everything
        (netfs["dropd"] / "forgeos-ens18.cfg").write_text("garbage")
        netfs["main"].write_text("WIPED")
        netfs["resolv"].write_text("nameserver 8.8.8.8")
        # restore
        ni._restore(snap)
        assert "iface ens18 inet dhcp" in netfs["main"].read_text()
        assert netfs["resolv"].read_text() == "nameserver 10.0.0.1\n"
        assert not (netfs["dropd"] / "forgeos-ens18.cfg").exists()  # added file removed


class TestApplyConfirm:
    def _apply_static(self, client, headers):
        return client.put("/api/net/interface/ens18", headers=headers, json={
            "name": "ens18", "method": "static",
            "address": "10.0.0.69/24", "gateway": "10.0.0.1", "mtu": 1500})

    def test_apply_writes_dropin_and_dedups_main(self, netfs, test_client, auth_headers):
        r = self._apply_static(test_client, auth_headers)
        assert r.status_code == 200, r.text
        assert "token" in r.json()
        # drop-in written with the static stanza
        dropin = netfs["dropd"] / "forgeos-ens18.cfg"
        assert dropin.exists()
        assert "iface ens18 inet static" in dropin.read_text()
        # main file deduped (ens18 commented, lo intact)
        main = netfs["main"].read_text()
        assert "# iface ens18 inet dhcp" in main
        assert "iface lo inet loopback" in main
        # reload was attempted (ifdown+ifup since which()->None)
        assert ["ifdown", "ens18", "--force"] in netfs["calls"]
        assert ["ifup", "ens18"] in netfs["calls"]
        netfs["ni"].engine.cancel()   # cleanup pending

    def test_confirm_commits(self, netfs, test_client, auth_headers):
        r = self._apply_static(test_client, auth_headers)
        tok = r.json()["token"]
        c = test_client.post("/api/net/confirm", headers=auth_headers, json={"token": tok})
        assert c.status_code == 200
        assert c.json()["result"] == "committed"
        # still static after confirm (no revert)
        assert "iface ens18 inet static" in (netfs["dropd"] / "forgeos-ens18.cfg").read_text()

    def test_no_confirm_auto_reverts(self, netfs, test_client, auth_headers, monkeypatch):
        # shrink the window so the timer fires fast
        netfs["ni"].engine._window = 1
        r = self._apply_static(test_client, auth_headers)
        assert (netfs["dropd"] / "forgeos-ens18.cfg").exists()
        time.sleep(1.4)
        # auto-reverted: drop-in gone, main restored to dhcp
        assert not (netfs["dropd"] / "forgeos-ens18.cfg").exists()
        assert "iface ens18 inet dhcp" in netfs["main"].read_text()
        assert "# iface ens18" not in netfs["main"].read_text()
        assert netfs["ni"].engine.status()["last_result"] == "reverted"

    def test_second_apply_while_pending_rejected(self, netfs, test_client, auth_headers):
        self._apply_static(test_client, auth_headers)
        r2 = self._apply_static(test_client, auth_headers)
        assert r2.status_code == 409
        netfs["ni"].engine.cancel()

    def test_cancel_reverts_immediately(self, netfs, test_client, auth_headers):
        self._apply_static(test_client, auth_headers)
        c = test_client.post("/api/net/cancel", headers=auth_headers)
        assert c.status_code == 200
        assert not (netfs["dropd"] / "forgeos-ens18.cfg").exists()

    def test_name_mismatch_rejected(self, netfs, test_client, auth_headers):
        r = test_client.put("/api/net/interface/ens18", headers=auth_headers, json={
            "name": "eth9", "method": "dhcp"})   # body name != path name
        assert r.status_code == 400


class TestGlobalWrite:
    def test_global_sets_hostname_and_dns(self, netfs, test_client, auth_headers):
        r = test_client.put("/api/net/global", headers=auth_headers, json={
            "hostname": "forgenas", "domain": "example.com",
            "dns": ["1.1.1.1", "9.9.9.9"]})
        assert r.status_code == 200
        assert ["hostnamectl", "set-hostname", "forgenas"] in netfs["calls"]
        resolv = netfs["resolv"].read_text()
        assert "nameserver 1.1.1.1" in resolv and "nameserver 9.9.9.9" in resolv
        assert "search example.com" in resolv

    def test_global_invalid_hostname_422(self, netfs, test_client, auth_headers):
        r = test_client.put("/api/net/global", headers=auth_headers, json={
            "hostname": "-bad", "dns": []})
        assert r.status_code == 422


class TestAdminGating:
    def test_writes_require_admin(self, netfs, test_client, user_headers):
        # a non-admin token must be refused on every write
        for call in [
            lambda: test_client.put("/api/net/interface/ens18", headers=user_headers,
                                    json={"name": "ens18", "method": "dhcp"}),
            lambda: test_client.put("/api/net/global", headers=user_headers,
                                    json={"hostname": "x", "dns": []}),
            lambda: test_client.post("/api/net/cancel", headers=user_headers),
        ]:
            assert call().status_code == 403
