"""
ForgeOS security header tests.

Verifies the ASGI SecurityHeadersMiddleware emits the expected
headers on every response. A regression here silently weakens
defense-in-depth — few things are worse than a security control
that looks active but is not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestSecurityHeaders:
    """Every response should carry the full set of security headers."""

    EXPECTED = {
        "content-security-policy": (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' ws: wss:; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'"
        ),
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
    }

    def test_sends_csp_header(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get("/api/system/stats", headers=auth_headers)
        assert r.headers.get("content-security-policy") == self.EXPECTED["content-security-policy"]

    def test_sends_x_content_type_options(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get("/api/system/stats", headers=auth_headers)
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_sends_x_frame_options(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get("/api/system/stats", headers=auth_headers)
        assert r.headers.get("x-frame-options") == "DENY"

    def test_sends_referrer_policy(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get("/api/system/stats", headers=auth_headers)
        assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_headers_on_error_response(self, test_client: TestClient) -> None:
        """Even 404s and 401s must carry security headers."""
        r = test_client.get("/api/nonexistent")
        assert r.headers.get("content-security-policy") is not None
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
