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

# Known placeholder values that are NOT acceptable as a real JWT secret.
# These get planted by install templates or admin-by-mistake — the auth
# layer must refuse to start with any of them.
_JWT_PLACEHOLDERS = frozenset({
    "",
    "changeme",
    "changeme-set-in-forgeos.conf",
})


class JwtSecretMissingError(RuntimeError):
    """Raised at import time if no valid JWT secret is configured.

    The API process exits with this when:
      - FORGEOS_JWT_SECRET env var is unset AND
      - /etc/forgeos/forgeos.conf is missing or has no WEBUI_JWT_SECRET line
        (or the value matches a known placeholder)

    Fix: run `bash install/modules/99-finalize.sh` to generate a secret,
    or set WEBUI_JWT_SECRET="<48-random-bytes-base64>" in the config file.
    """


def _load_jwt_secret() -> str:
    """Load the JWT signing secret from env or config file.

    Refuses to generate one at runtime — that path was race-prone (two
    parallel workers could each generate a different secret, last writer
    wins, all tokens from the loser become invalid).

    The installer (`install/modules/99-finalize.sh`) is now solely
    responsible for generating and persisting the secret. If this
    function cannot find a valid one, the API process must not start.
    """
    # Priority 1: explicit env var (used by the systemd unit)
    env_secret = os.environ.get("FORGEOS_JWT_SECRET", "").strip()
    if env_secret and env_secret not in _JWT_PLACEHOLDERS:
        return env_secret

    # Priority 2: WEBUI_JWT_SECRET line in the config file
    if CONFIG_FILE.exists():
        try:
            for line in CONFIG_FILE.read_text().splitlines():
                if line.startswith("WEBUI_JWT_SECRET="):
                    candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if candidate and candidate not in _JWT_PLACEHOLDERS:
                        return candidate
        except OSError as e:
            logger.warning("Failed to read %s: %s", CONFIG_FILE, e)

    # No valid secret found — refuse to start.
    msg = (
        "ForgeOS API refuses to start: no valid JWT signing secret is configured.\n"
        "\n"
        "  Tried (in order):\n"
        "    1. FORGEOS_JWT_SECRET environment variable — unset or placeholder\n"
        f"    2. WEBUI_JWT_SECRET in {CONFIG_FILE} — missing or placeholder\n"
        "\n"
        "  Fix:  run the installer's finalize module which generates one idempotently:\n"
        "          sudo bash install/modules/99-finalize.sh\n"
        "        or set it manually:\n"
        '          echo \'WEBUI_JWT_SECRET="\'"$(openssl rand -base64 48 | tr -d \'\\n/\')\'"\' \\\n'
        f"              | sudo tee -a {CONFIG_FILE}\n"
    )
    raise JwtSecretMissingError(msg)


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
