"""Firewall P1 — config-DB backed API + ufw generator converge.

API tests inject a fake apply (set_apply) so nothing touches ufw; generator
tests capture the exact CLI sequence, which is where lockout safety lives.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import firewall_api  # noqa: E402
import forgeos_config as fc  # noqa: E402
from generators.ufw import UfwGenerator  # noqa: E402


@pytest.fixture
def fw_apply():
    """Persist to the (isolated) config-DB without running ufw."""
    applied = []
    firewall_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
    yield applied
    firewall_api.set_apply(None)


class TestFirewallApi:
    def test_status_defaults(self, test_client, auth_headers, fw_apply):
        r = test_client.get("/api/firewall/status", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["active"] is False
        assert d["defaults"] == {"incoming": "deny", "outgoing": "allow"}
        assert d["rules"] == []

    def test_mutations_require_admin(self, test_client, user_headers, fw_apply):
        assert test_client.post("/api/firewall/toggle", json={"enable": True},
                                headers=user_headers).status_code == 403
        assert test_client.post("/api/firewall/rule",
                                json={"port": "443/tcp", "action": "allow"},
                                headers=user_headers).status_code == 403
        assert test_client.delete("/api/firewall/rule/1",
                                  headers=user_headers).status_code == 403

    def test_add_rule_roundtrip(self, test_client, auth_headers, fw_apply):
        r = test_client.post("/api/firewall/rule",
                             json={"port": "445/tcp", "action": "allow",
                                   "from": "10.0.0.0/24", "comment": "smb lan"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text
        d = test_client.get("/api/firewall/status", headers=auth_headers).json()
        assert d["rules"][0]["to"] == "445/tcp"
        assert d["rules"][0]["from"] == "10.0.0.0/24"
        assert d["rules"][0]["comment"] == "smb lan"
        assert len(fw_apply) == 1                       # converge invoked

    def test_add_rule_rejects_garbage(self, test_client, auth_headers, fw_apply):
        for body in (
            {"port": "70000", "action": "allow"},                     # port range
            {"port": "1000:2000", "action": "allow"},                 # range w/o proto
            {"port": "22", "action": "allow", "from": "999.9.9.9"},   # bad ip
            {"port": "22", "action": "allow", "comment": "x'; ufw disable"},  # injection
            {"port": "22", "action": "nuke"},                         # bad action
        ):
            assert test_client.post("/api/firewall/rule", json=body,
                                    headers=auth_headers).status_code == 400, body

    def test_delete_rule(self, test_client, auth_headers, fw_apply):
        test_client.post("/api/firewall/rule", json={"port": "53", "action": "allow"},
                         headers=auth_headers)
        assert test_client.delete("/api/firewall/rule/1",
                                  headers=auth_headers).status_code == 200
        assert test_client.get("/api/firewall/status",
                               headers=auth_headers).json()["rules"] == []
        assert test_client.delete("/api/firewall/rule/9",
                                  headers=auth_headers).status_code == 404

    def test_toggle_and_defaults_persist(self, test_client, auth_headers, fw_apply):
        assert test_client.post("/api/firewall/toggle", json={"enable": True},
                                headers=auth_headers).status_code == 200
        assert test_client.put("/api/firewall/defaults", json={"incoming": "reject"},
                               headers=auth_headers).status_code == 200
        d = test_client.get("/api/firewall/status", headers=auth_headers).json()
        assert d["active"] is True and d["defaults"]["incoming"] == "reject"
        assert test_client.put("/api/firewall/defaults", json={"incoming": "open"},
                               headers=auth_headers).status_code == 400

    def test_services_preset(self, test_client, auth_headers):
        d = test_client.get("/api/firewall/services", headers=auth_headers).json()
        assert any(s["id"] == "ssh" for s in d["services"])


def _capture_gen():
    g = UfwGenerator()
    calls = []
    ok = type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})
    g._run = staticmethod(lambda cmd, check=True: (calls.append(cmd), ok())[1])
    return g, calls


class TestUfwConverge:
    """Lockout safety = command ORDER. These assertions are the guarantee."""

    def _cfg(self, **fw):
        cfg = fc.ForgeOSConfig()
        for k, v in fw.items():
            setattr(cfg.firewall, k, v)
        return cfg

    def test_reset_first_enable_last_guards_before_rules(self):
        g, calls = _capture_gen()
        cfg = self._cfg(enabled=True,
                        rules=[fc.FirewallRule(port="445", proto="tcp", comment="smb")])
        g.apply(cfg)
        flat = [" ".join(c) for c in calls]
        assert calls[0] == ["ufw", "--force", "reset"]
        assert calls[-1] == ["ufw", "--force", "enable"]
        guards = [i for i, s in enumerate(flat) if "management" in s]
        users = [i for i, s in enumerate(flat) if "smb" in s]
        assert guards and users and max(guards) < min(users)
        assert any(s.startswith("ufw limit") and "port 22" in s for s in flat)  # ssh rate-limited

    def test_disabled_config_ends_disabled(self):
        g, calls = _capture_gen()
        g.apply(self._cfg(enabled=False))
        assert calls[-1] == ["ufw", "--force", "disable"]
        assert not any("management" in " ".join(c) for c in calls)  # no guards when off

    def test_allow_incoming_skips_guards(self):
        g, calls = _capture_gen()
        g.apply(self._cfg(enabled=True, default_incoming="allow"))
        assert not any("management" in " ".join(c) for c in calls)

    def test_failure_raises_generator_error(self):
        from generators import GeneratorError
        g = UfwGenerator()
        bad = type("P", (), {"returncode": 1, "stderr": "boom", "stdout": ""})
        g._run = staticmethod(lambda cmd, check=True: bad())
        with pytest.raises(GeneratorError):
            g.apply(self._cfg(enabled=True))

    def test_family_semantics(self):
        g, _ = _capture_gen()
        assert g._rule_args(fc.FirewallRule(port="53", family="ipv6"))[:3] == \
            ["allow", "from", "::/0"]
        assert g._rule_args(fc.FirewallRule(port="53", family="ipv4"))[:3] == \
            ["allow", "from", "0.0.0.0/0"]
        assert g._rule_args(fc.FirewallRule(port="53")) == ["allow", "53"]
