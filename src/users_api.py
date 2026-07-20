"""ForgeOS — User management API (Sprint 6 / native Option A).

Mounts under the existing FastAPI app via:

    from users_api import router as users_router, set_helpers as set_users_helpers
    set_users_helpers(audit=_audit)
    app.include_router(users_router)

Routes (/api/users/*), all admin-only:
  GET    /api/users                     list users (no secrets)
  POST   /api/users                     create user
  DELETE /api/users/{username}          delete user
  PUT    /api/users/{username}/role     change role
  POST   /api/users/{username}/password admin reset password

Lockout guards (the whole reason this module is careful):
  - Cannot delete the last admin.
  - Cannot demote the last admin.
  - Cannot delete yourself (foot-gun: losing your own session mid-op).

The user record in api-users.json is:
    { "<username>": {"hash": "<bcrypt>", "role": "admin"|"user", ...} }
TOTP fields (totp_secret, totp_enabled, backup_codes) are added by
the 2FA commits but this module never exposes them in list output.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import load_users, save_users, pwd_ctx, verify_token, verify_enroll_or_session
import forgeos_auth as fa
import forgeos_config as fcfg

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Usernames: conservative, since they key a JSON object and appear in logs.
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_VALID_ROLES = ("admin", "user")

_audit: Optional[Callable[..., None]] = None


def set_helpers(audit: Callable[..., None]) -> None:
    global _audit
    _audit = audit


def _require_admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


def _admin_count(users: dict) -> int:
    return sum(1 for u in users.values() if u.get("role") == "admin")


def _validate_username(name: str) -> str:
    if not _USERNAME_RE.match(name):
        raise HTTPException(
            400,
            "Invalid username. Use 1-32 chars: lowercase letters, digits, "
            "hyphen, underscore; must start with a letter or digit.",
        )
    return name


def _public_view(username: str, rec: dict) -> dict:
    """Return only non-secret fields for a user record."""
    return {
        "username": username,
        "role": rec.get("role", "user"),
        "totp_enabled": bool(rec.get("totp_enabled", False)),
        "totp_required": bool(rec.get("totp_required", False)),
        "backup_codes_remaining": len(rec.get("backup_codes", [])),
    }


@router.get("/api/users/me")
async def get_me(user=Depends(verify_token)):
    """Own public record — lets any user (not just admins) see their 2FA
    state and backup-code count on the profile page."""
    users = load_users()
    rec = users.get(user["sub"])
    if rec is None:
        raise HTTPException(404, "User not found")
    return _public_view(user["sub"], rec)


@router.get("/api/users")
async def list_users(user=Depends(verify_token)):
    _require_admin(user)
    users = load_users()
    return {
        "users": [_public_view(name, rec) for name, rec in sorted(users.items())],
        "count": len(users),
    }


@router.post("/api/users")
async def create_user(body: dict, user=Depends(verify_token)):
    _require_admin(user)
    username = _validate_username(str(body.get("username", "")).strip())
    password = str(body.get("password", ""))
    role = str(body.get("role", "user"))

    if role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    users = load_users()
    if username in users:
        raise HTTPException(409, f"User '{username}' already exists")

    rec = {"hash": pwd_ctx.hash(password), "role": role}
    # New-account 2FA mandate: when the admin has enabled it, mark the user so
    # login forces enrollment (see auth_api login + the U3 UI).
    if fcfg.load().auth.require_totp_new_users:
        rec["totp_required"] = True
    users[username] = rec
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.create", "success", f"User '{username}' ({role})")
    return {"ok": True, "user": _public_view(username, users[username])}


@router.delete("/api/users/{username}")
async def delete_user(username: str, user=Depends(verify_token)):
    _require_admin(user)
    username = _validate_username(username)
    users = load_users()
    if username not in users:
        raise HTTPException(404, f"User '{username}' not found")

    # Guard: cannot delete yourself (losing your own session mid-operation).
    if username == user["sub"]:
        raise HTTPException(400, "You cannot delete your own account")

    # Guard: cannot delete the last admin (would lock everyone out).
    if users[username].get("role") == "admin" and _admin_count(users) <= 1:
        raise HTTPException(400, "Cannot delete the last admin")

    del users[username]
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.delete", "success", f"User '{username}' deleted")
    return {"ok": True}


@router.put("/api/users/{username}/role")
async def change_role(username: str, body: dict, user=Depends(verify_token)):
    _require_admin(user)
    username = _validate_username(username)
    new_role = str(body.get("role", ""))
    if new_role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")

    users = load_users()
    if username not in users:
        raise HTTPException(404, f"User '{username}' not found")

    # Guard: cannot demote the last admin.
    if (users[username].get("role") == "admin"
            and new_role != "admin"
            and _admin_count(users) <= 1):
        raise HTTPException(400, "Cannot demote the last admin")

    users[username]["role"] = new_role
    # Bump the token epoch: the user's existing token carries the OLD role in
    # its claim (verify_token reads role from the token, not the store). Without
    # this, a demoted admin keeps admin access until their token expires. The
    # bump forces them to re-authenticate and pick up the new role.
    users[username]["token_epoch"] = int(users[username].get("token_epoch", 0)) + 1
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.role", "success", f"User '{username}' -> {new_role}")
    return {"ok": True, "user": _public_view(username, users[username])}


@router.post("/api/users/{username}/password")
async def admin_reset_password(username: str, body: dict, user=Depends(verify_token)):
    """Admin-set a user's password WITHOUT knowing the current one.

    Distinct from /api/auth/change-password, which is self-service and
    requires the current password. This is the recovery path.
    """
    _require_admin(user)
    username = _validate_username(username)
    new_password = str(body.get("password", ""))
    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    users = load_users()
    if username not in users:
        raise HTTPException(404, f"User '{username}' not found")

    users[username]["hash"] = pwd_ctx.hash(new_password)
    # Bump the token epoch so the reset user's existing sessions are all
    # invalidated — this is the recovery path (often used precisely because
    # the account was compromised), so old tokens MUST die.
    users[username]["token_epoch"] = int(users[username].get("token_epoch", 0)) + 1
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.password.reset", "success", f"Password reset for '{username}'")
    return {"ok": True}


# ── 2FA / TOTP ────────────────────────────────────────────────────────────────
# Self-service enroll/verify/disable operate on the CALLER's own account
# (user["sub"]) — never an arbitrary username — so there is no IDOR surface.
# Admin reset (DELETE /api/users/{username}/totp) is the lost-device recovery
# path on a single-admin box. Login enforcement (mfa_pending challenge) is U2.

def _totp_secret_fields():
    return ("totp_secret", "totp_enabled", "totp_pending_secret",
            "backup_codes", "totp_last_timecode")


@router.post("/api/users/me/totp/enroll")
async def totp_enroll(user=Depends(verify_enroll_or_session)):
    """Begin 2FA enrollment: generate a PENDING secret (not yet active) and
    return the otpauth:// URI + secret. Verify-before-enable: nothing is
    enforced until POST /verify confirms the user's authenticator works."""
    me = user["sub"]
    users = load_users()
    rec = users.get(me)
    if rec is None:
        raise HTTPException(404, "User not found")
    if rec.get("totp_enabled"):
        raise HTTPException(409, "2FA is already enabled")
    secret = fa.generate_totp_secret()
    rec["totp_pending_secret"] = secret
    users[me] = rec
    save_users(users)
    uri = fa.totp_uri(secret, me)
    qr = None
    try:                          # same system qrencode the VPN page uses
        import base64
        import subprocess
        r = subprocess.run(["qrencode", "-t", "PNG", "-o", "-"], input=uri.encode(),
                           capture_output=True, timeout=10)
        if r.returncode == 0:
            qr = "data:image/png;base64," + base64.b64encode(r.stdout).decode()
    except (OSError, subprocess.SubprocessError):
        pass                      # secret + uri still work for manual entry
    return {"secret": secret, "uri": uri, "issuer": fa.TOTP_ISSUER, "qr": qr}


