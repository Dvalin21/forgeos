"""
Two-factor LOGIN challenge tests (Sprint 6 U2).

Covers the step-1 / step-2 split, and — most importantly — the OWASP
"force-browse past step 2" bypass: a password-only mfa_pending token must be
useless against every real endpoint. Also: TOTP login, backup-code login,
anti-replay at login, and that login for users WITHOUT 2FA is unchanged.

Uses the same conftest isolation as test_users / test_totp.
"""
import pyotp

from forgeos_auth import (save_users, load_users, pwd_ctx, create_token,
                          create_mfa_token, verify_ws_token)


def _seed(users: dict):
    out = {}
    for name, (pw, role) in users.items():
        out[name] = {"hash": pwd_ctx.hash(pw), "role": role}
    save_users(out)


def _hdr(username: str, role: str) -> dict:
    return {"Authorization": "Bearer " + create_token(username, role)}


def _enable_2fa(client, username, role):
    """Enroll + verify via the real API; returns (secret, backup_codes)."""
    r = client.post("/api/users/me/totp/enroll", headers=_hdr(username, role))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    code = pyotp.TOTP(secret).now()
    r = client.post("/api/users/me/totp/verify", json={"code": code},
                    headers=_hdr(username, role))
    assert r.status_code == 200, r.text
    return secret, r.json()["backup_codes"]


def _reset_replay(username):
    users = load_users()
    users[username]["totp_last_timecode"] = 0
    save_users(users)


class TestLoginWithoutTotp:
    def test_password_login_unchanged(self, test_client):
        """Userspace contract: a user without 2FA logs in exactly as before."""
        _seed({"alice": ("password1", "admin")})
        r = test_client.post("/api/auth/login",
                             json={"username": "alice", "password": "password1"})
        assert r.status_code == 200
        body = r.json()
        assert body["token"] and body["role"] == "admin"
        assert "mfa_required" not in body
        assert "forgeos_token" in r.headers.get("set-cookie", "")


class TestLoginChallenge:
    def test_login_returns_mfa_challenge_not_session(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable_2fa(test_client, "alice", "admin")
        r = test_client.post("/api/auth/login",
                             json={"username": "alice", "password": "password1"})
        assert r.status_code == 200
        body = r.json()
        assert body["mfa_required"] is True
        assert body["mfa_token"]
        assert "token" not in body                       # NOT a session token
        assert "forgeos_token" not in r.headers.get("set-cookie", "")

    def test_mfa_pending_token_cannot_access_endpoints(self, test_client):
        """THE bypass test: completing step 1 then force-browsing must fail."""
        _seed({"alice": ("password1", "admin")})
        _enable_2fa(test_client, "alice", "admin")
        r = test_client.post("/api/auth/login",
                             json={"username": "alice", "password": "password1"})
        mfa_token = r.json()["mfa_token"]
        # Use the pending token as if it were a session token.
        bypass = test_client.get(
            "/api/users", headers={"Authorization": "Bearer " + mfa_token})
        assert bypass.status_code == 401                  # rejected by verify_token

    def test_totp_completes_login_and_token_works(self, test_client):
        _seed({"alice": ("password1", "admin")})
        secret, _ = _enable_2fa(test_client, "alice", "admin")
        mfa_token = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        _reset_replay("alice")
        r = test_client.post("/api/auth/login/totp",
                             json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        assert "forgeos_token" in r.headers.get("set-cookie", "")
        # the issued session token is a REAL one — works on a protected route
        ok = test_client.get("/api/users", headers={"Authorization": "Bearer " + token})
        assert ok.status_code == 200

    def test_totp_wrong_code_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable_2fa(test_client, "alice", "admin")
        mfa_token = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        r = test_client.post("/api/auth/login/totp",
                             json={"mfa_token": mfa_token, "code": "000000"})
        assert r.status_code == 401

    def test_garbage_mfa_token_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable_2fa(test_client, "alice", "admin")
        r = test_client.post("/api/auth/login/totp",
                             json={"mfa_token": "not.a.token", "code": "123456"})
        assert r.status_code == 401

    def test_session_token_not_accepted_as_mfa_token(self, test_client):
        """A full session token must not be replayable as the second factor."""
        _seed({"alice": ("password1", "admin")})
        secret, _ = _enable_2fa(test_client, "alice", "admin")
        session = create_token("alice", "admin")
        _reset_replay("alice")
        r = test_client.post("/api/auth/login/totp",
                             json={"mfa_token": session, "code": pyotp.TOTP(secret).now()})
        assert r.status_code == 401                       # wrong scope


class TestBackupCodeLogin:
    def test_backup_code_logs_in_and_is_consumed(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _, codes = _enable_2fa(test_client, "alice", "admin")
        mfa_token = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        r = test_client.post("/api/auth/login/totp",
                             json={"mfa_token": mfa_token, "code": codes[0]})
        assert r.status_code == 200, r.text
        assert len(load_users()["alice"]["backup_codes"]) == 9   # one consumed
        # reusing the same backup code fails (single-use)
        mfa2 = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        r2 = test_client.post("/api/auth/login/totp",
                              json={"mfa_token": mfa2, "code": codes[0]})
        assert r2.status_code == 401


class TestAntiReplayAtLogin:
    def test_totp_code_cannot_be_replayed_across_logins(self, test_client):
        _seed({"alice": ("password1", "admin")})
        secret, _ = _enable_2fa(test_client, "alice", "admin")
        _reset_replay("alice")
        code = pyotp.TOTP(secret).now()
        # first login with the code succeeds
        mfa1 = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        assert test_client.post("/api/auth/login/totp",
                                json={"mfa_token": mfa1, "code": code}).status_code == 200
        # second login replaying the SAME code is rejected (watermark advanced)
        mfa2 = test_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password1"}).json()["mfa_token"]
        assert test_client.post("/api/auth/login/totp",
                                json={"mfa_token": mfa2, "code": code}).status_code == 401


class TestWebSocketGuard:
    class _FakeWS:
        def __init__(self, token):
            self.query_params = {"token": token}

    def test_ws_rejects_mfa_pending_but_accepts_session(self):
        assert verify_ws_token(self._FakeWS(create_mfa_token("alice"))) is None
        ok = verify_ws_token(self._FakeWS(create_token("alice", "admin")))
        assert ok is not None and ok["sub"] == "alice"
