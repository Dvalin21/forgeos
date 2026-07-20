"""Session revocation via token_epoch — a token minted before the user's
current epoch is rejected. This is what invalidates old sessions on password
change / admin reset / role change (Finding #1 from the auth review)."""
import json
import pytest
from jose import jwt as jose_jwt


def _seed_user(name, role="user", epoch=0, pw="oldpassword1"):
    """Write a user record into the isolated store the fixtures set up."""
    from forgeos_auth import load_users, save_users, pwd_ctx
    users = load_users()
    users[name] = {"hash": pwd_ctx.hash(pw), "role": role, "token_epoch": epoch}
    save_users(users)
    return users[name]


def _token(name, role, epoch):
    from forgeos_auth import create_token
    return create_token(name, role, epoch)


class TestTokenEpochClaim:
    def test_create_token_embeds_epoch(self):
        from forgeos_auth import create_token, JWT_SECRET, JWT_ALGO
        tok = create_token("bob", "user", 7)
        p = jose_jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
        assert p["epoch"] == 7

    def test_create_token_default_epoch_zero(self):
        # backward compat: tokens minted without an explicit epoch are 0
        from forgeos_auth import create_token, JWT_SECRET, JWT_ALGO
        tok = create_token("bob", "user")
        p = jose_jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
        assert p["epoch"] == 0


class TestEpochEnforcement:
    """verify_token via a real protected endpoint (/api/auth/change-password
    requires a valid session)."""

    def test_stale_token_rejected(self, test_client):
        # user is at epoch 2; a token minted at epoch 1 is stale -> 401
        _seed_user("alice", "user", epoch=2)
        stale = _token("alice", "user", 1)
        r = test_client.get("/api/audit",
                            headers={"Authorization": f"Bearer {stale}"})
        assert r.status_code == 401

    def test_current_token_accepted(self, test_client):
        _seed_user("alice", "user", epoch=2)
        good = _token("alice", "user", 2)
        r = test_client.get("/api/audit",
                            headers={"Authorization": f"Bearer {good}"})
        assert r.status_code == 200

    def test_untouched_user_no_forced_logout(self, test_client):
        # user with NO token_epoch key + token with epoch 0 (or absent) must
        # keep working — no mass logout on deploy
        from forgeos_auth import load_users, save_users, pwd_ctx
        users = load_users()
        users["carol"] = {"hash": pwd_ctx.hash("pw12345678"), "role": "admin"}  # no token_epoch
        save_users(users)
        tok = _token("carol", "admin", 0)
        r = test_client.get("/api/audit", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200

    def test_newer_token_epoch_accepted(self, test_client):
        # defensive: token epoch > store epoch (shouldn't happen, but must not lock out)
        _seed_user("alice", "user", epoch=1)
        tok = _token("alice", "user", 5)
        r = test_client.get("/api/audit", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200


class TestChangePasswordRevokesSessions:
    def test_change_password_bumps_epoch_and_reissues(self, test_client):
        u = _seed_user("dave", "user", epoch=0, pw="oldpassword1")
        tok = _token("dave", "user", 0)
        r = test_client.post("/api/auth/change-password",
                             json={"current": "oldpassword1", "new": "newpassword2"},
                             headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        # a fresh token comes back (caller stays logged in)
        assert "token" in r.json()
        # the store epoch was bumped
        from forgeos_auth import load_users
        assert load_users()["dave"]["token_epoch"] == 1
        # the OLD token is now dead
        r2 = test_client.get("/api/audit", headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 401
        # the NEW token works
        new_tok = r.json()["token"]
        r3 = test_client.get("/api/audit", headers={"Authorization": f"Bearer {new_tok}"})
        assert r3.status_code == 200

    def test_change_password_wrong_current_rejected(self, test_client):
        _seed_user("dave", "user", epoch=0, pw="oldpassword1")
        tok = _token("dave", "user", 0)
        r = test_client.post("/api/auth/change-password",
                             json={"current": "WRONG", "new": "newpassword2"},
                             headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401


class TestChangePasswordValidation:
    """Finding #2: change-password had no validation (KeyError 500, no length)."""

    def test_missing_new_is_422_not_500(self, test_client):
        _seed_user("dave", "user", epoch=0, pw="oldpassword1")
        tok = _token("dave", "user", 0)
        r = test_client.post("/api/auth/change-password",
                             json={"current": "oldpassword1"},   # no 'new'
                             headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 422        # Pydantic validation, not a crash

    def test_short_new_password_rejected(self, test_client):
        _seed_user("dave", "user", epoch=0, pw="oldpassword1")
        tok = _token("dave", "user", 0)
        r = test_client.post("/api/auth/change-password",
                             json={"current": "oldpassword1", "new": "short"},
                             headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 422        # min_length=8


class TestAdminActionsRevokeSessions:
    """Admin password reset and role change must also invalidate the target
    user's existing sessions (same Finding #1 class)."""

    def test_admin_reset_bumps_target_epoch(self, test_client, auth_headers):
        # seed target + an admin who performs the reset
        _seed_user("victim", "user", epoch=0, pw="oldpassword1")
        # the admin doing the reset is 'testadmin' (auth_headers), epoch 0, no record needed
        old_tok = _token("victim", "user", 0)
        r = test_client.post("/api/users/victim/password",
                             json={"password": "resetpassword9"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        from forgeos_auth import load_users
        assert load_users()["victim"]["token_epoch"] == 1
        # victim's old session is dead
        r2 = test_client.get("/api/audit", headers={"Authorization": f"Bearer {old_tok}"})
        assert r2.status_code == 401

    def test_role_change_bumps_target_epoch(self, test_client, auth_headers):
        # a second admin exists so demoting 'victim' isn't blocked by last-admin guard
        _seed_user("keepadmin", "admin", epoch=0)
        _seed_user("victim", "admin", epoch=0)
        old_admin_tok = _token("victim", "admin", 0)
        r = test_client.put("/api/users/victim/role",
                            json={"role": "user"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        from forgeos_auth import load_users
        assert load_users()["victim"]["token_epoch"] == 1
        # victim's OLD admin token (role=admin, epoch=0) is now dead -> can't keep admin
        r2 = test_client.get("/api/audit", headers={"Authorization": f"Bearer {old_admin_tok}"})
        assert r2.status_code == 401