@router.post("/api/users/me/totp/verify")
async def totp_verify(body: dict, user=Depends(verify_enroll_or_session)):
    """Confirm enrollment: verify a code against the pending secret, then
    activate 2FA and return single-use backup codes (shown ONCE — they are
    bcrypt-hashed at rest and cannot be retrieved again)."""
    me = user["sub"]
    users = load_users()
    rec = users.get(me)
    if rec is None:
        raise HTTPException(404, "User not found")
    pending = rec.get("totp_pending_secret")
    if not pending:
        raise HTTPException(400, "No enrollment in progress — call enroll first")
    ok, tc = fa.verify_totp(pending, str(body.get("code", "")))
    if not ok:
        raise HTTPException(400, "Invalid code")
    display, hashed = fa.generate_backup_codes()
    rec["totp_secret"] = pending
    rec["totp_enabled"] = True
    rec["totp_last_timecode"] = tc
    rec["backup_codes"] = hashed
    rec.pop("totp_pending_secret", None)
    users[me] = rec
    save_users(users)
    assert _audit is not None
    _audit(me, "users.totp.enable", "success", "2FA enabled")
    return {"ok": True, "backup_codes": display}


@router.post("/api/users/me/totp/disable")
async def totp_disable(body: dict, user=Depends(verify_token)):
    """Disable own 2FA. Requires RE-AUTH with a current code OR password —
    OWASP: changing an MFA factor must re-verify identity, not trust the
    session (which could be hijacked)."""
    me = user["sub"]
    users = load_users()
    rec = users.get(me)
    if rec is None:
        raise HTTPException(404, "User not found")
    if not rec.get("totp_enabled"):
        raise HTTPException(400, "2FA is not enabled")
    reauthed = False
    code = str(body.get("code", ""))
    if code:
        reauthed, _ = fa.verify_totp(
            rec.get("totp_secret", ""), code, rec.get("totp_last_timecode", 0))
    if not reauthed:
        password = str(body.get("password", ""))
        if password:
            try:
                reauthed = pwd_ctx.verify(password, rec.get("hash", ""))
            except Exception:
                reauthed = False
    if not reauthed:
        raise HTTPException(401, "Re-authentication failed: current code or password required")
    for k in _totp_secret_fields():
        rec.pop(k, None)
    users[me] = rec
    save_users(users)
    assert _audit is not None
    _audit(me, "users.totp.disable", "success", "2FA disabled")
    return {"ok": True}


