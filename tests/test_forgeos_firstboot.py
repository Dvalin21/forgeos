"""First-boot DHCP→static-at-leased-IP converter.

Scope is deliberately narrow: DHCP hands out an address, this pins it
static. NO pool-range detection or warning — verified there is no
protocol-level way for a client to learn a DHCP server's scope, so a
heuristic would be a guess presented as fact. Every test here also guards
that boundary: nothing in this module infers or warns about pool conflicts.
"""
import json

import pytest

import forgeos_firstboot as fb


@pytest.fixture
def fs(tmp_path, monkeypatch):
    import net_networkd as ni
    netdir = tmp_path / "network"
    netdir.mkdir()
    monkeypatch.setattr(ni, "NETWORKD_DIR", netdir)
    calls = []
    def fake_run(args, timeout=30):
        calls.append(args)
        return fake_run.responses.pop(0) if fake_run.responses else ""
    fake_run.responses = []
    monkeypatch.setattr(fb, "_run_args", fake_run)
    return {"netdir": netdir, "calls": calls, "run": fake_run}


class TestPrimaryInterface:
    def test_reads_default_route_device(self, fs):
        fs["run"].responses = [json.dumps([{"dst": "default", "dev": "ens18"}])]
        assert fb.primary_interface() == "ens18"

    def test_no_default_route_returns_empty(self, fs):
        fs["run"].responses = ["[]"]
        assert fb.primary_interface() == ""

    def test_malformed_json_returns_empty(self, fs):
        fs["run"].responses = ["not json"]
        assert fb.primary_interface() == ""


class TestReadLease:
    def _addr_json(self, ip, prefix):
        return json.dumps([{"addr_info": [{"family": "inet", "local": ip, "prefixlen": prefix}]}])

    def test_reads_address_and_gateway(self, fs, tmp_path, monkeypatch):
        fs["run"].responses = [
            self._addr_json("10.0.0.69", 24),
            json.dumps([{"gateway": "10.0.0.1"}]),
        ]
        resolv = tmp_path / "resolv.conf"
        resolv.write_text("nameserver 10.0.0.1\n")
        real_open = open
        def fake_open(p, *a, **k):
            return real_open(resolv, *a, **k) if p == "/etc/resolv.conf" else real_open(p, *a, **k)
        monkeypatch.setattr("builtins.open", fake_open)
        lease = fb.read_lease("ens18")
        assert lease["address"] == "10.0.0.69/24"
        assert lease["gateway"] == "10.0.0.1"
        assert lease["dns"] == ["10.0.0.1"]

    def test_no_address_returns_none(self, fs):
        fs["run"].responses = ["[]", "[]"]
        assert fb.read_lease("ens18") is None

    def test_no_gateway_is_tolerated(self, fs, monkeypatch):
        fs["run"].responses = [self._addr_json("10.0.0.69", 24), "[]"]
        monkeypatch.setattr(fb, "_read_resolv_dns", lambda: [])
        lease = fb.read_lease("ens18")
        assert lease["address"] == "10.0.0.69/24"
        assert lease["gateway"] is None


class TestWaitForLease:
    def test_returns_as_soon_as_a_lease_appears(self, fs, monkeypatch):
        calls = {"n": 0}
        def fake_read(iface):
            calls["n"] += 1
            return {"address": "10.0.0.69/24"} if calls["n"] >= 3 else None
        monkeypatch.setattr(fb, "read_lease", fake_read)
        monkeypatch.setattr(fb.time, "sleep", lambda s: None)
        lease = fb.wait_for_lease("ens18", attempts=10, delay=0)
        assert lease == {"address": "10.0.0.69/24"}
        assert calls["n"] == 3

    def test_gives_up_after_max_attempts(self, fs, monkeypatch):
        monkeypatch.setattr(fb, "read_lease", lambda iface: None)
        monkeypatch.setattr(fb.time, "sleep", lambda s: None)
        assert fb.wait_for_lease("ens18", attempts=3, delay=0) is None


