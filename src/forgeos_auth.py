"""
ForgeOS Auth — shared JWT auth for API routers and WebSockets.
"""
from __future__ import annotations

import re

import json
import logging
import os
import secrets
import sys
import tempfile
import time

logger = logging.getLogger("forgeos-auth")
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, Field
import pyotp

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

    Fix: the v2 installer writes the secret to /etc/forgeos/api.env at
    install; set WEBUI_JWT_SECRET or FORGEOS_JWT_SECRET manually otherwise.
    """


def _load_jwt_secret() -> str:
    """Load the JWT signing secret from env or config file.

    Refuses to generate one at runtime — that path was race-prone (two
    parallel workers could each generate a different secret, last writer
    wins, all tokens from the loser become invalid).

    The installer is solely responsible for generating and persisting the
    secret (v2: phase_keystores -> /etc/forgeos/api.env). If this function
    cannot find a valid one, the API process must not start.
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
        "  Fix:  re-run the v2 installer (writes /etc/forgeos/api.env), or set it manually:\n"
        '          echo \'WEBUI_JWT_SECRET="\'"$(openssl rand -base64 48 | tr -d \'\\n/\')\'"\' \\\n'
        f"              | sudo tee -a {CONFIG_FILE}\n"
    )
    raise JwtSecretMissingError(msg)


JWT_SECRET  = _load_jwt_secret()
JWT_ALGO    = "HS256"
JWT_EXPIRE  = 12  # hours

# A login that passes the password step but still owes a TOTP code gets a
# SHORT-LIVED token scoped MFA_PENDING_SCOPE. It is NOT a session token:
# verify_token / verify_ws_token refuse it everywhere except /login/totp.
# This is what closes the OWASP "force-browse past step 2" MFA bypass.
MFA_PENDING_SCOPE   = "mfa_pending"
JWT_EXPIRE_MFA_MIN  = 5   # minutes

# Token scoped MFA_ENROLL_SCOPE is issued when a user under the "require 2FA for
# new accounts" policy logs in but has not enrolled yet. Like mfa_pending it is
# NOT a session token: it reaches ONLY the TOTP enroll/verify endpoints (via
# verify_enroll_or_session), letting a forced-enrollment user set up 2FA — and
# nothing else — before they hold a session. This is what makes the policy
# bypass-proof: the token can't be force-browsed to any real endpoint.
MFA_ENROLL_SCOPE      = "mfa_enroll"
JWT_EXPIRE_ENROLL_MIN = 15  # minutes (enough to scan a QR + enter a code)

class _BcryptCtx:
    """Drop-in for the retired passlib CryptContext (passlib is unmaintained
    since 2020 and forced the bcrypt<4.1 pin). Same $2b$ hashes, same
    hash/verify interface, zero call-site churn. bcrypt's hard limit is 72
    bytes; truncate exactly as passlib did so existing long passwords keep
    verifying."""

    @staticmethod
    def hash(password: str) -> str:
        return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode()[:72], hashed.encode())
        except (ValueError, TypeError):
            return False               # malformed/foreign hash never verifies


pwd_ctx = _BcryptCtx()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}


