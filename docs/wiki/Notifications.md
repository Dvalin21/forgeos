# Notifications

`/notifications.html`. Recent events and drive alerts.

## Recent

The latest 20 events, newest first, held in memory — they are cleared on
API restart. **The durable audit trail is the Activity Log page.**

## Drive alerts

SMART warnings and hot-swap events, one line per event, each marked with
the drive.

**Send test notification** (top right) — sends a test email through the
SMTP settings from [Settings](Settings). If no SMTP host is configured it
errors rather than pretending to send.

## Verified

- Both panels render their empty states ("Nothing yet.", "No drive alerts.").
