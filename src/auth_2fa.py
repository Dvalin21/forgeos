"""
ForgeOS 2FA (Two-Factor Authentication) Module
Provides TOTP-based 2FA with QR code setup and backup codes.

Dependencies:
  - pyotp: TOTP generation/verification
  - qrcode: QR code generation for authenticator apps
  - secrets: Cryptographically secure random generation
"""

import json
import secrets
from pathlib import Path
from typing import Optional, List, Dict

import pyotp
import qrcode
from io import BytesIO
from pydantic import BaseModel


# ── Configuration ──
USERS_FILE = Path("/etc/forgeos/api-users.json")
BACKUP_CODE_COUNT = 8
TOTP_ISSUER = "ForgeOS"
TOTP_VALID_WINDOW = 1  # ±1 time window (30s each)


# ── Models ──
class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_code_base64: str


class TOTPVerifyRequest(BaseModel):
    code: str


class BackupCodesResponse(BaseModel):
    backup_codes: List[str]


# ── Helpers ──
def _load_users() -> dict:
    """Load users from JSON file."""
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}


def _save_users(users: dict) -> None:
    """Save users to JSON file."""
    USERS_FILE.write_text(json.dumps(users, indent=2))


def get_user_totp_secret(username: str) -> Optional[str]:
    """Get TOTP secret for user (None if not set)."""
    users = _load_users()
    return users.get(username, {}).get("totp_secret")


def is_totp_enabled(username: str) -> bool:
    """Check if 2FA is enabled for user."""
    users = _load_users()
    return users.get(username, {}).get("totp_enabled", False)


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32)."""
    return pyotp.random_base32()


def generate_provisioning_uri(username: str, secret: str) -> str:
    """Generate the provisioning URI for authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=TOTP_ISSUER,
    )


def generate_qr_code_base64(uri: str) -> str:
    """Generate QR code as base64-encoded PNG."""
    import base64
    img = qrcode.make(uri)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a TOTP code against the secret."""
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=TOTP_VALID_WINDOW)


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> List[str]:
    """Generate cryptographically secure backup codes."""
    codes = []
    for _ in range(count):
        # Format: XXXX-XXXX-XXXX (alphanumeric, no confusing chars)
        code = ''.join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
        codes.append('-'.join([code[i:i+4] for i in range(0, 12, 4)]))
    return codes


def verify_backup_code(username: str, code: str) -> bool:
    """Verify and consume a backup code."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return False
    
    backup_codes = user.get("backup_codes", [])
    normalized_input = code.strip().upper()
    
    if normalized_input in backup_codes:
        # Remove used backup code
        backup_codes.remove(normalized_input)
        user["backup_codes"] = backup_codes
        users[username] = user
        _save_users(users)
        return True
    return False


def enable_totp_for_user(username: str, secret: str) -> TOTPSetupResponse:
    """Enable 2FA for user and return setup data."""
    users = _load_users()
    
    if username not in users:
        raise ValueError(f"User {username} not found")
    
    # Generate backup codes
    backup_codes = generate_backup_codes()
    
    # Update user
    users[username]["totp_secret"] = secret
    users[username]["totp_enabled"] = True
    users[username]["backup_codes"] = backup_codes
    _save_users(users)
    
    # Generate QR code data
    uri = generate_provisioning_uri(username, secret)
    qr_base64 = generate_qr_code_base64(uri)
    
    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=uri,
        qr_code_base64=qr_base64,
    )


def disable_totp_for_user(username: str) -> None:
    """Disable 2FA for user."""
    users = _load_users()
    
    if username not in users:
        raise ValueError(f"User {username} not found")
    
    users[username]["totp_secret"] = None
    users[username]["totp_enabled"] = False
    users[username]["backup_codes"] = []
    _save_users(users)


def get_backup_codes(username: str) -> List[str]:
    """Get backup codes for user."""
    users = _load_users()
    return users.get(username, {}).get("backup_codes", [])


def regenerate_backup_codes(username: str) -> List[str]:
    """Regenerate backup codes for user."""
    users = _load_users()
    
    if username not in users:
        raise ValueError(f"User {username} not found")
    
    backup_codes = generate_backup_codes()
    users[username]["backup_codes"] = backup_codes
    _save_users(users)
    return backup_codes
