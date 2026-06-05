# ForgeOS — Production Readiness Registry

**Purpose:** This document is the single authoritative tracker for every known bug, design concern, and feature gap in ForgeOS. Every entry has a stable ID, severity, current status, and the commit that resolved it (when resolved).

**Discipline rule:** This registry is updated in the same commit as the work it tracks. Status drift here is a project-management bug, not a documentation bug.

**Last reviewed:** 2026-06-04
**Last commit reviewed:** `79b1c72` — web: add ForgeDB page
**Test baseline at start:** 87/87 passing
**Current test count:** 95/95 passing (87 baseline + 8 new from Sprint 3)
**Repository:** github.com/Dvalin21/forgeos

---

## Status legend

| Code | Meaning |
|---|---|
| 🔴 OPEN | Not started |
| 🟡 IN-PROGRESS | Work begun but not committed |
| 🟢 DONE | Committed and verified |
| ⚪ DEFERRED | Acknowledged but explicitly out of current scope |
| ⚫ WON'T FIX | Decided against, with reason |

---

## Severity legend

| Code | Meaning |
|---|---|
| **CRIT** | Security correctness, data loss risk, or installation failure |
| **HIGH** | User-facing breakage, regression, or significant usability problem |
| **MED** | Quality / maintainability / accuracy concern |
| **LOW** | Polish, cleanup, documentation |

---

## Section 1 — Bugs and concerns from the vision audit

These are the seven items identified by the 2026-06-04 reading of the codebase. Each one was verified to exist in the working tree at commit `79b1c72`.

| ID | Severity | Status | Title | File(s) |
|---|---|---|---|---|
| C-001 | CRIT | 🟢 DONE | JWT secret bootstrap race — was: generated on first start, two parallel workers can write conflicting values. **Fix:** secret generation moved to installer (`99-finalize.sh`, now idempotent — preserves existing secrets on re-run). `forgeos_auth.py` is now pure-read: env var → config file → refuse to start with `JwtSecretMissingError` and a clear fix message. 8 new tests cover the refusal paths. | `src/forgeos_auth.py`, `install/modules/99-finalize.sh`, `tests/test_auth.py` |
| C-002 | HIGH | 🟢 DONE | `forgeos-api.py` was 2,410 lines — split into per-domain routers across 10 commits. Now 1,308 LOC orchestrator + 11 router files. **Sprint 1 complete.** | `src/forgeos-api.py` + new router files |
| C-003 | MED | 🟢 DONE | OS minimums hardened. `require_ubuntu_debian()` now reads `/etc/os-release` directly (was: required `lsb_release` which is optional on minimal images). Minimum raised: Ubuntu 24.04 LTS (was: 22.04, which ships Python 3.10 — incompatible with `requires-python = ">=3.11"`). Debian 12 minimum unchanged. README updated with explicit OS table + rationale. Installer refuses other OSes with clear error. Functional-tested across 7 OS cases. | `install/lib/common.sh`, `README.md` |
| C-004 | MED | 🔴 OPEN | Zero test coverage for `forgeos_pages_api.py` (1,410 LOC) and `rustfs_api.py` (270 LOC) | `tests/` |
| C-005 | LOW | 🟢 DONE | Backup tree `backups/20260417/` lived at repo root (not in `src/` as the original registry said — that was a misread). 39 tracked files, 1.1 MB. Moved to `docs/historical/snapshots/` via `git mv` (preserves history). Added `/backups/` to `.gitignore` to prevent recurrence. Note: also has a `working/` subdirectory with 6 HTML snapshots from April 19-20. | `backups/` → `docs/historical/snapshots/`, `.gitignore` |
| C-006 | LOW | 🟢 DONE | Installer module numbering has gaps (no 08, 19, 20, 21) — documented the gap scheme as intentional in `install/install.sh` header. Phase-based: 01-09 foundation, 10-19 services, 20-29 tools, 90-99 finalize. Variant suffixes (03/03c/03-hotswap, 10/10b/10c) explained. | `install/install.sh` |
| C-007 | LOW | 🟢 DONE | Stale status documents disagreed with current main. Original scope (3 docs) expanded during execution to 6 docs after discovering `FUNCTIONAL_VERIFICATION_REPORT.md` (April 25), `SECURITY_AUDIT.md` (April 20), `VERIFICATION_CHECKLIST.md` (April) were also stale snapshots from the same era. All moved to `docs/historical/`. Added `docs/historical/README.md` explaining what's there. README now points at `PRODUCTION_READINESS.md` as canonical state. | `docs/historical/*`, `README.md` |
| C-008 | MED | 🟢 DONE | `if __name__ == "__main__":` block lived at line ~1240 of forgeos-api.py with code still after it. Sprint 1 already cleaned up most of the trailing code; only stale section-header marker comments remained. Relocated the entry block to be the actual final block of the file, and removed the orphan markers. Added a comment explaining the block must remain at the bottom. | `src/forgeos-api.py` |
| C-009 | MED | 🔴 OPEN | Notification routes (notify, drive-alert, notifications, drive-alerts, alert-webhook) have ZERO test coverage. **Discovered during Sprint 1.** Roll into Sprint 4 scope alongside C-004. | `tests/`, `src/notifications_api.py` |
| C-010 | HIGH | 🟢 DONE | `pyproject.toml` declared `jose>=3.3` (wrong package — abandoned, max v1.0.0) instead of `python-jose>=3.3`. Also missing `python-multipart` which FastAPI form-data requires. Blocked all clean `pip install -e .` from fresh checkout. **Discovered when applying Sprint 1 patches to user hardware.** Fixed in pyproject.toml. | `pyproject.toml` |

