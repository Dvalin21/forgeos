"""ForgeOS — Authentication API surface.

Mounts under the existing FastAPI app via:

    from auth_api import router as auth_router, set_helpers as set_auth_helpers
    set_auth_helpers(audit=_audit, check_rate_limit=_check_login_rate_limit)
    app.include_router(auth_router)

Routes:
  • POST /api/auth/login           — username/password → JWT cookie + body token
  • POST /api/auth/logout          — clear cookie
  • POST /api/auth/change-password — change own password (requires current)

Helpers injected by the main module (forgeos-api.py) at startup, because they
own shared state (_login_attempts dict for rate limit, audit log writer).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from forgeos_auth import (
    JWT_EXPIRE,
    LoginRequest,
    create_mfa_token,
    create_token,
    decode_mfa_token,
    load_users,
    pwd_ctx,
    save_users,
    verify_token,
)
import forgeos_auth as fa

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_audit: Optional[Callable[..., None]] = None
_check_login_rate_limit: Optional[Callable[[str], None]] = None


def set_helpers(
    audit: Callable[..., None],
    check_rate_limit: Callable[[str], None],
) -> None:
    """Wire shared helpers from the main module.

    Called once at app startup before include_router(). Splitting these out
    avoids a circular import between this module and forgeos-api.py.
    """
    global _audit, _check_login_rate_limit
    _audit = audit
    _check_login_rate_limit = check_rate_limit


@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    if _check_login_rate_limit is None:
        # Programmer error — main module forgot to call set_helpers().
        raise HTTPException(status_code=500, detail="Auth helpers not initialized")
    _check_login_rate_limit(request.client.host)
    users = load_users()
    if not users:
        raise HTTPException(
            status_code=503,
            detail="No users configured. Run forgeos-install to set up admin user.",
        )
    user = users.get(body.username)
    if not user or not pwd_ctx.verify(body.password, user["hash"]):
        logger.warning("FAILED LOGIN user=%s from=%s", body.username, request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Step-2 gate: with 2FA enabled, the password alone earns only a short-lived
    # mfa_pending token — never a session token. The caller must complete
    # POST /api/auth/login/totp to get the real cookie.
    if user.get("totp_enabled"):
        if _audit is not None:
            _audit(body.username, "auth.login.mfa_challenge", "pending",
                   "Password accepted; awaiting 2FA code")
        return JSONResponse({"mfa_required": True,
                             "mfa_token": create_mfa_token(body.username)})
    token = create_token(body.username, user["role"])
    resp = JSONResponse({"token": token, "username": body.username, "role": user["role"]})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(
        "forgeos_token",
        token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=JWT_EXPIRE * 3600,
    )
    return resp


class TotpLoginRequest(BaseModel):
    mfa_token: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1, max_length=32)


@router.post("/api/auth/login/totp")
async def login_totp(body: TotpLoginRequest, request: Request):
    """Step 2 of 2FA login: exchange a valid mfa_pending token + a TOTP code
    (or a single-use backup code) for a real session token + cookie."""
    if _check_login_rate_limit is None:
        raise HTTPException(status_code=500, detail="Auth helpers not initialized")
    _check_login_rate_limit(request.client.host)
    username = decode_mfa_token(body.mfa_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA session")
    users = load_users()
    user = users.get(username)
    if not user or not user.get("totp_enabled"):
        # 2FA was disabled/removed between step 1 and step 2.
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA session")

    code = (body.code or "").strip()
    accepted = False
    # 1) TOTP code, enforcing the anti-replay watermark.
    ok, tc = fa.verify_totp(user.get("totp_secret", ""), code,
                            user.get("totp_last_timecode", 0))
    if ok:
        user["totp_last_timecode"] = tc
        accepted = True
    else:
        # 2) single-use backup code (a 6-digit TOTP can't collide — lengths differ).
        used, remaining = fa.consume_backup_code(code, user.get("backup_codes", []))
        if used:
            user["backup_codes"] = remaining
            accepted = True
    if not accepted:
        logger.warning("FAILED 2FA user=%s from=%s", username, request.client.host)
        raise HTTPException(status_code=401, detail="Invalid code")

    users[username] = user
    save_users(users)
    token = create_token(username, user["role"])
    resp = JSONResponse({"token": token, "username": username, "role": user["role"]})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(
        "forgeos_token", token, httponly=True, secure=secure,
        samesite="strict", max_age=JWT_EXPIRE * 3600,
    )
    if _audit is not None:
        _audit(username, "auth.login.totp", "success", "2FA login")
    return resp


@router.post("/api/auth/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("forgeos_token")
    return resp


@router.post("/api/auth/change-password")
async def change_password(body: dict, user=Depends(verify_token)):
    users = load_users()
    u = users.get(user["sub"])
    if not u or not pwd_ctx.verify(body.get("current", ""), u["hash"]):
        raise HTTPException(status_code=401, detail="Current password incorrect")
    users[user["sub"]]["hash"] = pwd_ctx.hash(body["new"])
    save_users(users)
    if _audit is not None:
        _audit(user["sub"], "auth.password.change", "success", "Password changed")
    return {"ok": True}
