"""ForgeOS SMTP notification sender.

A NOTIFICATION sender (alerts on errors, service/app down), NOT a mail
server. Sends via an existing SMTP account/relay configured in the config
DB. This is a third sink alongside the existing Gotify + Apprise fan-out in
notifications_api — reconciled, not duplicated.

Secret policy: the SMTP password is NOT stored in the config DB. It lives in
the keystore (/etc/forgeos/smtp/password, 0600) and is read at send time —
same pattern as the WireGuard server key.

build_message() is pure (config + text -> EmailMessage) so it can be
unit-tested without a real SMTP server. send() is the only part that touches
the network, and it's injected with an SMTP class so tests can pass a fake.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from forgeos_config import SmtpConfig

SMTP_KEY_DIR = "/etc/forgeos/smtp"


class SmtpError(RuntimeError):
    pass


def password_path() -> Path:
    return Path(SMTP_KEY_DIR) / "password"


def read_password() -> str:
    p = password_path()
    if p.exists():
        return p.read_text().strip()
    return ""


def build_message(cfg: SmtpConfig, subject: str, body: str) -> EmailMessage:
    """Pure: config + content -> EmailMessage. No I/O. Unit-testable."""
    if not cfg.from_addr:
        raise SmtpError("smtp.from_addr is not set")
    if not cfg.to_addrs:
        raise SmtpError("smtp.to_addrs is empty")
    msg = EmailMessage()
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.to_addrs)
    msg["Subject"] = f"[ForgeOS] {subject}"
    msg.set_content(body)
    return msg


def send(
    cfg: SmtpConfig,
    subject: str,
    body: str,
    *,
    password: str | None = None,
    smtp_factory=None,
) -> None:
    """Send a notification email.

    `smtp_factory` lets tests inject a fake SMTP class. In production it
    defaults to smtplib.SMTP_SSL (port 465) or smtplib.SMTP (+STARTTLS).
    """
    if not cfg.enabled:
        raise SmtpError("smtp is not enabled")
    if not cfg.host:
        raise SmtpError("smtp.host is not set")

    msg = build_message(cfg, subject, body)
    pw = password if password is not None else read_password()

    if smtp_factory is None:
        if cfg.use_ssl:
            smtp_factory = smtplib.SMTP_SSL
        else:
            smtp_factory = smtplib.SMTP

    try:
        with smtp_factory(cfg.host, cfg.port, timeout=15) as server:
            if cfg.use_tls and not cfg.use_ssl:
                server.starttls()
            if cfg.username and pw:
                server.login(cfg.username, pw)
            server.send_message(msg)
    except Exception as e:  # noqa: BLE001 — surface as a typed error
        raise SmtpError(f"SMTP send failed: {type(e).__name__}: {e}") from e


def send_safe(cfg: SmtpConfig, subject: str, body: str, **kw) -> bool:
    """Non-raising convenience: returns True on success, False otherwise."""
    try:
        send(cfg, subject, body, **kw)
        return True
    except SmtpError:
        return False