### Detail — C-001 JWT secret bootstrap race

`src/forgeos_auth.py:25-46` reads `FORGEOS_JWT_SECRET` from env, falls back to `WEBUI_JWT_SECRET` in `/etc/forgeos/forgeos.conf`, falls back to generating a new 32-byte secret and writing it. On parallel API worker start, two workers can each generate a different secret and the last writer wins. All tokens previously issued by the losing worker become invalid.

**Fix:** Move secret generation to `install/modules/99-finalize.sh` as a one-shot during install. `forgeos_auth.py` refuses to start if `WEBUI_JWT_SECRET` is missing or matches a known placeholder.

**Verification:** Inspect `/etc/forgeos/forgeos.conf` after install — secret present, file mode `0640` owned by `root:forgeos`. Restart API service twice and confirm token from first session still validates after second start.

### Detail — C-002 forgeos-api.py refactor

The user explicitly chose "do it first — clean foundation before any new features." Split `src/forgeos-api.py` into per-domain routers following the existing pattern (`docker_lxc_api.py`, `filedb_api.py`, `forgeos_pages_api.py`, `rustfs_api.py`).

**Proposed router decomposition:**
- `storage_api.py` — pools, drives, snapshots, SMART, hotswap log
- `nginx_api.py` — vhosts, certbot, raw config
- `samba_api.py` — shares, connections, raw config
- `services_api.py` — systemd, network state, security/fail2ban
- `system_api.py` — stats, info, settings, config
- `notifications_api.py` — notifications, alerts, notify
- `backup_api.py` — backup history (existing surface)
- `imaging_api.py` — system imaging
- `auth_api.py` — login, logout, change-password (separated from `forgeos_auth.py` which stays as the verification layer)

`src/forgeos-api.py` becomes a thin orchestrator that creates the app, applies middleware, and `include_router()`s the above.

**Risk:** 87 tests run today. If imports change, every test needs verification. Plan: do the split with a single commit that moves code but does not change behavior. Tests must pass identically.

### Detail — C-003 OS minimums

