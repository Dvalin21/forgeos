# Settings

`/settings.html`. System identity, timezone, theme, appearance, and SMTP.

## System card

- **Version** — installed ForgeOS version.
- **Hostname** — applied via `hostnamectl` on save. Samba/NetBIOS and logs
  pick up the new name after a service restart.
- **LAN name (mDNS)** — the name clients reach on the LAN, e.g.
  `forgeos.local`.
- **Public FQDN** — globally resolvable name for real TLS. Never a
  `.local` name.
- **Timezone** — IANA name (e.g. `America/Chicago`), applied via
  `timedatectl` when you save.
- **Theme** — Auto (follows OS), Light, or Dark. Applies immediately and
  persists in this browser.
- **Save system settings** — validates and applies all of the above;
  logs `settings.update`.

## Notification email card

Outbound SMTP for service alerts — it is not a mail server.

- **Enable email notifications** — toggles the alert pipeline.
- **SMTP host / Port** — e.g. `smtp.example.com:587`.
- **STARTTLS** — on for port 587; off means SMTPS on port 465.
- **Username / Password** — keystore-backed (0600 perms), never in
  config.json. Leave the password blank to keep the current one.
- **From / To addresses** — sender identity and comma-separated
  recipients.
- **Save SMTP** persists; **Send test email** sends a real message through
  the saved settings.

## Verified

- Hostname/timezone/LAN name/public FQDN round-trip through
  `GET /api/settings` (admin) — last driven update was `settings.update` in
  the audit log.
- Theme change is immediate; verified via the appearance selector and
  `localStorage.forgeos_theme`.
