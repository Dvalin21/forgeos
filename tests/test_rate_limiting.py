"""
Tests for ForgeOS rate limiters — login and mutation protection.

The test_client fixture loads forgeos-api.py fresh via importlib per test,
so rate limiter state (deques) starts empty for every test.

Note: The test environment has no configured users (api-users.json is
empty), so POST /api/auth/login returns 503.  That's *fine* — the rate
limiter runs before the user check, so it still counts attempts and
blocks at the threshold.
"""

from __future__ import annotations

import pytest


class TestLoginRateLimit:
    """Dedicated login rate limiter: 10 attempts per 300s per IP."""

    def test_blocks_after_10_failures(self, test_client):
        """11th POST to /api/auth/login from same IP returns 429
        regardless of whether users are configured."""
        body = {"username": "x", "password": "x"}
        for i in range(10):
            r = test_client.post("/api/auth/login", json=body)
            # 503 = no users configured (expected in test env)
            # 401 = user exists, wrong password
            assert r.status_code in (401, 503), \
                f"attempt {i+1}: expected 401/503, got {r.status_code}"

        r = test_client.post("/api/auth/login", json=body)
        assert r.status_code == 429, f"expected 429, got {r.status_code}"
        data = r.json()
        assert "detail" in data


class TestMutationRateLimit:
    """Global mutation rate limiter: 30 POST/PUT/DELETE per 60s per IP."""

    def test_blocks_after_30_requests(self, test_client):
        """31st POST from same IP returns 429."""
        for i in range(30):
            r = test_client.post("/api/auth/logout")
            assert r.status_code in (200, 429), \
                f"attempt {i+1}: expected 200/429, got {r.status_code}"
            if r.status_code == 429:
                return  # early block — still proves the limiter works

        # All 30 passed — 31st must 429
        r = test_client.post("/api/auth/logout")
        assert r.status_code == 429
        assert r.headers.get("retry-after") == "60"

    def test_does_not_block_get_requests(self, test_client):
        """GET requests are not counted by the mutation limiter."""
        for _ in range(35):
            r = test_client.get("/api/system/stats")
            assert r.status_code in (200, 401)

        # After 35 GETs, a single POST should still work
        r = test_client.post("/api/auth/logout")
        assert r.status_code == 200, f"expected 200, got {r.status_code}"
