"""ForgeOS — Notifications API surface (v2: auth-required, SMTP-only sink).

Routes (all require a session token):
  • POST /api/notify          — UI/test intake; Python callers use record()
  • POST /api/drive-alert     — SMART/hot-swap drive alerts → tray indicators
  • GET  /api/notifications   — last 20, newest first
  • GET  /api/drive-alerts    — current drive alerts state

Deleted from v1: Gotify + Apprise forwarders and the /api/alert-webhook
alertmanager bridge — none of that stack exists in v2, and the endpoints
were unauthenticated (LAN-spammable, SMTP-relay abuse; Gotify curl leaked
the token into /proc/*/cmdline).

State:
  _notifications and _drive_alerts are module-level, in-memory (lost on
  restart — they are transient toasts; the audit log is the durable trail).
  NOT thread-safe. Production runs workers=1.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from typing import Callable, Optional

from fastapi import APIRouter, Depends

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by the main module — see set_helpers(). Persistence is optional:
# without it the stores stay in memory (tests, dev), exactly as before.
_get_db: Optional[Callable[[], sqlite3.Connection]] = None


def set_helpers(get_db: Optional[Callable[[], sqlite3.Connection]] = None) -> None:
    """Wire the SQLite connection used to persist notifications across a
    restart. A notification that vanishes when the API restarts is exactly the
    thing a user asks about after the fact ("did it warn me?")."""
    global _get_db
    _get_db = get_db
    if _get_db is not None:
        try:
            _get_db().execute(
                "CREATE TABLE IF NOT EXISTS notifications ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " ts REAL NOT NULL, level TEXT NOT NULL,"
                " title TEXT NOT NULL, message TEXT NOT NULL)"
            )
            _get_db().commit()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("notifications table unavailable: %s", exc)


# In-memory stores — the hot read path, and the durable copy lives in SQLite
# when a connection was injected. See module docstring.
_NOTIF_MAX = 100
_notifications: deque[dict] = deque(maxlen=_NOTIF_MAX)
_drive_alerts: dict[str, dict] = {}

# drive alerts are keyed by device (a device's CURRENT state), so they persist
# as rows in their own table rather than as a growing notifications log.
def _persist_drive_alert(device: str, payload: dict) -> None:
    if _get_db is None:
        return
    try:
        conn = _get_db()
        conn.execute("CREATE TABLE IF NOT EXISTS drive_alerts ("
                     " device TEXT PRIMARY KEY, ts REAL NOT NULL,"
                     " level TEXT NOT NULL, message TEXT NOT NULL)")
        conn.execute("INSERT INTO drive_alerts (device, ts, level, message) VALUES (?,?,?,?)"
                     " ON CONFLICT(device) DO UPDATE SET ts=excluded.ts,"
                     " level=excluded.level, message=excluded.message",
                     (device, payload.get("ts", 0), payload.get("level", "warn"),
                      payload.get("message", "")))
        conn.commit()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("could not persist drive alert for %s: %s", device, exc)

@router.post("/api/notify")
async def notify(body: dict, user=Depends(verify_token)):
    """Notification intake. AUTH REQUIRED — the v1 no-auth version let any
    LAN client spam the queue and trigger SMTP sends through the box's own
    relay. Internal Python callers use record() directly, not HTTP.
    Gotify/Apprise/alertmanager forwarders deleted with the v1 stack (none
    are installed by v2; the Gotify curl also leaked the token into
    /proc/*/cmdline). SMTP is the v2 delivery path."""
    record(body.get("level", "info"), body.get("title", "ForgeOS"),
           body.get("message", ""))
    return {"ok": True}


def record(level: str, title: str, message: str) -> None:
    """In-process notification sink — call this from Python, not /api/notify.

    SMTP only for warning+ (info is too noisy for inboxes); a mail
    misconfig must never break the caller."""
    if level in ("warning", "warn", "critical", "err", "error"):
        try:
            import forgeos_config as _fc
            import forgeos_smtp as _smtp
            _cfg = _fc.load()
            if _cfg.smtp.enabled:
                _smtp.send_safe(_cfg.smtp, title, message)
        except Exception:
            pass  # never let notification delivery crash the caller
    entry = {"level": level, "title": title,
             "message": message, "ts": time.time()}
    _notifications.append(entry)
    if _get_db is not None:
        try:
            conn = _get_db()
            conn.execute("CREATE TABLE IF NOT EXISTS notifications ("
                         " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                         " ts REAL NOT NULL, level TEXT NOT NULL,"
                         " title TEXT NOT NULL, message TEXT NOT NULL)")
            conn.execute("INSERT INTO notifications (ts, level, title, message) VALUES (?,?,?,?)",
                         (entry["ts"], level, title, message))
            # keep the durable log bounded the same way the memory deque is
            conn.execute("DELETE FROM notifications WHERE id NOT IN "
                         "(SELECT id FROM notifications ORDER BY id DESC LIMIT ?)", (_NOTIF_MAX,))
            conn.commit()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("could not persist notification: %s", exc)


@router.post("/api/drive-alert")
async def drive_alert(body: dict, user=Depends(verify_token)):
    """Drive SMART/hot-swap alerts — updates tray indicators.
    ponytail: if a root-owned smartd hook ever needs to post these, give it
    a unix-socket path or a service token — do not remove auth again."""
    _device = body.get("device", "?")
    _alert = {
        "level": body.get("level", "warn"),
        "message": body.get("message", ""),
        "ts": time.time(),
    }
    _drive_alerts[_device] = _alert
    _persist_drive_alert(_device, _alert)
    record(body.get("level", "warn"), body.get("title", "Drive alert"),
           body.get("message", ""))
    return {"ok": True}


@router.get("/api/notifications")
async def get_notifications(user=Depends(verify_token)):
    """Newest first, last 20 — read from the durable store so the list survives
    an API restart (which is exactly when someone comes looking for it)."""
    rows = _recent_from_db()
    if rows:
        return {"notifications": rows}
    return {"notifications": list(reversed(list(_notifications)[-20:]))}


@router.get("/api/drive-alerts")
async def get_drive_alerts(user=Depends(verify_token)):
    return {"alerts": _drive_alerts or _drive_alerts_from_db()}


def _recent_from_db(limit: int = 20) -> list[dict]:
    if _get_db is None:
        return []
    try:
        rows = _get_db().execute(
            "SELECT ts, level, title, message FROM notifications "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    except Exception:                                       # noqa: BLE001
        return []
    return [{"ts": r[0], "level": r[1], "title": r[2], "message": r[3]} for r in rows]


def _drive_alerts_from_db() -> dict[str, dict]:
    if _get_db is None:
        return {}
    try:
        rows = _get_db().execute(
            "SELECT device, ts, level, message FROM drive_alerts").fetchall()
    except Exception:                                       # noqa: BLE001
        return {}
    return {r[0]: {"ts": r[1], "level": r[2], "message": r[3]} for r in rows}
