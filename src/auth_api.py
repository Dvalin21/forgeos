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

from forgeos_auth import (
    JWT_EXPIRE,
    LoginRequest,
    create_token,
    hash_password,
    load_users,
    save_users,
    verify_password,
    verify_token,
)

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
    if not user or not verify_password(body.password, user["hash"]):
        logger.warning("FAILED LOGIN user=%s from=%s", body.username, request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")
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


@router.post("/api/auth/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("forgeos_token")
    return resp


@router.post("/api/auth/change-password")
async def change_password(body: dict, user=Depends(verify_token)):
    users = load_users()
    u = users.get(user["sub"])
    if not u or not verify_password(body.get("current", ""), u["hash"]):
        raise HTTPException(status_code=401, detail="Current password incorrect")
    users[user["sub"]]["hash"] = hash_password(body["new"])
    save_users(users)
    if _audit is not None:
        _audit(user["sub"], "auth.password.change", "success", "Password changed")
    return {"ok": True}
