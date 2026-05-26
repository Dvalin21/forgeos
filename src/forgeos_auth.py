"""
ForgeOS Auth — shared JWT auth for API routers and WebSockets.
"""
from __future__ import annotations

import json
import logging
import os
import sys

logger = logging.getLogger("forgeos-auth")
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

# ── Config ──
CONFIG_FILE = Path("/etc/forgeos/forgeos.conf")
USERS_FILE  = Path("/etc/forgeos/api-users.json")


def _load_jwt_secret() -> str:
    secret = os.environ.get("FORGEOS_JWT_SECRET", "")
    if not secret:
        try:
            for line in CONFIG_FILE.read_text().splitlines():
                if line.startswith("WEBUI_JWT_SECRET="):
                    candidate = line.split("=", 1)[1].strip().strip('"')
                    if candidate not in ("changeme-set-in-forgeos.conf", "changeme", ""):
                        secret = candidate
        except Exception as e:
            logger.warning("FAILED to read %s: %s", CONFIG_FILE, e)
    if not secret or secret in ("changeme-set-in-forgeos.conf", "changeme", ""):
        import secrets
        secret = secrets.token_hex(32)
        try:
            lines = CONFIG_FILE.read_text().splitlines() if CONFIG_FILE.exists() else []
            lines = [l for l in lines if not l.startswith("WEBUI_JWT_SECRET=")]
            lines.append(f'WEBUI_JWT_SECRET="{secret}"')
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text("\n".join(lines) + "\n")
        except Exception as e:
            logger.warning("FAILED to persist JWT secret: %s", e)
    return secret


JWT_SECRET  = _load_jwt_secret()
JWT_ALGO    = "HS256"
JWT_EXPIRE  = 12  # hours

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}


def save_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2))


def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(request: Request) -> dict:
    """FastAPI dependency — extracts + validates JWT from header or cookie."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        token = request.cookies.get("forgeos_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def verify_ws_token(ws: WebSocket) -> dict | None:
    """Validate JWT from WebSocket query param 'token'.
    
    Returns decoded payload on success, None on failure.
    Caller should close the WebSocket if None is returned.
    """
    token = ws.query_params.get("token", "")
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None