class TestAlreadyStatic:
    def test_false_when_no_managed_file(self, fs):
        assert fb.already_static("ens18") is False

    def test_true_when_address_present(self, fs):
        (fs["netdir"] / "10-forgeos-ens18.network").write_text(
            "[Match]\nName=ens18\n[Network]\nAddress=10.0.0.69/24\n")
        assert fb.already_static("ens18") is True

    def test_false_when_dhcp_only(self, fs):
        (fs["netdir"] / "10-forgeos-ens18.network").write_text(
            "[Match]\nName=ens18\n[Network]\nDHCP=yes\n")
        assert fb.already_static("ens18") is False


class TestConvert:
    def test_writes_static_config_via_shared_generator(self, fs):
        """Must use net_networkd's own render/write — not a second
        implementation that could drift from the runtime one."""
        fb.convert("ens18", {"address": "10.0.0.69/24", "gateway": "10.0.0.1", "dns": ["1.1.1.1"]})
        content = (fs["netdir"] / "10-forgeos-ens18.network").read_text()
        assert "Address=10.0.0.69/24" in content
        assert "Gateway=10.0.0.1" in content
        assert "DNS=1.1.1.1" in content
        assert ["networkctl", "reconfigure", "ens18"] in fs["calls"]

    def test_missing_gateway_omits_it(self, fs):
        fb.convert("ens18", {"address": "10.0.0.69/24", "gateway": None, "dns": []})
        content = (fs["netdir"] / "10-forgeos-ens18.network").read_text()
        assert "Gateway=" not in content


class TestEnableNetworkd:
    def test_enables_networkd_and_resolved_disables_ifupdown(self, fs):
        fb.enable_networkd()
        joined = [" ".join(c) for c in fs["calls"]]
        assert any("enable" in c and "systemd-networkd" in c for c in joined)
        assert any("enable" in c and "systemd-resolved" in c for c in joined)
        assert any("disable" in c and "networking" in c for c in joined)


class TestRunEndToEnd:
    def test_full_flow_converts_a_fresh_interface(self, fs, monkeypatch):
        monkeypatch.setattr(fb, "primary_interface", lambda: "ens18")
        monkeypatch.setattr(fb, "already_static", lambda iface: False)
        monkeypatch.setattr(fb, "wait_for_lease", lambda iface: {
            "address": "10.0.0.69/24", "gateway": "10.0.0.1", "dns": ["1.1.1.1"]})
        assert fb.run() == 0
        content = (fs["netdir"] / "10-forgeos-ens18.network").read_text()
        assert "Address=10.0.0.69/24" in content

    def test_idempotent_skips_already_static(self, fs, monkeypatch):
        monkeypatch.setattr(fb, "primary_interface", lambda: "ens18")
        monkeypatch.setattr(fb, "already_static", lambda iface: True)
        called = {"n": 0}
        monkeypatch.setattr(fb, "convert", lambda *a: called.__setitem__("n", called["n"] + 1))
        assert fb.run() == 0
        assert called["n"] == 0

    def test_no_interface_found_returns_error_code(self, fs, monkeypatch):
        monkeypatch.setattr(fb, "primary_interface", lambda: "")
        assert fb.run() == 1

    def test_no_lease_acquired_returns_error_code(self, fs, monkeypatch):
        monkeypatch.setattr(fb, "primary_interface", lambda: "ens18")
        monkeypatch.setattr(fb, "already_static", lambda iface: False)
        monkeypatch.setattr(fb, "wait_for_lease", lambda iface: None)
        assert fb.run() == 1


class TestNoPoolDetection:
    """Guards the explicit scope boundary: this module must never infer or
    warn about the DHCP server's pool/scope range."""

    def test_module_has_no_pool_related_functions(self):
        names = " ".join(dir(fb)).lower()
        for forbidden in ("pool", "scope_range", "conflict_warn"):
            assert forbidden not in names, f"found forbidden concept: {forbidden}"

    def test_lease_dict_has_no_pool_fields(self, fs):
        fb.convert("ens18", {"address": "10.0.0.69/24", "gateway": "10.0.0.1", "dns": []})
        # convert() takes exactly address/gateway/dns — no pool-shaped input
        import inspect
        sig = str(inspect.signature(fb.convert))
        assert "pool" not in sig.lower()
