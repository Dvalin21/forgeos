"""
Tests for forgeos_auth.py — JWT creation, verification, user management.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jose import jwt as jose_jwt


class TestAuthToken:
    """JWT token creation and verification."""

    def test_create_token_returns_string(self):
        from forgeos_auth import create_token

        token = create_token("admin", "admin")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_create_token_contains_claims(self):
        from forgeos_auth import create_token, JWT_SECRET, JWT_ALGO

        token = create_token("bob", "user")
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        assert payload["sub"] == "bob"
        assert payload["role"] == "user"
        assert "exp" in payload

    def test_verify_token_valid(self, auth_headers):
        from forgeos_auth import verify_token

        # verify_token is a FastAPI dependency that extracts from Request
        # We test it indirectly via the API endpoints
        pass

    def test_decode_rejects_bad_secret(self):
        from forgeos_auth import create_token

        token = create_token("admin", "admin")
        with pytest.raises(Exception):
            jose_jwt.decode(token, "wrong-secret", algorithms=["HS256"])


class TestLoginRequest:
    """LoginRequest Pydantic model validation."""

    def test_valid_login(self):
        from forgeos_auth import LoginRequest

        r = LoginRequest(username="admin", password="secret123")
        assert r.username == "admin"
        assert r.password == "secret123"

    def test_empty_username_rejected(self):
        from forgeos_auth import LoginRequest

        with pytest.raises(Exception):
            LoginRequest(username="", password="secret")

    def test_empty_password_rejected(self):
        from forgeos_auth import LoginRequest

        with pytest.raises(Exception):
            LoginRequest(username="admin", password="")

    def test_username_max_length(self):
        from forgeos_auth import LoginRequest

        with pytest.raises(Exception):
            LoginRequest(username="x" * 129, password="ok")

    def test_password_max_length(self):
        from forgeos_auth import LoginRequest

        with pytest.raises(Exception):
            LoginRequest(username="ok", password="x" * 129)


class TestUserManagement:
    """User load/save operations."""

    def test_load_users_returns_dict_when_file_missing(self, monkeypatch):
        from forgeos_auth import load_users, USERS_FILE

        users = load_users()
        assert isinstance(users, dict)

    def test_save_and_load_users(self, tmp_path):
        from forgeos_auth import load_users, save_users, USERS_FILE

        test_users = {"alice": {"password": "$2b$12$abc", "role": "user"}}
        save_users(test_users)
        loaded = load_users()
        assert loaded == test_users

    def test_save_overwrites_previous(self, tmp_path):
        from forgeos_auth import load_users, save_users

        save_users({"a": {"role": "admin"}})
        save_users({"b": {"role": "user"}})
        loaded = load_users()
        assert "a" not in loaded
        assert loaded["b"]["role"] == "user"

    def test_save_users_sets_0600_permissions(self):
        """The user store holds password hashes — must never be world-readable."""
        import stat
        from forgeos_auth import save_users, USERS_FILE

        save_users({"alice": {"hash": "$2b$12$abc", "role": "admin"}})
        mode = stat.S_IMODE(USERS_FILE.stat().st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    def test_save_users_is_atomic_no_temp_left_behind(self):
        """After a successful save, no .api-users.*.tmp litter remains."""
        from forgeos_auth import save_users, USERS_FILE

        save_users({"alice": {"hash": "x", "role": "admin"}})
        leftovers = list(USERS_FILE.parent.glob(".api-users.*.tmp"))
        assert leftovers == [], f"temp files left behind: {leftovers}"

    def test_save_users_cleans_up_temp_on_serialization_failure(self):
        """If json.dump raises mid-write, the temp file must be removed and
        the existing user file left intact (not truncated)."""
        from forgeos_auth import save_users, load_users, USERS_FILE

        # Seed a known-good file first
        save_users({"alice": {"hash": "good", "role": "admin"}})

        # Something json can't serialize → json.dump raises mid-write
        class Unserializable:
            pass

        with pytest.raises(TypeError):
            save_users({"bob": {"obj": Unserializable()}})

        # Original file must be intact, no temp litter
        assert load_users() == {"alice": {"hash": "good", "role": "admin"}}
        assert list(USERS_FILE.parent.glob(".api-users.*.tmp")) == []


class TestJwtSecretLoading:
    """Verify _load_jwt_secret refuses to start with missing/placeholder secrets.

    These tests cover the C-001 hardening — the runtime never generates
    a secret. If neither env nor config provides a valid one, the API
    must refuse to start with a clear error.
    """

    def test_env_secret_takes_priority(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret
        import forgeos_auth as fa

        # Config file says one thing
        cfg = tmp_path / "forgeos.conf"
        cfg.write_text('WEBUI_JWT_SECRET="from-config"\n')
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        # Env says another — env wins
        monkeypatch.setenv("FORGEOS_JWT_SECRET", "from-env-takes-priority")

        assert _load_jwt_secret() == "from-env-takes-priority"

    def test_falls_back_to_config_file(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret
        import forgeos_auth as fa

        cfg = tmp_path / "forgeos.conf"
        cfg.write_text('WEBUI_JWT_SECRET="real-secret-from-config-file"\n')
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        assert _load_jwt_secret() == "real-secret-from-config-file"

    def test_refuses_missing_env_and_missing_config(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        # Point at a config file that doesn't exist
        monkeypatch.setattr(fa, "CONFIG_FILE", tmp_path / "does-not-exist.conf")
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        with pytest.raises(JwtSecretMissingError) as exc_info:
            _load_jwt_secret()

        # Error message must tell the user how to fix it
        msg = str(exc_info.value)
        assert "api.env" in msg, "Error must mention the installer fix (v2: /etc/forgeos/api.env)"
        assert "WEBUI_JWT_SECRET" in msg, "Error must name the config key"

    def test_refuses_placeholder_changeme(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        cfg = tmp_path / "forgeos.conf"
        cfg.write_text('WEBUI_JWT_SECRET="changeme"\n')
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        with pytest.raises(JwtSecretMissingError):
            _load_jwt_secret()

    def test_refuses_placeholder_changeme_long_form(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        cfg = tmp_path / "forgeos.conf"
        cfg.write_text('WEBUI_JWT_SECRET="changeme-set-in-forgeos.conf"\n')
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        with pytest.raises(JwtSecretMissingError):
            _load_jwt_secret()

    def test_refuses_empty_string_secret(self, tmp_path, monkeypatch):
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        cfg = tmp_path / "forgeos.conf"
        cfg.write_text('WEBUI_JWT_SECRET=""\n')
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        with pytest.raises(JwtSecretMissingError):
            _load_jwt_secret()

    def test_refuses_placeholder_in_env_var_too(self, tmp_path, monkeypatch):
        """Env var with a placeholder must NOT be accepted (it's still a placeholder)."""
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        # No config file
        monkeypatch.setattr(fa, "CONFIG_FILE", tmp_path / "no-config.conf")
        monkeypatch.setenv("FORGEOS_JWT_SECRET", "changeme")

        with pytest.raises(JwtSecretMissingError):
            _load_jwt_secret()

    def test_no_runtime_generation_attempted(self, tmp_path, monkeypatch):
        """The function must NEVER create or modify the config file.

        This is the C-001 fix: secret generation moved to the installer.
        Runtime must be pure-read.
        """
        from forgeos_auth import _load_jwt_secret, JwtSecretMissingError
        import forgeos_auth as fa

        cfg = tmp_path / "forgeos.conf"
        # Note: file does NOT exist before the call
        monkeypatch.setattr(fa, "CONFIG_FILE", cfg)
        monkeypatch.delenv("FORGEOS_JWT_SECRET", raising=False)

        try:
            _load_jwt_secret()
        except JwtSecretMissingError:
            pass

        # The function must NOT have created the file as a side effect.
        assert not cfg.exists(), (
            "_load_jwt_secret created config file as a side effect — "
            "this is the race-prone path C-001 was meant to remove."
        )

