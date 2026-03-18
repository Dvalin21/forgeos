# ElevateDB & File-Based Databases — ForgeOS Reference

## What ForgeFileDB Does

ForgeFileDB coordinates concurrent SMB access to file-based database engines. It prevents corruption by serializing conflicting writes at the inotify/OS layer — no changes to client software are needed.

**Supported engines:** ElevateDB, DBISAM, NexusDB, dBase, FoxPro, MS Access, SQLite, Firebird, Paradox, TurboDB

## ElevateDB Modes

ElevateDB applications (including Atrex inventory) operate in two modes:

### Local/File Mode (default — works with ForgeFileDB)

Client applications open `.EDB`, `.EDBT`, `.EDBI` files directly over SMB. ForgeFileDB watches for file open/close/write events and serializes conflicting writes.

**Setup:**
```bash
# Create a share with all oplocks disabled
forgeos-samba create myapp /srv/nas/myapp elevatedb yes @users

# Map network drive on Windows to \\forgeos\myapp
# Open the .EDB catalog file from the mapped drive
```

### Remote/Client-Server Mode (requires ElevateDB Server license)

A single ElevateDB Server process manages all file I/O. Clients connect via TCP. This is the architecturally correct solution for 50+ concurrent users but requires purchasing ElevateDB Server from Elevate Software.

ForgeOS does not provide an ElevateDB Server implementation — the wire protocol is proprietary and undocumented.

## Why Oplocks Must Be Disabled

When SMB oplocks are enabled, the OS grants clients permission to cache file reads locally. If Client A has an oplock on `customers.edbt` and writes a record, that write sits in Client A's local cache. Client B then reads `customers.edbt` and gets stale data from the server. When Client A flushes, both writes may interleave incorrectly, corrupting indexes.

The `elevatedb` Samba share template disables all four forms of oplock caching:

```ini
oplocks = no
level2 oplocks = no
kernel oplocks = no
strict locking = no
aio read size = 1
aio write size = 1
```

## Concurrent User Limits

| Configuration | Concurrent Write Users |
|---|---|
| Standard SMB share (no ForgeFileDB) | 1–2 before corruption risk |
| `elevatedb` SMB template only | ~5 |
| `elevatedb` template + ForgeFileDB | ~20–30 |
| ElevateDB Server (licensed) | 50+ |
| MariaDB migration | Unlimited |

## Auto-Detection

`forgeos-samba auto-share` detects ElevateDB file extensions and applies the correct template automatically:

```bash
forgeos-samba auto-share /srv/nas/myapp
# Detects .EDB/.EDBT/.EDBI → applies elevatedb template (oplocks disabled)
```

## ForgeFileDB Web UI

Access at `https://filedb.your-domain`:

- **Overview** — live client connections, open files, lock states
- **Databases** — all detected DB files grouped by directory
- **Snapshots** — versioned backups of each database directory
- **Restore** — point-in-time restore (in-place or to new location)
- **Settings** — snapshot frequency, retention, watch paths

## SQLite Notes

SQLite with WAL journal mode is significantly safer than other file-based databases for concurrent access. Enable WAL mode on existing SQLite files:

```bash
forgeos-db sqlite-optimize /srv/nas/myapp
# Applies: PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
```

## Migrating to MariaDB

For workloads that exceed ForgeFileDB's capacity, ForgeOS includes MariaDB. Most ElevateDB-based applications (including Atrex) support MariaDB as an alternative backend. Contact the application vendor for migration steps.

```bash
forgeos-db status             # Check MariaDB is running
forgeos-db mariadb-create mydb myuser mypassword
```
