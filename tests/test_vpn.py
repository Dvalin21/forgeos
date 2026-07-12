"""Tests for vpn_api.py — WireGuard peer management (LTH-001).

vpn_api wraps the forgeos-vpn CLI and reads peer metadata from
/etc/forgeos/vpn/peers/. Tests redirect PEERS_DIR to a temp dir and
mock the subprocess calls so no real WireGuard/CLI is needed.

Coverage:
  GET    /api/vpn/status
  GET    /api/vpn/peers
  POST   /api/vpn/peers              (admin, validation, dup-check)
  DELETE /api/vpn/peers/{name}       (admin, 404)
  GET    /api/vpn/peers/{name}/config (admin)
  POST   /api/vpn/control/{action}   (admin, action validation)
  peer-name validation (security: reject path traversal / junk)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def vpn_peers_dir(tmp_path, monkeypatch):
    """Redirect vpn_api.PEERS_DIR to a temp dir for the duration of a test."""
    import vpn_api
    peers = tmp_path / "peers"
    peers.mkdir()
    monkeypatch.setattr(vpn_api, "PEERS_DIR", peers)
    return peers


def _make_peer(peers_dir: Path, name: str, ip: str = "10.10.0.2"):
    """Create a fake peer directory with meta.json + public.key + .conf."""
    d = peers_dir / name
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "name": name, "ip": ip, "created": "2026-06-06T00:00:00Z",
        "allowed_ips": "0.0.0.0/0",
    }))
    (d / "public.key").write_text("FAKEPUBKEY" + name)
    (d / f"{name}.conf").write_text(f"[Interface]\n# config for {name}\n")
    return d


class TestVpnStatus:
    def test_requires_auth(self, test_client):
        assert test_client.get("/api/vpn/status").status_code in (401, 403)

    def test_status_running(self, test_client, auth_headers):
        import vpn_api
        with patch.object(vpn_api, "_run_args", return_value="interface: wg0\n  listening port: 51820"):
            resp = test_client.get("/api/vpn/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["running"] is True

    def test_status_not_running(self, test_client, auth_headers):
        import vpn_api
        with patch.object(vpn_api, "_run_args", return_value="WireGuard not running"):
            resp = test_client.get("/api/vpn/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["running"] is False


class TestListPeers:
    def test_requires_auth(self, test_client):
        assert test_client.get("/api/vpn/peers").status_code in (401, 403)

    def test_empty_when_no_peers(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        with patch.object(vpn_api, "_run_args", return_value=""):
            resp = test_client.get("/api/vpn/peers", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"peers": [], "count": 0}

    def test_lists_peers_from_meta(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        _make_peer(vpn_peers_dir, "laptop", ip="10.10.0.2")
        _make_peer(vpn_peers_dir, "phone", ip="10.10.0.3")
        with patch.object(vpn_api, "_run_args", return_value=""):
            resp = test_client.get("/api/vpn/peers", headers=auth_headers)
        data = resp.json()
        assert data["count"] == 2
        names = {p["name"] for p in data["peers"]}
        assert names == {"laptop", "phone"}

    def test_online_status_from_handshake(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        _make_peer(vpn_peers_dir, "laptop")
        # wg show latest-handshakes returns "<pubkey>\t<epoch>"
        handshake_out = "FAKEPUBKEYlaptop\t1717632000"
        with patch.object(vpn_api, "_run_args", return_value=handshake_out):
            resp = test_client.get("/api/vpn/peers", headers=auth_headers)
        peer = resp.json()["peers"][0]
        assert peer["online"] is True
        assert peer["last_handshake_epoch"] == 1717632000

    def test_offline_when_handshake_zero(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        _make_peer(vpn_peers_dir, "laptop")
        with patch.object(vpn_api, "_run_args", return_value="FAKEPUBKEYlaptop\t0"):
            resp = test_client.get("/api/vpn/peers", headers=auth_headers)
        assert resp.json()["peers"][0]["online"] is False


class TestAddPeer:
    def test_requires_auth(self, test_client):
        assert test_client.post("/api/vpn/peers", json={"name": "x"}).status_code in (401, 403)

    def test_requires_admin(self, test_client, user_headers, vpn_peers_dir):
        resp = test_client.post("/api/vpn/peers", json={"name": "laptop"}, headers=user_headers)
        assert resp.status_code == 403

    def test_add_peer_success(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        with patch.object(vpn_api, "_run_checked", return_value="Peer 'laptop' added: 10.10.0.2") as mock_run:
            resp = test_client.post("/api/vpn/peers", json={"name": "laptop"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # The CLI was called with add + name + dns + allowed_ips
        args = mock_run.call_args[0][0]
        assert args[:3] == ["forgeos-vpn", "add", "laptop"]

    def test_rejects_duplicate(self, test_client, auth_headers, vpn_peers_dir):
        _make_peer(vpn_peers_dir, "laptop")
        resp = test_client.post("/api/vpn/peers", json={"name": "laptop"}, headers=auth_headers)
        assert resp.status_code == 409

    def test_rejects_invalid_name_traversal(self, test_client, auth_headers, vpn_peers_dir):
        # Path-traversal attempt must be rejected by name validation
        resp = test_client.post("/api/vpn/peers", json={"name": "../etc"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_rejects_empty_name(self, test_client, auth_headers, vpn_peers_dir):
        resp = test_client.post("/api/vpn/peers", json={"name": ""}, headers=auth_headers)
        assert resp.status_code == 400

    def test_rejects_bad_dns(self, test_client, auth_headers, vpn_peers_dir):
        resp = test_client.post(
            "/api/vpn/peers",
            json={"name": "laptop", "dns": "8.8.8.8; rm -rf /"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_passes_custom_dns_and_allowed_ips(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        with patch.object(vpn_api, "_run_checked", return_value="ok") as mock_run:
            test_client.post(
                "/api/vpn/peers",
                json={"name": "laptop", "dns": "1.1.1.1", "allowed_ips": "10.10.0.0/24"},
                headers=auth_headers,
            )
        args = mock_run.call_args[0][0]
        assert args == ["forgeos-vpn", "add", "laptop", "1.1.1.1", "10.10.0.0/24"]


class TestRemovePeer:
    def test_requires_admin(self, test_client, user_headers, vpn_peers_dir):
        _make_peer(vpn_peers_dir, "laptop")
        resp = test_client.delete("/api/vpn/peers/laptop", headers=user_headers)
        assert resp.status_code == 403

    def test_remove_success(self, test_client, auth_headers, vpn_peers_dir):
        import vpn_api
        _make_peer(vpn_peers_dir, "laptop")
        with patch.object(vpn_api, "_run_checked", return_value="Peer 'laptop' removed") as mock_run:
            resp = test_client.delete("/api/vpn/peers/laptop", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        args = mock_run.call_args[0][0]
        assert args == ["forgeos-vpn", "remove", "laptop"]

    def test_remove_missing_404(self, test_client, auth_headers, vpn_peers_dir):
        resp = test_client.delete("/api/vpn/peers/ghost", headers=auth_headers)
        assert resp.status_code == 404

    def test_remove_invalid_name_400(self, test_client, auth_headers, vpn_peers_dir):
        resp = test_client.delete("/api/vpn/peers/..%2Fetc", headers=auth_headers)
        # A name with a literal/encoded slash (`..%2Fetc`) makes Starlette
        # reject the path shape (extra segment) before the handler runs,
        # returning 405 — the dangerous op is never executed. Accept 400/404/405.
        assert resp.status_code in (400, 404, 405)


class TestPeerConfig:
    def test_requires_admin(self, test_client, user_headers, vpn_peers_dir):
        _make_peer(vpn_peers_dir, "laptop")
        resp = test_client.get("/api/vpn/peers/laptop/config", headers=user_headers)
        assert resp.status_code == 403

    def test_returns_config_text(self, test_client, auth_headers, vpn_peers_dir):
        _make_peer(vpn_peers_dir, "laptop")
        resp = test_client.get("/api/vpn/peers/laptop/config", headers=auth_headers)
        assert resp.status_code == 200
        assert "config for laptop" in resp.text

    def test_missing_config_404(self, test_client, auth_headers, vpn_peers_dir):
        resp = test_client.get("/api/vpn/peers/ghost/config", headers=auth_headers)
        assert resp.status_code in (400, 404)


class TestVpnControl:
    def test_requires_admin(self, test_client, user_headers):
        resp = test_client.post("/api/vpn/control/restart", headers=user_headers)
        assert resp.status_code == 403

    def test_valid_action(self, test_client, auth_headers):
        import vpn_api
        with patch.object(vpn_api, "_run_checked", return_value="WireGuard restarted") as mock_run:
            resp = test_client.post("/api/vpn/control/restart", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["action"] == "restart"
        assert mock_run.call_args[0][0] == ["forgeos-vpn", "restart"]

    def test_invalid_action_rejected(self, test_client, auth_headers):
        resp = test_client.post("/api/vpn/control/destroy", headers=auth_headers)
        assert resp.status_code == 400