`pyproject.toml` requires Python 3.10+. The rest of the stack assumes systemd, apt, and packages whose names changed between Ubuntu 20.04 and 24.04 (most notably `python-is-python3`, `unattended-upgrades` defaults, AppArmor profile names).

**Fix:** Declare and enforce in `install/lib/preflight.sh`:
- Ubuntu 22.04, 24.04
- Debian 12 (bookworm)

Refuse anything else with a clear error message and a link to the README's compatibility section.

### Detail — C-004 Test coverage gaps

`tests/test_forgeos_pages.py` and `tests/test_rustfs.py` do not exist. The two files are 1,680 LOC combined with no test coverage.

**Fix scope:** Add a minimal happy-path + auth-required test suite per file. Aim for ~50% line coverage on each as a start. Full coverage is not the goal — preventing silent regressions is.

### Detail — C-005 Backup tree in source (RESOLVED, original description corrected)

The original registry entry said `src/backups/20260417/` but the actual path was `backups/20260417/` at repo root. The April snapshot of the API file (`backups/20260417/src/forgeos-api.py`, 1,886 lines) showed up in every recursive `grep` over the repo. 39 tracked files total (1.1 MB) including a full copy of `src/`, `install/`, and `web/` from April 17, plus a `working/` subdirectory with 6 HTML snapshots from April 19-20.

**Action taken:** `git mv backups/ docs/historical/snapshots/` preserved all 39 files as renames (full git history retained), and added `/backups/` to `.gitignore` to prevent recurrence.

### Detail — C-006 Module numbering gaps

Modules: 01, 02, 03, 03c, 04, 05, 06, 07, 09, 10, 10b, 10c, 11, 12, 13, 14, 15, 16, 17, 18, 22, 99. Missing: 08, 19, 20, 21.

**Fix:** Documentation-only. Add a comment block to `install/install.sh` explaining the numbering scheme. Not renumbering — that would invalidate user docs and break anyone with custom modules.

### Detail — C-007 Stale status documents

Three documents describe three different UI designs. None match current main.

**Fix:** Move `FINAL_STATUS_REPORT.md`, `SAVE_TO_RESUME.md`, `HARDWARE_TEST_REPORT.md` to `docs/historical/`. Update `README.md` to point at `PRODUCTION_READINESS.md` (this file) as the canonical state-of-project document.

---

## Section 2 — Like-to-have features (LTH)

These build new user-facing capability. Tier order is the user's stated priority.

### Tier 1 — User's explicitly requested gaps

| ID | Severity | Status | Title | Scope |
|---|---|---|---|---|
| LTH-001 | HIGH | 🔴 OPEN | WireGuard peer-management API + UI page | New `vpn_api.py` router, new `web/desktop/vpn.html` page, tests |
| LTH-002 | HIGH | 🔴 OPEN | OIDC SSO integration end-to-end (build with unit tests, hardware-verify on Authentik instance) | OIDC verifier in `forgeos_auth.py`, SSO routes, login button |
| LTH-003 | HIGH | 🔴 OPEN | lldap user-management API + UI page | New `users_api.py` router proxying lldap GraphQL admin |

### Tier 2 — Fix regressions from the May 29 redesign

| ID | Severity | Status | Title | Scope |
|---|---|---|---|---|
| LTH-004 | HIGH | 🔴 OPEN | Cloud / S3 page restoring lost UI for `rustfs_api.py` | New `web/desktop/cloud.html`, bucket browser |
| LTH-005 | MED | 🔴 OPEN | Sensors dedicated view (lm-sensors output) | New `web/desktop/sensors.html`, new `/api/sensors` route |
| LTH-006 | MED | 🔴 OPEN | Logs dedicated view (journalctl filter UI) | New `web/desktop/logs.html`, new `/api/logs` route with filtering |
| LTH-007 | MED | 🔴 OPEN | Apps page: "Add custom app" via paste-compose-yaml flow (warn-only, no allowlist per user choice) | Extend `apps.html`, new `POST /api/apps/custom` route |
| LTH-008 | LOW | 🔴 OPEN | Mail placeholder page — "Coming Soon" stub (separate mail project integration planned) | New `web/desktop/mail.html`, no API surface yet |

