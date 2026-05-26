"""
ForgeOS system endpoint tests.

The dashboard depends on /api/system/info for the CPU model label.
If this endpoint changes shape without a corresponding UI update,
the label silently shows nothing — worse than a crash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestSystemInfo:
    """GET /api/system/info — used by dashboard for CPU model label."""

    ENDPOINT = "/api/system/info"
    EXPECTED_FIELDS = {
        "hostname", "os", "kernel", "cpu",
        "cpu_cores", "forgeos_ver", "uptime", "boot_time",
    }

    def test_requires_auth(self, test_client: TestClient) -> None:
        r = test_client.get(self.ENDPOINT)
        assert r.status_code == 401

    def test_returns_all_fields(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get(self.ENDPOINT, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == self.EXPECTED_FIELDS, (
            f"Field mismatch. Got: {set(data.keys())}, Expected: {self.EXPECTED_FIELDS}"
        )
        for field in data:
            assert isinstance(data[field], str), f"{field} should be str, got {type(data[field])}"
        assert len(data["hostname"]) > 0
        assert len(data["os"]) > 0
        assert len(data["kernel"]) > 0
        assert len(data["cpu"]) > 0