def save_users(users: dict) -> None:
    """Persist the user store ATOMICALLY with restrictive permissions.

    api-users.json holds bcrypt password hashes (and, after Sprint 6,
    TOTP secrets + backup-code hashes) — it IS the auth system. A bare
    write_text() is unsafe on two counts:

      1. Non-atomic: a crash or concurrent write mid-stream truncates the
         file, locking every user out (the file that says who may log in
         is now empty/corrupt).
      2. Permissions: write_text() inherits the umask, which can leave a
         freshly-created file world-readable, exposing the hashes.

    Fix: write to a temp file in the same directory, fsync, chmod 600,
    then os.replace() — which is atomic on POSIX (same filesystem). A
    reader either sees the complete old file or the complete new one,
    never a half-written one.
    """
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".api-users.", suffix=".tmp", dir=str(USERS_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(users, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, USERS_FILE)
    except BaseException:
        # Clean up the temp file on any failure so we don't litter
        # .api-users.*.tmp files in /etc/forgeos.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def create_token(username: str, role: str, epoch: int = 0) -> str:
    """Issue a full session token.

    `epoch` is the user's current token_epoch — a monotonic counter bumped
    whenever their credentials change (e.g. password change). verify_token
    rejects a token whose epoch is older than the user's current one, which
    is how a stateless JWT gets revoked: bump the epoch and every prior token
    is instantly invalid. Default 0 keeps tokens issued before this existed
    (and users with no token_epoch yet) valid — no forced logout on deploy.
    """
    payload = {
        "sub": username,
        "role": role,
        "epoch": epoch,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def create_mfa_token(username: str) -> str:
    """Short-lived token proving the password step passed, pending TOTP.

    Scoped MFA_PENDING_SCOPE so it is accepted ONLY by /api/auth/login/totp;
    every other endpoint rejects it (see verify_token). Carries no role, so
    even if the scope check were bypassed it grants nothing.
    """
    payload = {
        "sub": username,
        "scope": MFA_PENDING_SCOPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MFA_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_mfa_token(token: str) -> str | None:
    """Return the username from a valid mfa_pending token, else None.

    None on: empty, malformed, expired, or wrong scope (e.g. a full session
    token may not be replayed here as a second factor)."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None
    if payload.get("scope") != MFA_PENDING_SCOPE:
        return None
    return payload.get("sub")


def create_enroll_token(username: str) -> str:
    """Restricted token for a forced-enrollment user. Scoped MFA_ENROLL_SCOPE so
    it is accepted ONLY by the TOTP enroll/verify endpoints — never a real
    endpoint. Carries no role."""
    payload = {
        "sub": username,
        "scope": MFA_ENROLL_SCOPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_ENROLL_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ── fail2ban feed ─────────────────────────────────────────────────────────────
# Auth failures also go to a FILE (the audit trail is SQLite, which fail2ban
# cannot read). Fixed grammar — the fail2ban filter regex depends on it:
#   <ts> forgeos-auth FAILED <WHAT> user=<u> ip=<ip>
AUTH_LOG = Path("/var/log/forgeos/auth.log")
_auth_logger = None


def log_auth_failure(what: str, username: str, ip: str) -> None:
    """Append one jailable line. Never raises — a logging failure must not
    break login itself."""
    global _auth_logger
    try:
        if _auth_logger is None:
            import logging
            from logging.handlers import RotatingFileHandler
            AUTH_LOG.parent.mkdir(parents=True, exist_ok=True)
            lg = logging.getLogger("forgeos.authlog")
            lg.setLevel(logging.INFO)
            lg.propagate = False
            h = RotatingFileHandler(str(AUTH_LOG), maxBytes=5_000_000, backupCount=3)
            h.setFormatter(logging.Formatter("%(asctime)s forgeos-auth %(message)s"))
            lg.addHandler(h)
            _auth_logger = lg
        # sanitize: usernames are attacker-controlled; keep the line unspoofable
        u = re.sub(r"[^\w.@-]", "_", str(username))[:64] or "_"
        _auth_logger.info("FAILED %s user=%s ip=%s", what, u, ip)
    except Exception:
        pass


def _extract_token(request: Request) -> str:
    """Pull the JWT from the Authorization header, falling back to the cookie."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        token = request.cookies.get("forgeos_token", "")
    return token


def _epoch_current(username: str) -> int:
    """The user's current token_epoch (0 if unset or user is gone). Read fresh
    so an epoch bump takes effect immediately on the next request."""
    try:
        return int(load_users().get(username, {}).get("token_epoch", 0))
    except (OSError, ValueError, TypeError):
        # If the store can't be read, fall back to 0 so a transient read error
        # doesn't lock everyone out. The token still had to be validly signed.
        return 0


def verify_token(request: Request) -> dict:
    """FastAPI dependency — full session tokens only. Rejects the restricted
    mfa_pending / mfa_enroll scopes, so a half-authenticated token can never
    reach a real endpoint (the MFA bypass guard). Also enforces token_epoch:
    a token whose epoch is older than the user's current one is rejected —
    this is what invalidates every prior session when the password changes."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("scope") in (MFA_PENDING_SCOPE, MFA_ENROLL_SCOPE):
        # A half-authenticated token (pre-2FA, or pre-enrollment) must never
        # reach a real endpoint.
        raise HTTPException(status_code=401, detail="Two-factor authentication required")
    # Stateless revocation: a token minted before the user's current epoch
    # (e.g. before their last password change) is dead. Token epoch defaults
    # to 0 for pre-existing tokens; user epoch defaults to 0 when unset — so
    # untouched accounts keep working (no forced logout on deploy).
    if int(payload.get("epoch", 0)) < _epoch_current(payload.get("sub", "")):
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")
    return payload


def verify_enroll_or_session(request: Request) -> dict:
    """Dependency for the TOTP enroll/verify endpoints ONLY. Accepts a full
    session token OR an mfa_enroll-scoped token — a forced-enrollment user holds
    only the latter until 2FA is set up. mfa_pending and anything else are
    rejected."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("scope") not in (None, MFA_ENROLL_SCOPE):
        raise HTTPException(status_code=401, detail="Not authorized for enrollment")
    return payload


def verify_ws_token(ws: WebSocket) -> dict | None:
    """Validate JWT from WebSocket query param 'token'.
    
    Returns decoded payload on success, None on failure.
    Caller should close the WebSocket if None is returned.
    """
    token = ws.query_params.get("token", "")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None
    if payload.get("scope") in (MFA_PENDING_SCOPE, MFA_ENROLL_SCOPE):
        return None
    return payload


# ── TOTP / 2FA (shared by users_api enroll/verify and auth_api login) ─────────
#
# Design follows OWASP MFA guidance + PyPI warehouse/utils/otp.py:
#   • secret: pyotp.random_base32() (160-bit), stored in the 0600 user store.
#   • verify: ±1 time-step window (clock skew; VMs drift) AND anti-replay —
#     a code's time-step must be strictly greater than the last accepted one,
#     so a code cannot be reused inside its ~90s validity window.
#   • backup codes: random, single-use, bcrypt-hashed at rest, shown once.

TOTP_ISSUER = "ForgeOS"
TOTP_PERIOD = 30
TOTP_WINDOW = 1                       # ± steps tolerated (±30s)
BACKUP_CODE_COUNT = 10
# unambiguous alphabet (no 0/O/1/l/I) for backup codes
_BACKUP_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def generate_totp_secret() -> str:
    """A fresh base32 TOTP secret (Google Authenticator / Authy compatible)."""
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str = TOTP_ISSUER) -> str:
    """otpauth:// provisioning URI for QR / manual entry. Built fresh each call
    (PyOTP issue #115: provisioning_uri can misbehave after verify())."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str, last_timecode: int = 0,
                window: int = TOTP_WINDOW) -> tuple[bool, int | None]:
    """Verify a 6-digit TOTP code with ±window clock-skew tolerance and replay
    protection.

    Returns (ok, timecode). On success, persist `timecode` as the user's
    totp_last_timecode; a later code whose step is <= that is rejected as a
    replay (covers reuse within the ±window validity span).
    """
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 6) or not secret:
        return False, None
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in range(-window, window + 1):
        tc = now // TOTP_PERIOD + offset
        if pyotp.utils.strings_equal(code, totp.generate_otp(tc)):
            if tc <= last_timecode:
                return False, None        # replay within the window
            return True, tc
    return False, None


def generate_backup_codes(n: int = BACKUP_CODE_COUNT) -> tuple[list[str], list[str]]:
    """Return (display_codes, hashed_codes). Display codes are shown to the user
    ONCE (format ``xxxxx-xxxxx``); hashed codes (bcrypt of the normalized
    10-char form) are what gets stored. Single-use is enforced on consume."""
    display, hashed = [], []
    for _ in range(n):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(10))
        display.append(f"{raw[:5]}-{raw[5:]}")
        hashed.append(pwd_ctx.hash(raw))
    return display, hashed


def _normalize_backup_code(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def consume_backup_code(code: str, hashed: list[str]) -> tuple[bool, list[str]]:
    """If `code` matches an unused hashed backup code, return (True, remaining)
    with that code removed (single-use). Otherwise (False, unchanged)."""
    norm = _normalize_backup_code(code)
    if len(norm) != 10:
        return False, hashed
    for i, h in enumerate(hashed):
        try:
            if pwd_ctx.verify(norm, h):
                return True, hashed[:i] + hashed[i + 1:]
        except Exception:
            continue
    return False, hashed
