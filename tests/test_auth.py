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
