"""Tests for notifications_api.py (v2 contract).

All routes require auth — the v1 no-auth POSTs were LAN-spammable and could
trigger SMTP sends through the box's own relay. /api/alert-webhook is gone.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_notification_state():
    import notifications_api
    notifications_api._notifications.clear()
    notifications_api._drive_alerts.clear()
    yield
    notifications_api._notifications.clear()
    notifications_api._drive_alerts.clear()


class TestAuthBoundary:
    def test_notify_requires_auth(self, test_client):
        r = test_client.post("/api/notify", json={"title": "spam"})
        assert r.status_code in (401, 403)

    def test_drive_alert_requires_auth(self, test_client):
        r = test_client.post("/api/drive-alert", json={"device": "sda"})
        assert r.status_code in (401, 403)

    def test_alert_webhook_deleted(self, test_client, auth_headers):
        assert test_client.post("/api/alert-webhook", json={},
                                headers=auth_headers).status_code == 404


class TestNotify:
    def test_roundtrip(self, test_client, auth_headers):
        r = test_client.post("/api/notify", headers=auth_headers,
                             json={"level": "info", "title": "T", "message": "m"})
        assert r.status_code == 200
        d = test_client.get("/api/notifications", headers=auth_headers).json()
        assert d["notifications"][0]["title"] == "T"

    def test_warning_goes_to_smtp_when_enabled(self, test_client, auth_headers, monkeypatch):
        import forgeos_config as fcfg
        import forgeos_smtp as fsmtp
        cfg = fcfg.load()
        cfg.smtp = fcfg.SmtpConfig(enabled=True, host="smtp.example.com",
                                   from_addr="a@b.c", to_addrs=["k@b.c"])
        fcfg.save(cfg)
        sent = []
        monkeypatch.setattr(fsmtp, "send_safe", lambda c, t, b: sent.append(t))
        test_client.post("/api/notify", headers=auth_headers,
                         json={"level": "warning", "title": "W", "message": "m"})
        assert sent == ["W"]

    def test_info_never_hits_smtp(self, test_client, auth_headers, monkeypatch):
        import forgeos_smtp as fsmtp
        sent = []
        monkeypatch.setattr(fsmtp, "send_safe", lambda c, t, b: sent.append(t))
        test_client.post("/api/notify", headers=auth_headers,
                         json={"level": "info", "title": "I", "message": "m"})
        assert sent == []


class TestDriveAlerts:
    def test_roundtrip(self, test_client, auth_headers):
        test_client.post("/api/drive-alert", headers=auth_headers,
                         json={"device": "sdb", "level": "critical", "message": "SMART fail"})
        d = test_client.get("/api/drive-alerts", headers=auth_headers).json()
        assert d["alerts"]["sdb"]["level"] == "critical"
        n = test_client.get("/api/notifications", headers=auth_headers).json()
        assert n["notifications"][0]["level"] == "critical"


class TestPersistence:
    """Notifications used to live in a module-level deque, so an API restart
    wiped them — precisely the moment someone comes back to ask "did it warn
    me?". They now persist to SQLite and are read back from there."""

    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        import sqlite3
        import notifications_api
        # check_same_thread=False mirrors the app's real connection
        # (forgeos-api._get_db): FastAPI serves endpoints on worker threads.
        conn = sqlite3.connect(str(tmp_path / "forgeos.db"), check_same_thread=False)
        notifications_api.set_helpers(get_db=lambda: conn)
        yield conn
        notifications_api.set_helpers(get_db=None)
        conn.close()

    def test_survives_a_restart(self, test_client, auth_headers, db, monkeypatch):
        import notifications_api
        r = test_client.post("/api/notify", headers=auth_headers,
                             json={"level": "warning", "title": "Scrub found errors",
                                   "message": "tank: csum mismatch"})
        assert r.status_code == 200

        # simulate the restart: memory stores emptied, DB untouched
        notifications_api._notifications.clear()

        r = test_client.get("/api/notifications", headers=auth_headers)
        titles = [n["title"] for n in r.json()["notifications"]]
        assert "Scrub found errors" in titles

    def test_drive_alert_state_survives(self, test_client, auth_headers, db,
                                        monkeypatch):
        import notifications_api
        test_client.post("/api/drive-alert", headers=auth_headers,
                         json={"device": "sdc", "level": "critical",
                               "message": "predict failure"})
        notifications_api._drive_alerts.clear()
        r = test_client.get("/api/drive-alerts", headers=auth_headers)
        assert "sdc" in r.json()["alerts"]
        assert r.json()["alerts"]["sdc"]["message"] == "predict failure"

    def test_log_stays_bounded(self, test_client, auth_headers, db):
        for i in range(130):
            test_client.post("/api/notify", headers=auth_headers,
                             json={"title": f"n{i}", "message": "x"})
        n = db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        assert n <= 100, f"durable log must stay bounded, got {n}"

    def test_works_without_a_database(self, test_client, auth_headers):
        # no injected connection: must behave exactly as before, not crash
        r = test_client.post("/api/notify", headers=auth_headers,
                             json={"title": "in-memory only"})
        assert r.status_code == 200
        r = test_client.get("/api/notifications", headers=auth_headers)
        assert any(n["title"] == "in-memory only" for n in r.json()["notifications"])
