# Dashboard

The Dashboard is the landing page after login (`https://<ip>/index.html` or `/`).
It reads live data from `GET /api/system/*` and `GET /api/storage/*`.

## Sections

**Hero banner** — shows "Mostly fine — one thing to look at" when something
needs attention, the hostname (`forgeos`), and uptime. Two actions:
- **Create Snapshot** — takes a btrfs snapshot of the pool root. This runs
  `snapper create` on the pool. It is safe to run while the system is busy;
  snapshots are copy-on-write and instant.
- **New Share** — jumps to the new-share dialog on Shares (SMB).

**Ring gauges** — Processor, Memory, Storage, Network. They auto-refresh;
storage shows free space of the pool.

**Health panel** — every watched subsystem with an OK/Problem pill:
Drives, Storage pool, File sharing, Protection (firewall/intrusion/updates),
Last backup. A "Set up" button appears next to anything not configured.

**My Apps** — tiles for installed apps (Photoprism, Navidrome, …) on the
app catalog. The green dot means the container is running. **Add app** opens
the Apps page catalog.

**Recent activity** — the last 20 audit events: timestamp and `user action —
detail`. Open the full trail on [Activity Log](Activity-Log).

**Storage card** — total and used capacity of the primary pool with a
progress bar.

## Verified

- Page loads, renders the tank pool (raid1, 3 disks) and 5 healthy drives.
- Health pills reflect real state: "Attention" appears when the last backup
  pill is "Set up", otherwise "All good".
