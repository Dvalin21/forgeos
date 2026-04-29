"""
ForgeOS OAuth2/OIDC Authentication Module
Supports Google, GitHub, and generic OIDC providers.

Dependencies:
  - authlib: OAuth2/OIDC client library
  - httpx: For OAuth token requests
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlencode, parse_qs


# ── Configuration ──
USERS_FILE = Path("/etc/forgeos/api-users.json")
OAUTH_CONFIG_FILE = Path("/etc/forgeos/oauth-providers.json")


# ── Provider Configurations ──
PROVIDERS = {
    "google": {
        "name": "Google",
        "client_id_env": "FORGEOS_GOOGLE_CLIENT_ID",
        "client_secret_env": "FORGEOS_GOOGLE_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "name": "GitHub",
        "client_id_env": "FORGEOS_GITHUB_CLIENT_ID",
        "client_secret_env": "FORGEOS_GITHUB_CLIENT_SECRET",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "user:email",
    }
}


# ── Helpers ──
def _load_users() -> dict:
    """Load users from JSON file."""
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}


def _save_users(users: dict) -> None:
    """Save users to JSON file."""
    USERS_FILE.write_text(json.dumps(users, indent=2))


def _load_oauth_config() -> dict:
    """Load OAuth provider configurations."""
    if OAUTH_CONFIG_FILE.exists():
        return json.loads(OAUTH_CONFIG_FILE.read_text())
    return {
        "registered_providers": {},
        "user_links": {},
    }


def _save_oauth_config(config: dict) -> None:
    """Save OAuth configuration."""
    OAUTH_CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_provider(name: str) -> Optional[dict]:
    """Get provider config by name."""
    return PROVIDERS.get(name.lower())


def list_providers() -> List[str]:
    """List available provider names."""
    return list(PROVIDERS.keys())


def generate_auth_url(provider_name: str, redirect_uri: str) -> Tuple[str, str]:
    """
    Generate OAuth2 authorization URL.
    
    Returns: (auth_url, state)
    """
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_name}")
    
    # Get credentials from environment
    client_id = os.environ.get(provider["client_id_env"], "")
    if not client_id:
        raise ValueError(f"Missing {provider['client_id_env']} environment variable")
    
    # Generate state for CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)
    
    # Build authorization URL
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider["scope"],
        "state": state,
    }
    
    auth_url = f"{provider['authorize_url']}?{urlencode(params)}"
    return auth_url, state


def handle_oauth_callback(
    provider_name: str,
    code: str,
    redirect_uri: str,
    state: str,
    stored_state: str,
) -> dict:
    """
    Handle OAuth2 callback and return user info.
    
    Returns: {"sub": ..., "email": ..., "name": ...}
    """
    # Verify state (CSRF protection)
    if state != stored_state:
        raise ValueError("Invalid state parameter - possible CSRF attack")
    
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_name}")
    
    # Get credentials
    client_id = os.environ.get(provider["client_id_env"], "")
    client_secret = os.environ.get(provider["client_secret_env"], "")
    
    if not client_id or not client_secret:
        raise ValueError("Missing OAuth credentials")
    
    # Exchange code for token
    import httpx
    
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    resp = httpx.post(provider["token_url"], data=token_data)
    if resp.status_code != 200:
        raise ValueError(f"Token exchange failed: {resp.text}")
    
    token_info = dict(parse_qs(resp.text)) if "access_token" not in resp.json() else resp.json()
    access_token = token_info.get("access_token")
    
    if not access_token:
        raise ValueError("No access token received")
    
    # Get user info
    headers = {"Authorization": f"Bearer {access_token}"}
    user_resp = httpx.get(provider["userinfo_url"], headers=headers)
    if user_resp.status_code != 200:
        raise ValueError(f"Failed to get user info: {user_resp.text}")
    
    user_info = user_resp.json()
    
    # Normalize user info (different providers have different fields)
    if provider_name == "github":
        return {
            "sub": str(user_info.get("id")),
            "email": user_info.get("email"),
            "name": user_info.get("login"),
            "avatar": user_info.get("avatar_url"),
        }
    else:  # Google or generic OIDC
        return {
            "sub": user_info.get("sub"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "avatar": user_info.get("picture"),
        }


def link_oauth_to_user(username: str, provider_name: str, user_info: dict) -> None:
    """Link an OAuth provider to an existing user."""
    users = _load_users()
    if username not in users:
        raise ValueError(f"User {username} not found")
    
    # Update user with OAuth info
    if "oauth_providers" not in users[username]:
        users[username]["oauth_providers"] = {}
    
    users[username]["oauth_providers"][provider_name] = {
        "sub": user_info["sub"],
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "linked_at": __import__("time").time(),
    }
    
    _save_users(users)


def unlink_oauth_from_user(username: str, provider_name: str) -> None:
    """Unlink an OAuth provider from a user."""
    users = _load_users()
    if username not in users:
        raise ValueError(f"User {username} not found")
    
    if "oauth_providers" in users[username]:
        users[username]["oauth_providers"].pop(provider_name, None)
        _save_users(users)
        return
    
    raise ValueError(f"No OAuth providers linked to {username}")


def get_linked_providers(username: str) -> list:
    """Get list of OAuth providers linked to user."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return []
    
    return list(user.get("oauth_providers", {}).keys())


def find_user_by_oauth(provider_name: str, sub: str) -> Optional[str]:
    """Find username by OAuth provider and subject ID."""
    users = _load_users()
    for username, info in users.items():
        providers = info.get("oauth_providers", {})
        if provider_name in providers and providers[provider_name].get("sub") == sub:
            return username
    return None
