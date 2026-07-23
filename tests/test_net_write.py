"""Interface/global write layer (systemd-networkd backend) — snapshot/apply/
revert + endpoints. Uses a temp /etc/systemd/network + mocked networkctl —
NO real networkctl/ip commands."""
import time
import pytest


@pytest.fixture
def netfs(tmp_path, monkeypatch, test_client):
    """Redirect networkd paths into a temp dir + capture networkctl calls.

    Depends on test_client so app startup (set_runner with the real runner)
    happens FIRST — then we override _run_args with the mock.
    """
    import net_networkd as ni
    netdir = tmp_path / "network"
    resolv = tmp_path / "resolv.conf"
    netdir.mkdir()
    # a distro-default file that ForgeOS must leave alone
    (netdir / "99-default.network").write_text("[Match]\nName=en*\n[Network]\nDHCP=yes\n")
    resolv.write_text("nameserver 10.0.0.1\n")
    monkeypatch.setattr(ni, "NETWORKD_DIR", netdir)
    monkeypatch.setattr(ni, "RESOLV_CONF", resolv)
    calls = []
    monkeypatch.setattr(ni, "_run_args", lambda args, timeout=None: calls.append(args) or "")
    ni.engine._pending = None
    ni.engine._last_result = None
    return {"netdir": netdir, "resolv": resolv, "calls": calls, "ni": ni}


class TestSnapshotRestore:
    def test_snapshot_then_restore_is_exact(self, netfs):
        ni = netfs["ni"]
        snap = ni._snapshot()
        (netfs["netdir"] / "10-forgeos-ens18.network").write_text("garbage")
        (netfs["netdir"] / "99-default.network").write_text("WIPED")
        netfs["resolv"].write_text("nameserver 8.8.8.8")
        ni._restore(snap)
        # distro default restored, added forgeos file removed, resolv restored
        assert "DHCP=yes" in (netfs["netdir"] / "99-default.network").read_text()
        assert not (netfs["netdir"] / "10-forgeos-ens18.network").exists()
        assert netfs["resolv"].read_text() == "nameserver 10.0.0.1\n"


class TestApplyConfirm:
    def _apply_static(self, client, headers):
        return client.put("/api/net/interface/ens18", headers=headers, json={
            "name": "ens18", "method": "static",
            "address": "10.0.0.69/24", "gateway": "10.0.0.1", "mtu": 1500})

    def test_apply_writes_network_file_and_reconfigures(self, netfs, test_client, auth_headers):
        r = self._apply_static(test_client, auth_headers)
        assert r.status_code == 200, r.text
        assert "token" in r.json()
        nf = netfs["netdir"] / "10-forgeos-ens18.network"
        assert nf.exists()
        assert "Address=10.0.0.69/24" in nf.read_text()
        # distro default untouched
        assert (netfs["netdir"] / "99-default.network").exists()
        # networkctl reload + reconfigure were called
        assert ["networkctl", "reload"] in netfs["calls"]
        assert ["networkctl", "reconfigure", "ens18"] in netfs["calls"]
        netfs["ni"].engine.cancel()

    def test_confirm_commits(self, netfs, test_client, auth_headers):
        r = self._apply_static(test_client, auth_headers)
        c = test_client.post("/api/net/confirm", headers=auth_headers, json={"token": r.json()["token"]})
        assert c.status_code == 200
        assert c.json()["result"] == "committed"
        assert "Address=10.0.0.69/24" in (netfs["netdir"] / "10-forgeos-ens18.network").read_text()

    def test_no_confirm_auto_reverts(self, netfs, test_client, auth_headers):
        netfs["ni"].engine._window = 1
        r = self._apply_static(test_client, auth_headers)
        assert (netfs["netdir"] / "10-forgeos-ens18.network").exists()
        time.sleep(1.4)
        # auto-reverted: forgeos file gone, default intact
        assert not (netfs["netdir"] / "10-forgeos-ens18.network").exists()
        assert (netfs["netdir"] / "99-default.network").exists()
        assert netfs["ni"].engine.status()["last_result"] == "reverted"
        # the REVERT must also reconfigure the link — restoring the file alone
        # leaves the interface on the bad address (hardware-proven regression)
        assert netfs["calls"].count(["networkctl", "reconfigure", "ens18"]) >= 2

    def test_second_apply_while_pending_rejected(self, netfs, test_client, auth_headers):
        self._apply_static(test_client, auth_headers)
        r2 = self._apply_static(test_client, auth_headers)
        assert r2.status_code == 409
        netfs["ni"].engine.cancel()

    def test_cancel_reverts_immediately(self, netfs, test_client, auth_headers):
        self._apply_static(test_client, auth_headers)
        c = test_client.post("/api/net/cancel", headers=auth_headers)
        assert c.status_code == 200
        assert not (netfs["netdir"] / "10-forgeos-ens18.network").exists()
        assert netfs["calls"].count(["networkctl", "reconfigure", "ens18"]) >= 2

    def test_name_mismatch_rejected(self, netfs, test_client, auth_headers):
        r = test_client.put("/api/net/interface/ens18", headers=auth_headers, json={
            "name": "eth9", "method": "dhcp"})
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
        for call in [
            lambda: test_client.put("/api/net/interface/ens18", headers=user_headers,
                                    json={"name": "ens18", "method": "dhcp"}),
            lambda: test_client.put("/api/net/global", headers=user_headers,
                                    json={"hostname": "x", "dns": []}),
            lambda: test_client.post("/api/net/cancel", headers=user_headers),
        ]:
            assert call().status_code == 403


