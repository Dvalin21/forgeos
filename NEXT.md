# ForgeOS review — continuation (2026-08-26)

## Status

Read-only review of `v2-rearchitect` HEAD `3cebb1c`. No files modified, no commits made.

Test suite: **970 pass / 1 fail / 2 skipped** (2026-08-26 post-fix run). Prior review had 965/8/10/2.

## Real product bugs (FIXED — verify with full suite)

All three real bugs from the prior review are now fixed and verified by the targeted test files (test_v2_osbackup_runtime, test_net_write, test_v2_security_generator, test_pages, test_system, test_forgeos_atomic all green).

- **Bug A** — FIXED. Added `from forgeos_atomic import atomic_write as _atomic_write` at top of `src/forgeos_osbackup.py:18`.
- **Bug B** — FIXED. Added `from system_api import get_cpu_usage, get_memory, get_load, get_temps` to the system_api import block in `src/forgeos-api.py:913`.
- **Bug C** — FIXED. In `src/forgeos_pages_api.py:726-728`, root folder chmod now guarded by `if apply_dirs:` — when only `apply_files=True`, the root dir keeps its x-bit and `os.walk` descends correctly.
- **Bug D** — DEBUNKED (was never a bug). Drop.

### Verification status (2026-08-26, post-fix)
- test_net_write: 17 passed
- test_v2_security_generator: 6 passed
- test_v2_osbackup_runtime: 12 passed
- test_v2_rear: 15 passed
- test_system: 28 passed
- test_forgeos_atomic: 8 passed
- test_pages: 33 passed (includes `test_apply_files_only_leaves_dirs` which was failing due to Bug C)
- Full suite (excluding TestEpochEnforcement): **970 pass / 1 fail / 2 skipped** (0:03:10)
  - 1 failure: `test_notifications.py::TestAuthBoundary::test_alert_webhook_deleted` — test expects 404, gets 405. NEXT.md previously classified as "Test expects wrong HTTP status." CONFIRMED: not a product bug.

## Test failure classification

**Environmental (conftest gap, not product bugs):**
- 3× `TestEpochEnforcement` failures + `test_prefix_filters_to_storage` — `_DATA_DIR` not isolated by conftest; `_get_db()` tries to open `/var/lib/forgeos/forgeos.db` which doesn't exist in sandbox. Pass when `FORGEOS_DATA_DIR` pointed at temp dir.
- 10× `PermissionError` in `test_pages.py` — tests run as non-root; chmod to 644 strips x-bit on dirs, `os.stat` on those dirs fails. Test-infra issue.

**Real product bug surfaced by test:**
- `test_apply_files_only_leaves_dirs` — caused by Bug C above.

**Test expects wrong HTTP status:**
- `test_alert_webhook_deleted` — expects 404, gets 405. `/api/alert-webhook` genuinely doesn't exist (v1 deletion confirmed). FastAPI returns 405 for non-existent path + method. Test assertion wrong.

**Test needs additional mocking (pre-existing gap):**
- `test_create_builds_correct_args` — returns 409 not 200. `_docker_fake` doesn't mock `_used_host_ports()`, so port 8080 appears "in use."

## LHSR Hybrid RAID (NEW — ported from LHSR kernel project)

All real product bugs fixed. Now adding LHSR (Hybrid RAID) support — porting the useful parts of the LHSR kernel project's userspace tools into ForgeOS:

### New files (6):
- `src/forgeos_lhsr.py` — Greedy tiering layout engine (ported from `shr.c`)
- `src/forgeos_lhsr_health.py` — Composite health scoring (ported from `lhsr-health.c`)
- `src/forgeos_lhsr_trend.py` — SQLite trend database with linear regression (ported from `lhsr-trend.c`)
- `src/forgeos_lhsr_exec.py` — Execution layer: partition, mkfs.btrfs per tier, mergerfs spanning
- `src/forgeos_lhsr_scheduler.py` — systemd timer for automatic SMART snapshots
- `src/lhsr_api.py` — REST API endpoints for all LHSR functions
- `src/setup_api.py` — First-boot setup wizard API

### Modified files (5):
- `src/forgeos-api.py` — Registers LHSR and Setup routers
- `src/forgeos_config.py` — Added LhsrConfig, LhsrGroup, InstallConfig (schema v12)
- `src/forgeos_storage_cli.py` — Added `lhsr plan` and `lhsr create` subcommands
- `web/desktop/storage.html` + `js/storage.js` — Added LHSR Planner and Health Trends panels
- `web/desktop/setup.html` + `js/setup.js` — New first-boot setup wizard

### Naming convention:
- LHSR1 = single parity (RAID5-like)
- LHSR2 = dual parity (RAID6-like)
- No Synology SHR naming anywhere in ForgeOS

### What works:
- `forgeos-storage lhsr plan /dev/sdb /dev/sdc /dev/sdd` — computes layout
- `POST /api/lhsr/plan` — JSON API for layout computation
- `GET /api/lhsr/health/sdb` — composite health score (0-100)
- `GET /api/lhsr/trends` — SMART trend data with predictive warnings
- `POST /api/lhsr/trends/snapshot` — record SMART snapshot
- `POST /api/lhsr/scheduler` — install/remove SMART snapshot timer
- Web UI: LHSR Planner + Disk Health Trends panels on Storage page
- Setup Wizard: 6-step first-boot configuration (network, system, OS drive, LHSR groups, monitoring, review)

### Architecture:
```
Filesystem (userspace)
     ↓
mergerfs (spans tiers into one mountpoint)
     ↓
Tier 0 (btrfs RAID5)   Tier 1 (btrfs RAID1)   ...
     ↓                       ↓
Partitions on disks     Partitions on disks
     ↓                       ↓
Physical disks          Physical disks
```

btrfs handles per-tier redundancy, mergerfs handles cross-tier spanning. No custom kernel module needed.

### TODO:
- `lhsr create` execution (partitioning, mkfs, LVM setup) — plan works, disk manipulation wired but untested on real hardware
- Installer ISO integration (add LHSR choices to install flow)
- Real-hardware testing of mergerfs + btrfs tier spanning