@router.post("/api/users/me/totp/backup-codes")
async def totp_regenerate_backup_codes(body: dict, user=Depends(verify_token)):
    """Regenerate backup codes (invalidates all old ones). Requires a current
    code as re-auth. Returns the new codes ONCE."""
    me = user["sub"]
    users = load_users()
    rec = users.get(me)
    if rec is None or not rec.get("totp_enabled"):
        raise HTTPException(400, "2FA is not enabled")
    ok, tc = fa.verify_totp(
        rec.get("totp_secret", ""), str(body.get("code", "")),
        rec.get("totp_last_timecode", 0))
    if not ok:
        raise HTTPException(400, "Invalid code")
    display, hashed = fa.generate_backup_codes()
    rec["backup_codes"] = hashed
    rec["totp_last_timecode"] = tc
    users[me] = rec
    save_users(users)
    assert _audit is not None
    _audit(me, "users.totp.backup_codes", "success", "Backup codes regenerated")
    return {"ok": True, "backup_codes": display}


@router.delete("/api/users/{username}/totp")
async def admin_reset_totp(username: str, user=Depends(verify_token)):
    """Admin recovery: clear a user's 2FA so they can re-enroll (e.g. lost
    device). Admin-only, audited. Does NOT touch the password."""
    _require_admin(user)
    username = _validate_username(username)
    users = load_users()
    if username not in users:
        raise HTTPException(404, f"User '{username}' not found")
    rec = users[username]
    had = bool(rec.get("totp_enabled"))
    for k in _totp_secret_fields():
        rec.pop(k, None)
    users[username] = rec
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.totp.admin_reset", "success",
           f"2FA reset for '{username}' (was {'enabled' if had else 'disabled'})")
    return {"ok": True}


# ── Auth policy (admin) ───────────────────────────────────────────────────────
# Persisted in the config-DB (forgeos_config). Currently a single switch:
# require new accounts to set up 2FA.

@router.get("/api/auth/policy")
async def get_auth_policy(user=Depends(verify_token)):
    """Read the auth policy. Admin-only (it governs account security)."""
    _require_admin(user)
    cfg = fcfg.load()
    return {"require_totp_new_users": cfg.auth.require_totp_new_users}


@router.put("/api/auth/policy")
async def set_auth_policy(body: dict, user=Depends(verify_token)):
    """Update the auth policy (admin). Only affects accounts created AFTER the
    change — existing users are untouched."""
    _require_admin(user)
    if "require_totp_new_users" not in body:
        raise HTTPException(400, "require_totp_new_users (bool) is required")
    cfg = fcfg.load()
    cfg.auth.require_totp_new_users = bool(body.get("require_totp_new_users"))
    fcfg.save(cfg)
    assert _audit is not None
    _audit(user["sub"], "auth.policy.update", "success",
           f"require_totp_new_users={cfg.auth.require_totp_new_users}")
    return {"ok": True, "require_totp_new_users": cfg.auth.require_totp_new_users}
