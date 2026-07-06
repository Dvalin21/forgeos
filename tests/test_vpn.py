"""VPN API (v2) — config-DB backed, return-once client keys.

Peers live in cfg.wireguard.peers[]; the generator renders the server conf.
The legacy forgeos-vpn CLI is gone. Client private keys are never persisted —
add_peer returns the .conf once. subprocess (wg/qrencode/systemctl) is mocked.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import forgeos_config as fc  # noqa: E402
import vpn_api  # noqa: E402


@pytest.fixture
def wg_apply():
    """Persist to isolated config-DB without rendering/reloading wg."""
    applied = []
    vpn_api.set_apply(lambda cfg: applied.append(cfg) or fc.save(cfg))
    yield applied
    vpn_api.set_apply(None)


def _wg(cmd, *a, **k):
    """Fake wg/qrencode/systemctl. genkey/pubkey return deterministic keys."""
    exe = cmd[0]
    r = MagicMock(returncode=0, stderr="", stdout="")
    if cmd[:1] == ["wg"] and cmd[1:2] == ["genkey"]:
        r.stdout = "PRIVKEY0000000000000000000000000000000000000=\n"
    elif cmd[:1] == ["wg"] and cmd[1:2] == ["pubkey"]:
        r.stdout = "PUBKEY00000000000000000000000000000000000000=\n"
    elif cmd[:2] == ["wg", "show"]:
        r.stdout = ""                       # interface down / no handshakes
    elif exe == "qrencode":
        r.stdout = b"\x89PNG_fake"
    elif exe == "systemctl":
        r.stdout = ""
    return r


class TestPeerLifecycle:
    def test_add_returns_config_once_never_persists_privkey(self, test_client, auth_headers, wg_apply, tmp_path, monkeypatch):
        monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
        with patch("subprocess.run", side_effect=_wg):
            r = test_client.post("/api/vpn/peers",
                                 json={"name": "laptop", "endpoint": "vpn.example.com"},
                                 headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "PrivateKey = PRIVKEY" in d["config"]     # client privkey returned...
        assert d["qr"].startswith("data:image/png;base64,")
        assert "only once" in d["warning"]
        # ...but the SERVER config-DB stores only the public key
        cfg = fc.load()
        assert cfg.wireguard.peers[0].public_key.startswith("PUBKEY")
        assert cfg.wireguard.peers[0].address == "10.10.0.2/32"   # .1 is server
        assert not any("PRIV" in p.public_key for p in cfg.wireguard.peers)

    def test_ip_allocation_skips_taken(self, test_client, auth_headers, wg_apply, tmp_path, monkeypatch):
        monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
        with patch("subprocess.run", side_effect=_wg):
            test_client.post("/api/vpn/peers", json={"name": "a"}, headers=auth_headers)
            r = test_client.post("/api/vpn/peers", json={"name": "b"}, headers=auth_headers)
        assert r.json()["address"] == "10.10.0.3/32"

    def test_duplicate_name_rejected(self, test_client, auth_headers, wg_apply, tmp_path, monkeypatch):
        monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
        with patch("subprocess.run", side_effect=_wg):
            test_client.post("/api/vpn/peers", json={"name": "dup"}, headers=auth_headers)
            r = test_client.post("/api/vpn/peers", json={"name": "dup"}, headers=auth_headers)
        assert r.status_code == 409

    def test_bad_dns_rejected(self, test_client, auth_headers, wg_apply, tmp_path, monkeypatch):
        monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
        with patch("subprocess.run", side_effect=_wg):
            r = test_client.post("/api/vpn/peers",
                                 json={"name": "x", "dns": "not;an;ip"}, headers=auth_headers)
        assert r.status_code == 400

    def test_list_and_remove(self, test_client, auth_headers, wg_apply, tmp_path, monkeypatch):
        monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
        with patch("subprocess.run", side_effect=_wg):
            test_client.post("/api/vpn/peers", json={"name": "gone"}, headers=auth_headers)
            lst = test_client.get("/api/vpn/peers", headers=auth_headers).json()
            assert lst["count"] == 1 and lst["peers"][0]["name"] == "gone"
            assert test_client.delete("/api/vpn/peers/gone", headers=auth_headers).status_code == 200
            assert test_client.delete("/api/vpn/peers/gone", headers=auth_headers).status_code == 404


class TestGating:
    def test_mutations_require_admin(self, test_client, user_headers):
        assert test_client.post("/api/vpn/peers", json={"name": "x"}, headers=user_headers).status_code == 403
        assert test_client.delete("/api/vpn/peers/x", headers=user_headers).status_code == 403
        assert test_client.post("/api/vpn/control/restart", headers=user_headers).status_code == 403

    def test_status_any_user(self, test_client, user_headers):
        with patch("subprocess.run", side_effect=_wg):
            assert test_client.get("/api/vpn/status", headers=user_headers).status_code == 200


class TestControl:
    def test_control_valid_action(self, test_client, auth_headers):
        with patch("subprocess.run", side_effect=_wg) as m:
            r = test_client.post("/api/vpn/control/restart", headers=auth_headers)
        assert r.status_code == 200
        assert any(c.args[0][:2] == ["systemctl", "restart"] for c in m.call_args_list)

    def test_control_bad_action(self, test_client, auth_headers):
        assert test_client.post("/api/vpn/control/nuke", headers=auth_headers).status_code == 400


def test_server_key_generated_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("generators.wireguard.WG_KEY_DIR", str(tmp_path))
    from generators.wireguard import WireGuardGenerator
    with patch("subprocess.run", side_effect=_wg):
        pub = WireGuardGenerator().ensure_server_key()
    assert pub.startswith("PUBKEY")
    assert (tmp_path / "server.key").exists()
    assert oct((tmp_path / "server.key").stat().st_mode)[-3:] == "600"
