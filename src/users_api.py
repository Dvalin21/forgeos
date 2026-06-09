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

from forgeos_auth import load_users, save_users, pwd_ctx, verify_token

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
    }


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

    users[username] = {"hash": pwd_ctx.hash(password), "role": role}
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
    save_users(users)
    assert _audit is not None
    _audit(user["sub"], "users.password.reset", "success", f"Password reset for '{username}'")
    return {"ok": True}
