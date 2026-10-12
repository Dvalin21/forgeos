# ForgeOS — NEXT (updated 2026-10-12)

## HEAD

Branch `v2-rearchitect` @ `8ac5c79`. **Working tree has uncommitted work (see below).**
Detail: `PRODUCTION_REVIEW.md` (verdict: NOT PRODUCTION READY, 5.5/10).

## Uncommitted work (2026-10-12 session) — NOT yet on the VM

Suite: **1026 pass / 6 fail / 2 skip**. The 6 failures are the pre-existing
environmental ones (unchanged, all test-infra, zero product bugs):

- `tests/test_auth_session_revocation.py::TestEpochEnforcement` ×3 — conftest `_DATA_DIR` not isolated
- `tests/test_auth_session_revocation.py::TestChangePasswordRevokesSessions` ×1 — same cause
- `tests/test_storage.py::TestAuditPrefixFilter::test_prefix_filters_to_storage` — same cause
- `tests/test_docker_api.py::TestRun::test_create_builds_correct_args` — `_used_host_ports()` not mocked

### Deployed to the VM — FULLY verified 2026-10-12 (afternoon)

Backup: `/opt/forgeos.bak-20261012`. Python `py_compile` pre-flight on the box
before install. `forgeos-api` active, `/health` ok, journal clean.
Local suite: **1031 pass / 6 fail (all pre-existing) / 2 skip**.

Verified live on 10.0.0.69:
- `GET /api/storage/scrub-schedule` → 200 with `last_scrub` derived from the
  audit log
- `POST /api/docker/wipe` → `invalid container: ''` = docker_lxc's handler
  serves, so the shadowing fix is live
- notification posted → API restarted → **SURVIVED**
- `POST /api/storage/scrub-schedule {"enabled":true,"schedule":"weekly"}` → 200,
  timer active, `list-timers` shows **Sun 2026-10-18 02:30 CDT**
- `forgeos-storage scrub run` as root → `tank: clean`; `btrfs scrub status`
  confirms a REAL scrub (`Status: finished`, `Error summary: no errors found`,
  704 KiB — the pool really is nearly empty, so 0.5s is honest, not a no-op)
- after that run the audit row appeared and `last_scrub` moved to the
  scheduled timestamp — the whole schedule→run→record→display chain works
- Storage page: 2 collapsed `<details>`, `#scrub-status`, `health.js` tag,
  `ForgeScrubTray` + `loadingWatchdog` in nav.js, `health.js` present on
  index/storage/shares

**The VM is now left with scrub scheduling ENABLED (weekly).** One click in the
Storage page turns it off.

#### Bugs the hardware found that the tests did not

1. **API could not install its own timer.** `ProtectSystem=strict` makes
   `/etc/systemd/system` read-only and the allowlist didn't cover it. Fixed the
   way this codebase already handles `/etc/resolv.conf` + `/etc/hostname`: a
   narrow per-FILE `ReadWritePaths` carve-out in
   `install/v2/forgeos_install.py:144` (plus the LHSR snapshot pair — same
   latent bug). Traps baked into `/tmp/vm_fix_units.sh`: the unit files must
   exist BEFORE the restart or a `-` entry for a missing path never becomes
   writable (the documented "dbserver bug"), and on installed boxes the live
   unit must be patched by hand.
2. **Console scripts don't run `/opt/forgeos`.** They import from
   `/usr/local/lib/python3.13/dist-packages`, so the deployed
   `forgeos-storage scrub run` was unreachable and the Sunday timer would have
   failed. **An upgrade must reinstall the package, not just copy files.**
3. **The scheduled runner's default audit was a no-op lambda** — a real scrub
   ran, reported clean, and recorded nothing, so "last checked" would have
   stayed frozen at the last manual scrub. Now writes to `audit_log` directly
   (`forgeos_scrub._default_audit`); pinned by `TestDefaultAudit`, which uses
   the DEFAULT runner instead of an injected fake.

### Shipped-in-tree

1. **Docker route shadowing fixed.** `forgeos_pages_api.py` defined
   `/api/docker/{wipe,update-check,run}` a second time; docker_lxc's copies
   were the ones serving. Dead duplicates deleted (3 handlers). Proven by the
   distinct 400 text (`invalid container: ''` vs `Invalid container name`).
   Pinned by `TestRouteOwnership`.
   NOTE: `POST /api/docker/update` (pages) is NOT shadowed and is called by
   nothing — live but dead. Delete or wire it (operator call).
