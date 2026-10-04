"""B1 regression: WebSocket endpoints must reject half-auth scopes and
non-admin exec tokens. The REST equivalents already enforced this; the WS
handlers did not until verify/check were wired in."""
import pytest
from starlette.websockets import WebSocketDisconnect

from forgeos_auth import create_mfa_token, create_token


class TestWsAuthBoundary:
    def test_mfa_pending_token_rejected_on_metrics(self, test_client):
        mfa = create_mfa_token("testuser")
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_client.websocket_connect("/ws/metrics", subprotocols=["forgeos", mfa]):
                pass
        assert exc.value.code == 4001

    def test_garbage_token_rejected_on_metrics(self, test_client):
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_client.websocket_connect("/ws/metrics", subprotocols=["forgeos", "junk"]):
                pass
        assert exc.value.code == 4001

    def test_non_admin_rejected_on_docker_exec(self, test_client):
        user_tok = create_token("testuser", "user")
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_client.websocket_connect("/ws/docker/exec/abc", subprotocols=["forgeos", user_tok]):
                pass
        assert exc.value.code == 4003

    def test_mfa_pending_rejected_on_docker_exec(self, test_client):
        mfa = create_mfa_token("admin")
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_client.websocket_connect("/ws/docker/exec/abc", subprotocols=["forgeos", mfa]):
                pass
        assert exc.value.code == 4001

    def test_admin_token_accepted_on_metrics(self, test_client):
        admin_tok = create_token("testadmin", "admin")
        with test_client.websocket_connect("/ws/metrics", subprotocols=["forgeos", admin_tok]) as ws:
            msg = ws.receive_json()
            assert "cpu_pct" in msg
