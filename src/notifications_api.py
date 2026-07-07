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
import time
from collections import deque

from fastapi import APIRouter, Depends

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# In-memory notification stores — see module docstring.
_notifications: deque[dict] = deque(maxlen=100)
_drive_alerts: dict[str, dict] = {}

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
    _notifications.append({"level": level, "title": title,
                           "message": message, "ts": time.time()})


@router.post("/api/drive-alert")
async def drive_alert(body: dict, user=Depends(verify_token)):
    """Drive SMART/hot-swap alerts — updates tray indicators.
    ponytail: if a root-owned smartd hook ever needs to post these, give it
    a unix-socket path or a service token — do not remove auth again."""
    _drive_alerts[body.get("device", "?")] = {
        "level": body.get("level", "warn"),
        "message": body.get("message", ""),
        "ts": time.time(),
    }
    record(body.get("level", "warn"), body.get("title", "Drive alert"),
           body.get("message", ""))
    return {"ok": True}


@router.get("/api/notifications")
async def get_notifications(user=Depends(verify_token)):
    return {"notifications": list(reversed(list(_notifications)[-20:]))}


@router.get("/api/drive-alerts")
async def get_drive_alerts(user=Depends(verify_token)):
    return {"alerts": _drive_alerts}