2. **One storage-health truth.** New `web/desktop/js/health.js`, consumed by
   `nav.js` + `js/index.js` + `storage.js`, loaded on all 19 pages. Fixes a
   live contradiction: the sidebar counted a drive with no SMART reading as
   healthy while the dashboard counted it failed.
3. **Scheduled data scrub.** `ScrubConfig` (schema v12→v13), `forgeos_scrub.py`
   (ReaR-timer shape), `forgeos-storage scrub run|schedule`, GET/POST
   `/api/storage/scrub-schedule`, cost-explaining confirm modal with a
   schedule alternative, ambient sidebar tray, "last scrubbed" derived from the
   audit log. 22 tests.
4. **`lhsr_exec` landmine defused.** It unmounted every tier BEFORE handing the
   tier mountpoints to mergerfs (span built over empty dirs, tier data
   unreachable); `force` was read by nothing so nothing stood between a
   mistyped device / the system disk and `sgdisk --zap-all`; fstab appended
   non-idempotently. Fixed + 7 tests (the mount-order test was verified to
   FAIL against the old code).
5. **SMART as plain words** (Healthy/Degraded/Crashed + sentence), DSM
   vocabulary, raw smartctl still one click away.
6. **Loading watchdog** — 16 static "Loading…" placeholders now degrade to an
   honest "Could not load this — the API did not answer. Try again" instead of
   lying forever. One watchdog in nav.js, not 16 edits.
7. **Notifications persist** to SQLite and survive an API restart (was a
   module-level deque). Rules/routing centre deliberately deferred.
8. **Storage page collapsed** — LHSR Planner + Disk Health Trends are now
   `<details>`; the page reads short for a non-techie.

### Blocked
- **Version chip → release notes** needs the public-repo decision (GitHub URL
  would 404 otherwise). Not implemented, on purpose.

## Next

1. **Decide the push.** Nothing is committed. Working tree = 3 fixes + 5
   features + 41 new tests, all VM-verified. Suggested split (one fault per
   commit, rules say):
   - `fix(mcp): drop duplicate docker routes shadowed by docker_lxc_api`
   - `feat(storage): scheduled btrfs scrub (config v13, timer, API, UI)`
   - `fix(installer): allow the API to write its own timer units`
   - `feat(ui): one storage-health verdict, plain-words SMART, honest loading`
   - `fix(lhsr): do not unmount tiers before mergerfs; guard destructive exec`
   - `feat(ui): collapsible storage panels; notifications persist`
2. Hardware verification on real iron (installer, LHSR exec on real disks,
   WireGuard, backup restore, mDNS).
3. **V-022 can be closed** — v1 bash installer was deleted in `a3f55c4`;
   `PRODUCTION_REVIEW.md:45` and `PRODUCTION_READINESS.md:394` still list it
   OPEN and are wrong.
4. **V-012 is smaller than recorded** — `forgeos_config.load()` already
   migrates in-memory (`forgeos_config.py:1031`); only the persist-back is
   missing and only `forgeos-generate` calls `load_and_upgrade()`. Re-grade it.
5. Decide `POST /api/docker/update` (pages) — live, uncalled, shadow-free.
6. `POST /api/storage/drive/fail` is a 409 stub behind a UI button.
7. conftest `_DATA_DIR` isolation (fixes 5 of the 6 failures), then the docker
   `_used_host_ports()` mock.

## Known gap class found 2026-10-12 — backend with no UI

Audited every route against every `web/desktop/js/*.js` call. Real gaps (the
capability exists in the API, nothing in the UI can reach it):

- **LXC**: only the container LIST is called. start/stop/restart/destroy/
  snapshot/exec/info are unreachable, and **there is no create endpoint at all**
  — LXC containers cannot be created through ForgeOS by any route.
- **Docker Compose**: up/down/start/stop/restart/pull/build, compose-file
  GET/PUT, services, logs, project CRUD — all unreachable.
- **Docker images**: list + delete unreachable.
- **RustFS/S3** (`rustfs_api.py`, 11 endpoints): entirely unreachable (the Apps
  page only edits a config.yaml textarea).
- **NFS**: config + generator exist, zero UI, no wiki page.
- **LHSR health** per-device, **Snapper snapshot list**, `/api/storage/drive/fail`.

## Prior checkpoint

`git show 379c362 -- NEXT.md` (2026-08-26: Bugs A–C fixed, LHSR ported, 970/1/2).
Superseded by `PRODUCTION_REVIEW.md` 2026-10-06 (989/6/2).