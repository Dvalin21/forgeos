"""
ForgeOS API Keys Management Module
Provides API key creation, verification, and rate limiting.

Storage: /etc/forgeos/api-keys.json
Features:
  - Create API keys with permissions
  - Rate limiting per key
  - Automatic expiration
  - Usage tracking
"""

import json
import secrets
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict


# ── Configuration ──
API_KEYS_FILE = Path("/etc/forgeos/api-keys.json")
KEY_PREFIX = "forgeos_"
KEY_LENGTH = 32
DEFAULT_RATE_LIMIT = 1000  # requests per hour (increased for API keys)


# ── Models ──
class APIKeyCreate:
    name: str
    permissions: List[str] = ["read"]
    rate_limit: int = DEFAULT_RATE_LIMIT
    expires_days: int = 365


class APIKey:
    id: str
    user: str
    name: str
    key_hash: str
    permissions: List[str]
    rate_limit: int
    created: float
    last_used: Optional[float] = None
    expires: Optional[float] = None
    active: bool = True


# ── Helpers ──
def _load_keys() -> Dict[str, dict]:
    """Load API keys from JSON file."""
    if API_KEYS_FILE.exists():
        return json.loads(API_KEYS_FILE.read_text())
    return {}


def _save_keys(keys: dict) -> None:
    """Save API keys to JSON file."""
    API_KEYS_FILE.write_text(json.dumps(keys, indent=2))


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.
    Returns: (full_key, key_id)
    """
    # Generate random key
    raw_key = secrets.token_hex(KEY_LENGTH)
    full_key = KEY_PREFIX + raw_key
    
    # Create key ID (first 12 chars after prefix)
    key_id = full_key[:len(KEY_PREFIX) + 12]
    
    return full_key, key_id


def hash_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_api_key(key: str) -> Optional[dict]:
    """
    Verify an API key and return key info if valid.
    Returns: key_info dict or None if invalid.
    """
    keys = _load_keys()
    key_hash = hash_key(key)
    
    # Find key by hash
    for key_id, key_info in keys.items():
        if key_info.get("key_hash") == key_hash:
            # Check if active
            if not key_info.get("active", True):
                return None
            
            # Check expiration
            if key_info.get("expires"):
                if time.time() > key_info["expires"]:
                    return None
            
            # Update last_used
            key_info["last_used"] = time.time()
            keys[key_id] = key_info
            _save_keys(keys)
            
            return key_info
    
    return None


def create_api_key(username: str, params: APIKeyCreate) -> tuple[str, dict]:
    """
    Create a new API key for a user.
    Returns: (full_key, key_info)
    """
    keys = _load_keys()
    
    # Generate key
    full_key, key_id = generate_api_key()
    
    # Calculate expiration
    expires = None
    if params.expires_days > 0:
        expires = time.time() + (params.expires_days * 86400)
    
    # Create key info
    key_info = {
        "id": key_id,
        "user": username,
        "name": params.name,
        "key_hash": hash_key(full_key),
        "permissions": params.permissions,
        "rate_limit": params.rate_limit,
        "created": time.time(),
        "last_used": None,
        "expires": expires,
        "active": True,
    }
    
    keys[key_id] = key_info
    _save_keys(keys)
    
    return full_key, key_info


def list_api_keys(username: str) -> List[dict]:
    """List API keys for a user."""
    keys = _load_keys()
    return [
        {k: v for k, v in info.items() if k != "key_hash"}
        for key_id, info in keys.items()
        if info.get("user") == username
    ]


def revoke_api_key(key_id: str, username: str) -> bool:
    """Revoke an API key (must be owned by user)."""
    keys = _load_keys()
    
    key_info = keys.get(key_id)
    if not key_info:
        return False
    
    # Check ownership
    if key_info.get("user") != username:
        return False
    
    # Revoke
    key_info["active"] = False
    keys[key_id] = key_info
    _save_keys(keys)
    return True


def get_usage_stats(key_id: str, username: str) -> Optional[dict]:
    """Get usage statistics for an API key."""
    keys = _load_keys()
    key_info = keys.get(key_id)
    
    if not key_info or key_info.get("user") != username:
        return None
    
    return {
        "id": key_id,
        "name": key_info.get("name"),
        "created": key_info.get("created"),
        "last_used": key_info.get("last_used"),
        "expires": key_info.get("expires"),
        "permissions": key_info.get("permissions"),
        "rate_limit": key_info.get("rate_limit"),
    }
