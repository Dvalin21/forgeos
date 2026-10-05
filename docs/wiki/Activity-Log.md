# Activity Log

`/activity.html`. Who did what, when, and to what — the durable audit
trail. (The Notifications page is in-memory; this one is not.)

## Filters

- **User** — exact username to filter by.
- **Action** — exact action string (e.g. `backup.job.create`).
- **Apply** filters, **Clear** resets.

## Table

Columns: TIME (absolute + relative), USER, ACTION, STATUS (success /
pending / warning pill), DETAIL. The audit log keeps up to 50 rows per
page; the counter shows `1-50 of 192` with Newer/Older navigation.

## What it records

Everything state-changing: auth (login, password change), storage (pool
create/adopt/destroy, drives, scrubs), files (chmod/chown), shares,
network (interfaces, routes, DDNS), firewall toggles, VPN, docker,
settings, backup, users.

## Verified

- `settings.update`, `storage.pool.adopt`, `docker.run`, `vpn.stop`,
  `firewall.toggle`, `files.chown`, `net.route.add/delete` all appear with
  correct timestamps and user.
