"""Incus API + the ufw/Incus firewall integration.

Everything asserted here was verified against Incus 6.0.4 on Debian 13
before the code was written; the comments record WHAT was checked so the next
person can re-verify rather than trust.

The firewall test is the important one. A default-deny ufw policy silently
discards the DHCP OFFER before it reaches the container: the instance starts,
`incus exec` works, and eth0 has no address, no route and no DNS. It looks
like a broken hypervisor. It is a broken firewall.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    import forgeos_config as fc
    path = tmp_path / "config.json"
    fc.save(fc.ForgeOSConfig(), path)
    monkeypatch.setattr(fc, "CONFIG_PATH", path)
    return path


# ── config model ───────────────────────────────────────────────────────────
class TestIncusConfig:
    def test_defaults_are_off(self):
        import forgeos_config as fc
        c = fc.IncusConfig()
        assert c.enabled is False
        assert c.bridge == "incusbr0"
        assert c.storage_pool == "default"

    def test_bridge_name_is_validated(self):
        import forgeos_config as fc
        # these all reach iptables/nftables and ufw argv; a space or a leading
        # dash could escape into another argument
        for bad in ("bad name", "a;b", "1bad", "-bridge", "", "x" * 40):
            with pytest.raises(Exception):
                fc.IncusConfig(bridge=bad)

    def test_schema_migrated_to_14(self):
        import forgeos_config as fc
        assert fc.SCHEMA_VERSION == 14
        assert fc.migrate({"version": 13})["version"] == 14
        assert fc.migrate({"version": 14})["version"] == 14

    def test_v13_config_still_loads(self):
        import forgeos_config as fc
        c = fc.ForgeOSConfig.model_validate(fc.migrate({"version": 13}))
        assert c.incus.enabled is False      # additive: nothing changes for old boxes


# ── the ufw carve-outs ─────────────────────────────────────────────────────
class TestUfwIncusIntegration:
    """ufw generator — the fix for the silent-no-IP failure."""

    def _gen(self):
        from generators.ufw import UfwGenerator
        return UfwGenerator()

    def _cfg(self, enabled: bool):
        import forgeos_config as fc
        return fc.ForgeOSConfig.model_validate({"incus": {"enabled": enabled}})

    def test_no_rules_when_incus_disabled(self):
        assert self._gen()._incus_rules(self._cfg(False)) == []

    def test_bridge_gets_input_and_forward_carve_outs(self):
        rules = self._gen()._incus_rules(self._cfg(True))
        joined = [" ".join(r) for r in rules]
        assert any(r.startswith("allow in on incusbr0") for r in joined), joined
        assert any(r.startswith("route allow in on incusbr0") for r in joined), joined
        assert any(r.startswith("route allow out on incusbr0") for r in joined), joined

    def test_bridge_name_comes_from_config_not_hardcoded(self):
        import forgeos_config as fc
        cfg = fc.ForgeOSConfig.model_validate(
            {"incus": {"enabled": True, "bridge": "forgebr0"}})
        joined = [" ".join(r) for r in self._gen()._incus_rules(cfg)]
        assert all("forgebr0" in r for r in joined), joined

    def test_applied_before_enable(self):
        """Order matters: `ufw --force reset` wipes Incus's own nftables rules,
        so the carve-outs must be re-added before the firewall goes back up.
        Otherwise every apply silently breaks every container again."""
        g = self._gen()
        seen = []

        class R:
            returncode = 0
            stdout = stderr = ""

        def fake_run(cmd, check=True):
            seen.append(cmd)
            return R()

        g._run = fake_run
        cfg = self._cfg(True)
        cfg.firewall.enabled = True
        cfg.firewall.default_incoming = "deny"
        g.apply(cfg)

        incus_idx = [i for i, c in enumerate(seen)
                     if "incusbr0" in " ".join(c)]
        enable_idx = [i for i, c in enumerate(seen) if "enable" in c]
        assert incus_idx and enable_idx
        assert max(incus_idx) < min(enable_idx), \
            "Incus carve-outs must be inserted before `ufw enable`"
        assert seen[0][:3] == ["ufw", "--force", "reset"]


# ── API surface ────────────────────────────────────────────────────────────
class TestIncusApiRouting:
    def test_routes_under_own_prefix(self, test_client):
        assert test_client.get("/api/incus/status").status_code in (401, 403)

    def test_requires_auth(self, test_client, cfgfile, monkeypatch):
        import incus_api
        monkeypatch.setattr(incus_api, "_installed", lambda: True)
        for path in ("/api/incus/instances", "/api/incus/status"):
            assert test_client.get(path).status_code in (401, 403)


class TestIncusApiBehaviour:
    @pytest.fixture(autouse=True)
    def _present(self, monkeypatch):
        import incus_api
        monkeypatch.setattr(incus_api, "_installed", lambda: True)

    def test_missing_incus_is_503_not_500(self, test_client, auth_headers,
                                          monkeypatch):
        import incus_api
        monkeypatch.setattr(incus_api, "_installed", lambda: False)
        r = test_client.get("/api/incus/instances", headers=auth_headers)
        assert r.status_code == 503
        assert "not installed" in r.json()["detail"]

    def test_invalid_instance_name_rejected(self, test_client, auth_headers):
        for bad in ("-rf", "a;b", "a b", "", "x" * 100):
            r = test_client.post(f"/api/incus/instances/{bad}/start",
                                 headers=auth_headers)
            assert r.status_code in (400, 404), f"{bad!r} -> {r.status_code}"

    def test_create_requires_admin(self, test_client, user_headers):
        r = test_client.post("/api/incus/instances", headers=user_headers,
                             json={"name": "x", "image": "images:debian/13"})
        assert r.status_code == 403

    def test_create_requires_image(self, test_client, auth_headers):
        r = test_client.post("/api/incus/instances", headers=auth_headers,
                             json={"name": "x"})
        assert r.status_code == 400

    def test_create_rejects_bad_type(self, test_client, auth_headers):
        r = test_client.post("/api/incus/instances", headers=auth_headers,
                             json={"name": "x", "image": "i", "type": "vm"})
        assert r.status_code == 400

    def test_hardware_values_pass_through_unclamped(self, test_client,
                                                    auth_headers, monkeypatch):
        """The whole point of the editable fields: what the user typed is what
        Incus gets. 3GB must not become 4GB because a preset said so."""
        import incus_api
        seen = {}

        calls = []

        def fake_run(args, timeout=60):
            calls.append(args)
            # first call is the "does this name already exist" probe
            out = "" if args[:1] == ["list"] else "[]"
            return {"success": True, "stdout": out, "stderr": "",
                    "returncode": 0}

        monkeypatch.setattr(incus_api, "_run", fake_run)
        test_client.post("/api/incus/instances", headers=auth_headers, json={
            "name": "mine", "image": "images:debian/13",
            "cpu_limit": "3", "memory": "3GiB", "disk": "77GB",
        })
        launch = next(c for c in calls if c[:1] == ["launch"])
        args = launch
        assert "limits.cpu=3" in args
        assert "limits.memory=3GiB" in args
        assert any(a.endswith("size=77GB") for a in args), args

    def test_garbage_hardware_is_rejected_not_sanitised(self, test_client,
                                                        auth_headers, monkeypatch):
        import incus_api
        monkeypatch.setattr(incus_api, "_run",
                            lambda *a, **k: {"success": True, "stdout": "",
                                             "stderr": "", "returncode": 0})
        for field, bad in (("cpu_limit", "-1"), ("memory", "1; rm -rf /"),
                           ("disk", "$(reboot)")):
            r = test_client.post("/api/incus/instances", headers=auth_headers,
                                 json={"name": "x", "image": "i", field: bad})
            assert r.status_code == 400, f"{field}={bad!r} leaked through"

    def test_delete_requires_admin(self, test_client, user_headers):
        assert test_client.delete("/api/incus/instances/x",
                                  headers=user_headers).status_code == 403

    def test_exec_requires_admin(self, test_client, user_headers):
        r = test_client.post("/api/incus/instances/x/exec",
                             headers=user_headers, json={"command": "id"})
        assert r.status_code == 403

    def test_delete_missing_instance_is_404(self, test_client, auth_headers,
                                           monkeypatch):
        import incus_api
        monkeypatch.setattr(incus_api, "_run",
                            lambda *a, **k: {"success": False, "stdout": "",
                                             "stderr": "Error: Instance not found",
                                             "returncode": 1})
        assert test_client.delete("/api/incus/instances/nope",
                                  headers=auth_headers).status_code == 404

    def test_view_shape_matches_what_the_ui_renders(self):
        from incus_api import _view
        v = _view({
            "name": "c1", "status": "Running", "type": "container",
            "config": {"image.description": "Debian 13",
                       "limits.cpu": "2", "limits.memory": "2GiB"},
            "expanded_devices": {"root": {"type": "disk", "path": "/",
                                          "size": "20GiB"}},
            "state": {"memory": {"usage": 536870912},
                      "network": {"eth0": {"addresses": [
                          {"family": "inet", "scope": "global",
                           "address": "10.141.33.5"}]}}},
            "snapshots": [{"name": "s1"}],
        })
        assert v["name"] == "c1" and v["status"] == "Running"
        assert v["image"] == "Debian 13"
        assert v["cpu_limit"] == "2" and v["memory_limit"] == "2GiB"
        assert v["ipv4"] == "10.141.33.5"
        assert v["disk_display"] == "20.0 GiB"
        assert v["memory_display"] == "512.0 MiB"
        assert v["snapshots"] == 1