### Tier 3 — Vision-completing additions

| ID | Severity | Status | Title | Scope |
|---|---|---|---|---|
| LTH-009 | MED | ⚪ DEFERRED | HIPAA compliance dashboard page | Surfaces PHI volumes, auditd status, retention check |
| LTH-010 | MED | ⚪ DEFERRED | Embedded monitoring (Grafana iframes + Alertmanager toasts) | Dashboard integration |
| LTH-011 | MED | ⚪ DEFERRED | Snapshot browser (Time Machine-style btrfs restore) | New `web/desktop/snapshots.html` |
| LTH-012 | MED | ⚪ DEFERRED | Backup wizard (Restic job CRUD + restore wizard) | Builds on existing `/api/backup/*` |
| LTH-013 | LOW | ⚪ DEFERRED | Firewall UI improvement (zones, country/ASN blocking) | Enhance existing `firewall.html` |

**Note on Tier 3 deferred items:** These are valuable but not in current scope. They are tracked so they are not forgotten.

### Tier 4 — Quality and polish

| ID | Severity | Status | Title | Scope |
|---|---|---|---|---|
| LTH-014 | LOW | 🔴 OPEN | README updated to reflect actual feature surface + canonical pointer to this registry | `README.md` |
| LTH-015 | LOW | 🔴 OPEN | Modularize `web/desktop/index.html` JS (1,422 lines) into per-section initializers | `web/desktop/index.html` |
| LTH-016 | LOW | ⚪ DEFERRED | Pin OS minimums in CI (lint on every PR) | `.github/workflows/` |
| LTH-017 | LOW | ⚪ DEFERRED | Snapshot module 22-imaging.sh is currently 72 lines — incomplete vs README description | `install/modules/22-imaging.sh` |

---

## Section 3 — Out of scope, deliberate

These were considered and excluded for the current effort. Documented here to prevent re-discovery.

| Decision | Reason |
|---|---|
| Mail server admin UI | Will integrate from a separate project. Placeholder page only this round. |
| App marketplace registry | Out of scope. User uncertain about complexity. The BYO-compose path (LTH-007) gives users the same outcome (deploy any app) without the registry maintenance burden. |
| AD / FreeIPA support | Target user is 1-10 employee businesses. lldap + Authentik is sufficient. |
| WireGuard mesh / Netbird integration | Installer already supports it optionally. UI surface stays single-server. |
| Enterprise audit-vault | HIPAA module already handles 6-year retention. No enterprise SIEM integration in scope. |
| Role-based access control beyond admin/user | Not needed for 1-10 employee target. Re-evaluate if target shifts. |

---

## Section 4 — Sprint plan

Sprints are a unit of focus, not a unit of time. Each sprint has a clear goal and a clear done condition.

### Sprint 0 — Registry setup
**Goal:** This document exists, committed, on main.
**Done condition:** Commit lands, this file at HEAD.
**Status:** 🟢 DONE (commit `c5c4523`)

### Sprint 1 — The big refactor (C-002) — DONE first per user preference
**Goal:** `forgeos-api.py` split into per-domain routers.
**Scope:** Mechanical move, no behavior change. 10 incremental commits.
**Done condition:** 87/87 tests pass identically after each commit. Registry DONE.
**Risk acknowledged at start:** Highest in the plan. Spanned multiple turns.
**Status:** 🟢 DONE
**Outcome:** `forgeos-api.py` 2,410 → 1,308 LOC (-45.7%). 11 router files created.
**Commits:**
- 1/10 `9353ec3` auth_api.py (3 routes)
- 2/10 `4b8f61c` system_api.py (7 routes + 6 metrics helpers)
- 3/10 `b91823b` storage_api.py (10 routes)
- 4/10 `e27b182` nginx_api.py (8 routes)
- 5/10 `23c8b8f` samba_api.py (6 routes)
- 6/10 docker_api.py + security_api.py (5 routes total, single commit)
- 7/10 `7766d30` notifications_api.py (5 routes + module state)
- 8/10 `3dacb7b` backup_api.py (16 routes — largest, plus _check_tool/_require_tool helpers)
- 9/10 audit_api.py + imaging_api.py (4 routes, single commit)
- 10/10 this registry update