class TestReadOnlyParentDir:
    """systemd ProtectSystem carve-outs can be FILE-level (-/etc/resolv.conf),
    leaving the parent dir read-only. mkstemp there fails — hardware-proven to
    abort the whole revert and strand the box."""

    def test_atomic_write_falls_back_when_parent_readonly(self, netfs, monkeypatch):
        import errno as _errno
        import forgeos_atomic as fa
        ni = netfs["ni"]
        target = netfs["resolv"]
        def boom(*a, **k):
            raise OSError(_errno.EROFS, "Read-only file system")
        monkeypatch.setattr(fa.tempfile, "mkstemp", boom)
        fa.atomic_write(target, "nameserver 9.9.9.9\n")
        assert target.read_text() == "nameserver 9.9.9.9\n"

    def test_atomic_write_reraises_other_oserrors(self, netfs, monkeypatch):
        import errno as _errno
        import forgeos_atomic as fa
        def boom(*a, **k):
            raise OSError(_errno.ENOSPC, "No space left on device")
        monkeypatch.setattr(fa.tempfile, "mkstemp", boom)
        with pytest.raises(OSError):
            fa.atomic_write(netfs["resolv"], "x")

    def test_resolv_failure_does_not_abort_revert(self, netfs, test_client,
                                                  auth_headers, monkeypatch):
        """The regression: a resolv.conf write blowing up must not stop the
        .network restore + reconfigure that actually un-bricks the host."""
        ni = netfs["ni"]
        ni.engine._window = 1
        real = ni.atomic_write
        def selective(path, content, mode=0o644):
            if str(path) == str(netfs["resolv"]):
                raise OSError(30, "Read-only file system")
            return real(path, content, mode)
        r = test_client.put("/api/net/interface/ens18", headers=auth_headers, json={
            "name": "ens18", "method": "static",
            "address": "10.0.0.69/24", "gateway": "10.0.0.1", "mtu": 1500})
        assert r.status_code == 200
        monkeypatch.setattr(ni, "atomic_write", selective)
        time.sleep(1.4)
        # revert still completed: forgeos file removed AND link reconfigured
        assert not (netfs["netdir"] / "10-forgeos-ens18.network").exists()
        assert netfs["calls"].count(["networkctl", "reconfigure", "ens18"]) >= 2
        assert ni.engine.status()["last_result"] == "reverted"
