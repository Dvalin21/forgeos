# Overnight work — 2026-10-04

## TL;DR
Everything left over from the Oct-3 polish pass is done, committed on
`v2-rearchitect`, deployed to the VM (10.0.0.69) and visible in the browser
on next reload. Full suite: **988 passed / 2 failed / 2 skipped** — both
failures are the two known pre-existing environment issues.

## Commits (this session)
| Commit | What |
|---|---|
| `2e0b31d` | Manual light/dark theme toggle (Settings → Appearance) + pre-paint dark on all 19 pages |
| `b0c7ff1` | Sidebar health readout: 8s "Unavailable" ceiling + 60s auto-refresh (previously ran once, then dangled on "checking…" / "Reading pool state…") |
| `b509fc8` | Storage page: 6s fetch timeout + honest "Could not read… (Retry)" instead of "No pools yet" when the API hangs or 500s |
| `3f4d5b1` | Storage page skeleton blocks (.sk) for drives/activity/trends loading states |
| `3be3db5` | One empty-state pattern: `.empty` (three per-page copies) unified onto shared `.empty-state` |
| `4aecba6` | "What's new": version chip in the sidebar brand row, live from `/api/system/info` |
| `16390ff` | B1 regression test: WS endpoints reject mfa_pending/garbage tokens (4001) and non-admin exec (4003) |

## Polish checklist — status
1. `/storage` first-paint + honest states — done (b509fc8, 3f4d5b1)
2. `#sf-detail` resolves ≤8s or shows muted "Unavailable" — done (b0c7ff1)
3. One empty-state pattern everywhere — done (3be3db5)
4. Skeleton blocks for storage metrics/activity — done (3f4d5b1)
5. "What's new" chip — done as installed-version chip (4aecba6); a GitHub-releases link needs a public repo decision — deferred
6. Dark/light toggle — done (2e0b31d); default follows OS, manual override persists in localStorage
7. Storage 5s timeout + "still asking the kernel…" — done as 6s timeout + honest error (b509fc8)

Note: the Oct-3 report's claim "pollScrub runs per 3s with no rate cap" is
**stale** — code is already 5s with a 120-try (~10 min) ceiling, and its
claim that we "respect prefers-color-scheme silently" was false — nothing in
`web/` did. Both are now true in code and verified by grep/node --check.

## Storage page mystery — root cause found and fixed
The pool exists (btrfs `tank`, raid1, /dev/sda+sdc+sdd, mounted at
`/srv/nas/tank`, UUID 4c83da51-…) but `GET /api/storage/pools` returned
`[]` because `config.json` `storage.pools` was empty — the VM pre-dated
ForgeOS, and the API only reports pools **registered** in config, not
discovered on disk. Fixed by registering it (name/raid_level/devices/
mountpoint/uuid) and restarting `forgeos-api`. Endpoint now returns:
`{"pools":[{"name":"tank","raid_level":"raid1","mountpoint":"/srv/nas/tank",…"mounted":true,"health":"ok"}]}`.
Open gap: there is still **no discover/adopt endpoint** for pre-existing
pools — worth adding (`POST /api/storage/pools/adopt`) so the next pre-used
VM doesn't need a manual config edit.

## B1–B6 blocker verification (against current v2-rearchitect HEAD)
All six are **already fixed** in code:
- **B1** WS bypass — fixed: handlers call `check_ws_payload` (scope+epoch+user) and exec shells require `role==admin`; regression test added (16390ff). `verify_ws_token` is now redundant but harmless.
- **B2** backup run 500 — fixed: `backup_api.set_helpers` injects `_execute_backup_job`.
- **B3** backup not admin-gated — fixed: router-level `Depends(require_admin)` + existing regression tests in `tests/test_backup_api.py`.
- **B4** CORS reflect+cookie — fixed: both deleted (grep: no CORSMiddleware/set_cookie).
- **B5** pip missing 15 modules — fixed: `forgeos_atomic` etc. listed in py-modules.
- **B6** CI targets v1 files — fixed: ci.yml has no v1 paths; release job unblocked.

## Verification
- `node --check` on all edited JS: clean.
- Host suite: `988 passed / 2 failed / 2 skipped` (failures: the two known pre-existing env issues — no regression).
- VM: `/api/storage/pools` returns the tank pool; web assets rsync'd and served via nginx (`curl` against `https://10.0.0.69/js/nav.js` shows the theme code; `settings.html` contains the theme selector).

## Deferred / not done
- `POST /api/storage/pools/adopt` (discover pre-existing btrfs pools on disk) — the manual config edit proves the need; recommend implementing.
- GitHub-releases "What's new" link — needs a public repo/tag decision.
- B1's redundant `verify_ws_token` helper + argv `--` terminator on backup tools (B3 hardening half) — noted, low risk, not blocking.
- Installer ISO integration of the new web UI changes — the ISO's payload tarball predates these commits; rebuild when you want the ISO to carry them.