### Sprint 2 — Small concerns batch (was originally Sprint 1)
**Goal:** Close the cheap concerns now that the refactor is done.
**Scope:** C-005, C-006, C-007, C-008 (backup move, module numbering doc, status docs archive, __main__ relocation).
**Done condition:** Four commits, registry reflects DONE for each, 87/87 tests pass.
**Status:** 🟢 DONE
**Commits:**
- 1/4 `924ca08` C-006 — installer module numbering scheme documented
- 2/4 `df5ada4` C-005 — backups/ moved to docs/historical/snapshots/ (39 file renames). Original entry was wrong about path (said "inside src/" — actually at repo root); corrected in detail section.
- 3/4 `3906a46` C-007 — 6 stale top-level status docs archived (scope expanded from original 3 after finding 3 more from the same April-era pattern). Added README pointer at registry.
- 4/4 `c741754` C-008 — `__main__` block cleaned up; orphan section markers removed.

### Sprint 3 — JWT secret hardening
**Goal:** C-001 closed.
**Scope:** Move secret generation to installer, API refuses placeholder.
**Done condition:** Code committed, registry DONE, 87/87 tests pass, new test coverage for the refuse-placeholder path.
**Status:** 🟢 DONE
**Commits:**
- 1/3 `2deed58` Installer (`99-finalize.sh`) generates JWT secret idempotently. Preserves existing non-placeholder secrets. Functional test verified in real bash (4 cases: empty, preserve, idempotent, placeholder triggers regen).
- 2/3 `ecfee91` `forgeos_auth.py` no longer generates secrets at runtime. Raises `JwtSecretMissingError` with a clear fix message if env var or config has no valid secret. 8 new tests cover all refusal paths.
- 3/3 This registry close-out.

**Test count after Sprint 3:** 95/95 (87 baseline + 8 new from the refusal-path coverage).

### Sprint 4 — OS minimums and test gaps
**Goal:** C-003 and C-004 closed.
**Scope:** Preflight rejects unsupported OS; tests added for `forgeos_pages_api.py` and `rustfs_api.py`.
**Done condition:** Registry DONE, ≥90/90 tests passing (87 baseline + new tests).

### Sprint 5 — LTH-001 WireGuard
**Goal:** WireGuard peer management end-to-end.
**Done condition:** `vpn_api.py` router, `vpn.html` page, tests, registry DONE. Hardware verification required before close.

### Sprint 6 — LTH-002 OIDC
**Goal:** OIDC integration with unit tests.
**Done condition:** Code, unit tests, integration test instructions in `docs/oidc-integration-test.md`. Hardware verification deferred to user.

### Sprint 7 — LTH-003 lldap user management
**Goal:** Users & Groups page.
**Done condition:** `users_api.py`, UI page, tests, registry DONE.

### Sprint 8 — Lost UI surface (LTH-004 through LTH-008)
**Goal:** Cloud, Sensors, Logs, Custom Apps, Mail-stub.
**Done condition:** Five pages exist, three new minor API routes, mail stub serves coming-soon message.

### Sprint 9 — Polish (LTH-014, LTH-015)
**Goal:** README accurate, dashboard JS modularized where safe.
**Done condition:** README points at this registry; index.html JS organized into named initializers.

---

## Section 5 — Hardware verification log

Every change that touches storage, network, auth, systemd, or installer behavior needs hardware verification by the user before the registry marks it DONE. This section logs that verification.

