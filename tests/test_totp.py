"""
TOTP / 2FA tests (Sprint 6 U1): enroll, verify-before-enable, disable with
re-auth, backup-code regeneration, admin recovery reset, and the no-leak
invariant on the public view. Plus unit checks of the two security
invariants the helpers must hold: TOTP anti-replay and single-use backup codes.

The autouse conftest fixture isolates USERS_FILE to a temp dir; these tests
populate it via save_users (through _seed), exactly like test_users.py.
"""
import time

import pyotp

from forgeos_auth import save_users, load_users, pwd_ctx, create_token
import forgeos_auth as fa


def _seed(users: dict):
    out = {}
    for name, (pw, role) in users.items():
        out[name] = {"hash": pwd_ctx.hash(pw), "role": role}
    save_users(out)


def _hdr(username: str, role: str) -> dict:
    return {"Authorization": "Bearer " + create_token(username, role)}


def _enroll(client, username="alice", role="admin") -> str:
    r = client.post("/api/users/me/totp/enroll", headers=_hdr(username, role))
    assert r.status_code == 200, r.text
    return r.json()["secret"]


def _enable(client, username="alice", role="admin"):
    """Full enroll + verify. Returns (secret, backup_codes)."""
    secret = _enroll(client, username, role)
    code = pyotp.TOTP(secret).now()
    r = client.post("/api/users/me/totp/verify", json={"code": code},
                    headers=_hdr(username, role))
    assert r.status_code == 200, r.text
    return secret, r.json()["backup_codes"]


def _reset_replay_guard(username="alice"):
    """Drop the anti-replay watermark so a *current* code is accepted in tests
    (mirrors time having advanced past the code consumed at enable)."""
    users = load_users()
    users[username]["totp_last_timecode"] = 0
    save_users(users)


