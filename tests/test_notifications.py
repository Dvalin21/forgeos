"""Tests for notifications_api.py routes (C-009).

Covers the 5 notification routes that previously had zero coverage:
  POST /api/notify          (no auth — internal)
  POST /api/drive-alert     (no auth — internal)
  GET  /api/notifications   (auth required)
  GET  /api/drive-alerts    (auth required)
  POST /api/alert-webhook   (no auth — alertmanager)

These routes mutate module-level state (_notifications deque,
_drive_alerts dict). Each test clears that state first so tests
don't bleed into each other.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_notification_state():
    """Reset the module-level notification stores before each test."""
    import notifications_api
    notifications_api._notifications.clear()
    notifications_api._drive_alerts.clear()
    yield
    notifications_api._notifications.clear()
    notifications_api._drive_alerts.clear()


class TestNotify:
    """POST /api/notify — internal notification endpoint, no auth."""

    def test_notify_no_auth_required(self, test_client):
        # No auth header — should still succeed (internal endpoint)
        resp = test_client.post("/api/notify", json={
            "level": "info", "title": "Test", "message": "hello"
        })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_notify_stores_in_queue(self, test_client):
        import notifications_api
        test_client.post("/api/notify", json={
            "level": "warning", "title": "Disk", "message": "SMART warning"
        })
        assert len(notifications_api._notifications) == 1
        stored = notifications_api._notifications[0]
        assert stored["level"] == "warning"
        assert stored["title"] == "Disk"
        assert stored["message"] == "SMART warning"
        assert "ts" in stored

    def test_notify_defaults_when_fields_missing(self, test_client):
        import notifications_api
        # Empty body — defaults should apply
        resp = test_client.post("/api/notify", json={})
        assert resp.status_code == 200
        stored = notifications_api._notifications[0]
        assert stored["level"] == "info"
        assert stored["title"] == "ForgeOS"
        assert stored["message"] == ""


class TestDriveAlert:
    """POST /api/drive-alert — drive SMART/hotswap alerts, no auth."""

    def test_drive_alert_no_auth_required(self, test_client):
        resp = test_client.post("/api/drive-alert", json={
            "device": "/dev/sda", "level": "critical", "message": "drive failing"
        })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_drive_alert_keyed_by_device(self, test_client):
        import notifications_api
        test_client.post("/api/drive-alert", json={
            "device": "/dev/sdb", "level": "warn", "message": "reallocated sectors"
        })
        assert "/dev/sdb" in notifications_api._drive_alerts
        alert = notifications_api._drive_alerts["/dev/sdb"]
        assert alert["level"] == "warn"
        assert alert["message"] == "reallocated sectors"

    def test_drive_alert_also_creates_notification(self, test_client):
        import notifications_api
        # drive_alert calls notify() internally
        test_client.post("/api/drive-alert", json={
            "device": "/dev/sdc", "level": "critical", "message": "drive dead"
        })
        # Should appear in BOTH the drive_alerts dict and the notifications queue
        assert "/dev/sdc" in notifications_api._drive_alerts
        assert len(notifications_api._notifications) == 1

    def test_drive_alert_unknown_device_uses_placeholder(self, test_client):
        import notifications_api
        # No device field — keyed under "?"
        test_client.post("/api/drive-alert", json={"level": "warn", "message": "x"})
        assert "?" in notifications_api._drive_alerts


class TestGetNotifications:
    """GET /api/notifications — requires auth."""

    def test_requires_auth(self, test_client):
        resp = test_client.get("/api/notifications")
        assert resp.status_code in (401, 403)

    def test_returns_notifications_with_auth(self, test_client, auth_headers):
        # Seed one notification
        test_client.post("/api/notify", json={"title": "A", "message": "1"})
        resp = test_client.get("/api/notifications", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "A"

    def test_returns_newest_first(self, test_client, auth_headers):
        for i in range(3):
            test_client.post("/api/notify", json={"title": f"msg{i}", "message": str(i)})
        resp = test_client.get("/api/notifications", headers=auth_headers)
        titles = [n["title"] for n in resp.json()["notifications"]]
        # Newest first — msg2, msg1, msg0
        assert titles == ["msg2", "msg1", "msg0"]

    def test_caps_at_20(self, test_client, auth_headers):
        for i in range(25):
            test_client.post("/api/notify", json={"title": f"m{i}", "message": str(i)})
        resp = test_client.get("/api/notifications", headers=auth_headers)
        assert len(resp.json()["notifications"]) == 20


class TestGetDriveAlerts:
    """GET /api/drive-alerts — requires auth."""

    def test_requires_auth(self, test_client):
        resp = test_client.get("/api/drive-alerts")
        assert resp.status_code in (401, 403)

    def test_returns_alerts_with_auth(self, test_client, auth_headers):
        test_client.post("/api/drive-alert", json={
            "device": "/dev/sda", "level": "warn", "message": "test"
        })
        resp = test_client.get("/api/drive-alerts", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "/dev/sda" in data["alerts"]


class TestAlertWebhook:
    """POST /api/alert-webhook — Alertmanager bridge, no auth."""

    def test_webhook_no_auth_required(self, test_client):
        resp = test_client.post("/api/alert-webhook", json={"alerts": []})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_webhook_creates_notification_per_alert(self, test_client):
        import notifications_api
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "HighCPU"},
                    "annotations": {"description": "CPU over 90%"},
                },
                {
                    "status": "resolved",
                    "labels": {"alertname": "DiskFull"},
                    "annotations": {"summary": "Disk recovered"},
                },
            ]
        }
        test_client.post("/api/alert-webhook", json=payload)
        assert len(notifications_api._notifications) == 2

    def test_webhook_firing_is_critical(self, test_client):
        import notifications_api
        test_client.post("/api/alert-webhook", json={
            "alerts": [{
                "status": "firing",
                "labels": {"alertname": "Test"},
                "annotations": {"description": "d"},
            }]
        })
        assert notifications_api._notifications[0]["level"] == "critical"

    def test_webhook_resolved_is_info(self, test_client):
        import notifications_api
        test_client.post("/api/alert-webhook", json={
            "alerts": [{
                "status": "resolved",
                "labels": {"alertname": "Test"},
                "annotations": {"description": "d"},
            }]
        })
        assert notifications_api._notifications[0]["level"] == "info"