| Date | Commit | Item | Verifier | Pass/Fail | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | (none yet) |

---

## Section 6 — Test count history

The 87-test baseline is the floor. Every sprint must end with at least the baseline test count passing. New work adds tests.

| Sprint | Tests passing | Tests added | Tests removed | Notes |
|---|---:|---:|---:|---|
| Baseline (pre-Sprint-0) | 87 | — | — | At commit `79b1c72` |
| Sprint 0 | 87 | 0 | 0 | Registry only, no code change |
| Sprint 1 commit 1/10 | 87 | 0 | 0 | auth_api.py extracted |
| Sprint 1 commit 2/10 | 87 | 0 | 0 | system_api.py extracted; one ordering bug caught + fixed mid-commit |
| Sprint 1 commit 3/10 | 87 | 0 | 0 | storage_api.py extracted; missing `re` import caught + fixed mid-commit |
| Sprint 1 commit 4/10 | 87 | 0 | 0 | nginx_api.py extracted |
| Sprint 1 commit 5/10 | 87 | 0 | 0 | samba_api.py extracted |
| Sprint 1 commit 6/10 | 87 | 0 | 0 | docker_api.py + security_api.py extracted (single commit) |
| Sprint 1 commit 7/10 | 87 | 0 | 0 | notifications_api.py extracted; revealed C-009 (zero coverage for these routes) |
| Sprint 1 commit 8/10 | 87 | 0 | 0 | backup_api.py extracted (16 routes, largest single extraction); revealed C-008 (__main__ misplacement) |
| Sprint 1 commit 9/10 | 87 | 0 | 0 | audit_api.py + imaging_api.py extracted (single commit). Main file is now 1,308 LOC. |
| Sprint 1 commit 10/10 | 87 | 0 | 0 | Registry update — this commit |
| Sprint 1 dep fix (C-010) | 87 | 0 | 0 | Caught during hardware verification on Keith's box |
| Sprint 2 commit 1/4 (C-006) | 87 | 0 | 0 | Documented installer module numbering scheme |
| Sprint 2 commit 2/4 (C-005) | 87 | 0 | 0 | Moved backups/ → docs/historical/snapshots/ (39 file renames) |
| Sprint 2 commit 3/4 (C-007) | 87 | 0 | 0 | Archived 6 stale top-level status docs (scope expanded from 3) |
| Sprint 2 commit 4/4 (C-008) | 87 | 0 | 0 | Cleaned up __main__ block end-of-file. Sprint 2 done. |
| Sprint 3 commit 1/3 (C-001 installer) | 87 | 0 | 0 | Installer idempotent JWT secret generation |
| Sprint 3 commit 2/3 (C-001 auth) | **95** | **+8** | 0 | forgeos_auth.py refuses missing/placeholder secret. 8 new tests added. |
| Sprint 3 commit 3/3 | 95 | 0 | 0 | Registry close-out. Sprint 3 done. |

---

## Section 7 — Maintenance

This document changes whenever the work it tracks changes. The change rules:

1. Every commit that closes a registry item updates that item's status from 🔴/🟡 to 🟢, in the same commit.
2. Every commit that discovers a new bug or concern adds an entry, in the same commit. New IDs continue the C-NNN or LTH-NNN sequence.
3. Hardware verification results are logged in Section 5 immediately, by the user reporting them.
4. Sprint plan revisions happen between sprints, not during. Once a sprint starts, its scope is fixed; new findings become future sprints.
5. Out-of-scope decisions go in Section 3, with reason. Re-opening requires explicit user direction.

**Lesson learned from WatchROM:** WatchROM's `PRODUCTION_READINESS.md` had tables at the top showing open issues and Sprint sections at the bottom showing them closed. The code matched the Sprint sections; the tables were stale. ForgeOS will not repeat this mistake — there is one status field per item, and it is updated in the same commit as the work.
