"""
Auth-policy tests (Sprint 6 U2b): the admin "require 2FA for new accounts"
switch, the totp_required flag it stamps on new users, and the
enrollment_required signal login returns for a flagged-but-not-enrolled user.

Config-DB is isolated to a temp path by the autouse conftest fixture.
"""
import pyotp

from forgeos_auth import save_users, load_users, pwd_ctx, create_token


def _seed(users: dict):
    out = {}
    for name, (pw, role) in users.items():
        out[name] = {"hash": pwd_ctx.hash(pw), "role": role}
    save_users(out)


def _hdr(username: str, role: str) -> dict:
    return {"Authorization": "Bearer " + create_token(username, role)}


def _set_policy(client, admin, value: bool):
    r = client.put("/api/auth/policy",
                   json={"require_totp_new_users": value}, headers=_hdr(admin, "admin"))
    assert r.status_code == 200, r.text
    return r


class TestPolicyEndpoint:
    def test_get_requires_admin(self, test_client):
        _seed({"bob": ("password2", "user")})
        assert test_client.get("/api/auth/policy",
                               headers=_hdr("bob", "user")).status_code == 403

    def test_default_is_off(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.get("/api/auth/policy", headers=_hdr("alice", "admin"))
        assert r.status_code == 200
        assert r.json()["require_totp_new_users"] is False

    def test_put_toggles_and_persists(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _set_policy(test_client, "alice", True)
        r = test_client.get("/api/auth/policy", headers=_hdr("alice", "admin"))
        assert r.json()["require_totp_new_users"] is True

    def test_put_requires_admin(self, test_client):
        _seed({"alice": ("password1", "admin"), "bob": ("password2", "user")})
        r = test_client.put("/api/auth/policy",
                            json={"require_totp_new_users": True}, headers=_hdr("bob", "user"))
        assert r.status_code == 403

    def test_put_missing_field_400(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.put("/api/auth/policy", json={}, headers=_hdr("alice", "admin"))
        assert r.status_code == 400


class TestNewUserFlagging:
    def test_policy_on_flags_new_user(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _set_policy(test_client, "alice", True)
        r = test_client.post("/api/users",
                             json={"username": "carol", "password": "password123", "role": "user"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        assert r.json()["user"]["totp_required"] is True
        assert load_users()["carol"].get("totp_required") is True

    def test_policy_off_does_not_flag(self, test_client):
        _seed({"alice": ("password1", "admin")})
        # policy defaults off
        r = test_client.post("/api/users",
                             json={"username": "dave", "password": "password123", "role": "user"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        assert r.json()["user"]["totp_required"] is False
        assert "totp_required" not in load_users()["dave"]


class TestLoginEnrollmentRequired:
    def test_required_but_not_enrolled_signals_enrollment(self, test_client):
        _seed({"bob": ("password2", "user")})
        users = load_users(); users["bob"]["totp_required"] = True; save_users(users)
        r = test_client.post("/api/auth/login",
                             json={"username": "bob", "password": "password2"})
        assert r.status_code == 200
        body = r.json()
        # gets a real session (so it can call the enroll endpoints) ...
        assert body["token"] and "forgeos_token" in r.headers.get("set-cookie", "")
        # ... but is told enrollment is mandatory
        assert body["enrollment_required"] is True

    def test_enabled_takes_precedence_over_required(self, test_client):
        """Once enrolled, login is the normal 2FA challenge — no enrollment flag."""
        _seed({"bob": ("password2", "user")})
        # enroll bob
        secret = test_client.post("/api/users/me/totp/enroll",
                                  headers=_hdr("bob", "user")).json()["secret"]
        test_client.post("/api/users/me/totp/verify",
                         json={"code": pyotp.TOTP(secret).now()}, headers=_hdr("bob", "user"))
        # also mark required (belt and suspenders)
        users = load_users(); users["bob"]["totp_required"] = True; save_users(users)
        r = test_client.post("/api/auth/login",
                             json={"username": "bob", "password": "password2"})
        body = r.json()
        assert body["mfa_required"] is True
        assert "enrollment_required" not in body
        assert "token" not in body

    def test_normal_user_has_no_enrollment_flag(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.post("/api/auth/login",
                             json={"username": "alice", "password": "password1"})
        body = r.json()
        assert "enrollment_required" not in body
        assert body["token"]
