"""ForgeOS — Notifications API surface.

Mounts under the existing FastAPI app via:

    from notifications_api import router as notifications_router, set_helpers as set_notifications_helpers
    set_notifications_helpers(conf=conf)
    app.include_router(notifications_router)

Routes:
  • POST /api/notify          — internal notification endpoint (scripts, alertmanager)
  • POST /api/drive-alert     — SMART/hot-swap drive alerts → tray indicators
  • GET  /api/notifications   — list recent notifications (last 20, newest first)
  • GET  /api/drive-alerts    — current drive alerts state
  • POST /api/alert-webhook   — Alertmanager webhook bridge → /api/notify

State:
  _notifications and _drive_alerts are module-level. NOT thread-safe.
  Production runs with workers=1 — if workers>1 is needed, wrap with asyncio.Lock.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import deque
from typing import Callable, Optional

from fastapi import APIRouter, Depends

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# In-memory notification stores — see module docstring.
_notifications: deque[dict] = deque(maxlen=100)
_drive_alerts: dict[str, dict] = {}

# Injected by main module — see set_helpers().
_conf_get: Optional[Callable[[str, str], str]] = None


def set_helpers(conf: Callable[[str, str], str]) -> None:
    global _conf_get
    _conf_get = conf


@router.post("/api/notify")
async def notify(body: dict):
    """Internal notification endpoint — called by scripts and alertmanager."""
    assert _conf_get is not None
    level = body.get("level", "info")
    title = body.get("title", "ForgeOS")
    message = body.get("message", "")

    # Forward to Gotify
    gotify_url = _conf_get("GOTIFY_URL", "http://localhost:8070")
    gotify_tok = _conf_get("GOTIFY_TOKEN", "")
    if gotify_tok:
        priority = {"info": 2, "warning": 5, "warn": 5, "critical": 10, "err": 8}.get(level, 2)
        _payload = json.dumps({"title": title, "message": message, "priority": priority})
        subprocess.run(
            ["curl", "-sf", "-X", "POST",
             f"{gotify_url}/message?token={gotify_tok}",
             "-H", "Content-Type: application/json",
             "-d", _payload],
            capture_output=True, timeout=10,
        )

    # Forward to Apprise (if configured)
    apprise_urls = _conf_get("APPRISE_URLS", "")
    if apprise_urls:
        subprocess.run(
            ["apprise", "-t", title, "-b", message, apprise_urls],
            capture_output=True, timeout=10,
        )

    # Store in notification queue for Web UI
    _notifications.append({"level": level, "title": title, "message": message, "ts": time.time()})

    return {"ok": True}


@router.post("/api/drive-alert")
async def drive_alert(body: dict):
    """Drive SMART/hot-swap alerts — updates tray indicators."""
    _drive_alerts[body.get("device", "?")] = {
        "level": body.get("level", "warn"),
        "message": body.get("message", ""),
        "ts": time.time(),
    }
    await notify(body)
    return {"ok": True}


@router.get("/api/notifications")
async def get_notifications(user=Depends(verify_token)):
    return {"notifications": list(reversed(list(_notifications)[-20:]))}


@router.get("/api/drive-alerts")
async def get_drive_alerts(user=Depends(verify_token)):
    return {"alerts": _drive_alerts}


@router.post("/api/alert-webhook")
async def alertmanager_webhook(body: dict):
    """Alertmanager webhook → forward to /api/notify."""
    for alert in body.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status_ = alert.get("status", "firing")
        level = "critical" if status_ == "firing" else "info"
        title = labels.get("alertname", "Alert")
        message = annotations.get("description", annotations.get("summary", str(labels)))
        await notify({"level": level, "title": title, "message": message})
    return {"ok": True}