class TestEnroll:
    def test_requires_auth(self, test_client):
        assert test_client.post("/api/users/me/totp/enroll").status_code in (401, 403)

    def test_returns_secret_and_uri_without_enabling(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.post("/api/users/me/totp/enroll", headers=_hdr("alice", "admin"))
        assert r.status_code == 200
        body = r.json()
        assert len(body["secret"]) == 32
        assert body["uri"].startswith("otpauth://totp/")
        assert body["issuer"] == "ForgeOS"
        rec = load_users()["alice"]
        assert rec.get("totp_enabled") is not True          # not active yet
        assert rec.get("totp_pending_secret") == body["secret"]

    def test_conflicts_when_already_enabled(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable(test_client)
        r = test_client.post("/api/users/me/totp/enroll", headers=_hdr("alice", "admin"))
        assert r.status_code == 409


class TestVerify:
    def test_enables_and_returns_backup_codes(self, test_client):
        _seed({"alice": ("password1", "admin")})
        secret, codes = _enable(test_client)
        assert len(codes) == 10
        rec = load_users()["alice"]
        assert rec["totp_enabled"] is True
        assert rec["totp_secret"] == secret
        assert "totp_pending_secret" not in rec
        assert len(rec["backup_codes"]) == 10
        # backup codes are stored HASHED, never plaintext
        assert codes[0] not in rec["backup_codes"]
        assert rec["backup_codes"][0].startswith("$2")       # bcrypt

    def test_wrong_code_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enroll(test_client)
        r = test_client.post("/api/users/me/totp/verify", json={"code": "000000"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 400
        assert load_users()["alice"].get("totp_enabled") is not True

    def test_without_enroll_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.post("/api/users/me/totp/verify", json={"code": "123456"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 400


class TestDisable:
    def test_with_current_code(self, test_client):
        _seed({"alice": ("password1", "admin")})
        secret, _ = _enable(test_client)
        _reset_replay_guard()
        code = pyotp.TOTP(secret).now()
        r = test_client.post("/api/users/me/totp/disable", json={"code": code},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        rec = load_users()["alice"]
        assert rec.get("totp_enabled") is not True
        assert "totp_secret" not in rec and "backup_codes" not in rec

    def test_with_password(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable(test_client)
        r = test_client.post("/api/users/me/totp/disable", json={"password": "password1"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        assert load_users()["alice"].get("totp_enabled") is not True

    def test_wrong_reauth_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable(test_client)
        r = test_client.post("/api/users/me/totp/disable", json={"password": "wrong"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 401
        assert load_users()["alice"]["totp_enabled"] is True   # still on

    def test_when_not_enabled(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.post("/api/users/me/totp/disable", json={"password": "password1"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 400


class TestBackupCodeRegeneration:
    def test_regenerate_replaces_codes(self, test_client):
        _seed({"alice": ("password1", "admin")})
        secret, old = _enable(test_client)
        old_hashes = list(load_users()["alice"]["backup_codes"])
        _reset_replay_guard()
        code = pyotp.TOTP(secret).now()
        r = test_client.post("/api/users/me/totp/backup-codes", json={"code": code},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        new = r.json()["backup_codes"]
        assert len(new) == 10 and new != old
        assert load_users()["alice"]["backup_codes"] != old_hashes

    def test_regenerate_bad_code_rejected(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable(test_client)
        r = test_client.post("/api/users/me/totp/backup-codes", json={"code": "000000"},
                             headers=_hdr("alice", "admin"))
        assert r.status_code == 400


class TestAdminReset:
    def test_admin_clears_user_2fa(self, test_client):
        _seed({"alice": ("password1", "admin"), "bob": ("password2", "user")})
        # bob enables his own 2FA
        _enable(test_client, "bob", "user")
        assert load_users()["bob"]["totp_enabled"] is True
        # alice (admin) resets it
        r = test_client.delete("/api/users/bob/totp", headers=_hdr("alice", "admin"))
        assert r.status_code == 200, r.text
        rec = load_users()["bob"]
        assert rec.get("totp_enabled") is not True
        assert "totp_secret" not in rec

    def test_non_admin_forbidden(self, test_client):
        _seed({"alice": ("password1", "admin"), "bob": ("password2", "user")})
        r = test_client.delete("/api/users/alice/totp", headers=_hdr("bob", "user"))
        assert r.status_code == 403

    def test_missing_user_404(self, test_client):
        _seed({"alice": ("password1", "admin")})
        r = test_client.delete("/api/users/ghost/totp", headers=_hdr("alice", "admin"))
        assert r.status_code == 404


class TestNoSecretLeak:
    def test_list_users_hides_totp_secrets(self, test_client):
        _seed({"alice": ("password1", "admin")})
        _enable(test_client)
        r = test_client.get("/api/users", headers=_hdr("alice", "admin"))
        assert r.status_code == 200
        blob = r.text
        assert "totp_secret" not in blob
        assert "backup_codes" not in blob or "backup_codes_remaining" in blob
        alice = next(u for u in r.json()["users"] if u["username"] == "alice")
        assert alice["totp_enabled"] is True
        assert alice["backup_codes_remaining"] == 10


class TestHelperInvariants:
    def test_totp_anti_replay(self):
        secret = fa.generate_totp_secret()
        code = pyotp.TOTP(secret).now()
        ok, tc = fa.verify_totp(secret, code)
        assert ok and tc is not None
        ok2, _ = fa.verify_totp(secret, code, last_timecode=tc)
        assert not ok2                                          # reuse rejected
        assert fa.verify_totp(secret, "000000")[0] is False    # bad code

    def test_backup_codes_single_use_and_hyphen_insensitive(self):
        display, hashed = fa.generate_backup_codes()
        assert len(display) == 10 and len(hashed) == 10
        ok, remaining = fa.consume_backup_code(display[0], hashed)
        assert ok and len(remaining) == 9
        ok2, _ = fa.consume_backup_code(display[0], remaining)
        assert not ok2                                          # single-use
        ok3, _ = fa.consume_backup_code(display[1].replace("-", ""), remaining)
        assert ok3                                              # hyphen ignored


class TestEnrollQr:
    def test_enroll_carries_qr_when_qrencode_present(self, test_client):
        _seed({"alice": ("password1", "admin")})
        from unittest.mock import patch, MagicMock
        fake = MagicMock(returncode=0, stdout=b"\x89PNG_fake")
        with patch("subprocess.run", return_value=fake):
            r = test_client.post("/api/users/me/totp/enroll", headers=_hdr("alice", "admin"))
        assert r.status_code == 200
        assert r.json()["qr"].startswith("data:image/png;base64,")

    def test_enroll_survives_missing_qrencode(self, test_client):
        _seed({"alice": ("password1", "admin")})
        from unittest.mock import patch
        with patch("subprocess.run", side_effect=OSError("not installed")):
            r = test_client.post("/api/users/me/totp/enroll", headers=_hdr("alice", "admin"))
        assert r.status_code == 200
        body = r.json()
        assert body["qr"] is None
        assert body["secret"] and body["uri"].startswith("otpauth://")
