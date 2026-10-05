# Data Connect

`/data-connect.html`. Registers database directories / servers so several
client apps can share them safely.

## Broadcast

When on, the NAS announces itself on the local network (mDNS) so client
apps discover it without typing an IP. Toggle off if you don't want
discovery.

## Databases

Each registered database shows its directory path and the app that owns it.

- **Add server database** — register a Postgres/MySQL server (host, port,
  credentials).
- **Import database** — register a file-based database directory (SQLite,
  Access, etc.) so it can be served and protected as one unit.

## Verified

- Broadcast toggle is on; empty database list renders with guidance text.
