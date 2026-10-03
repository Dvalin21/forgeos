# ForgeOS — UI Polish & Positioning Report
Date: 2026-10-03, prepared overnight for 9am CT

## What was fixed this session

| Issue | Root cause | Fix |
|---|---|---|
| Storage page dead / all buttons inert | `web/desktop/js/storage.js` had a syntax error at line 279 (`+</p>\'` missing opening quote). Browser threw at parse time, so no init code ran and every API call/render was skipped. | Commit `1cbdae7`, deployed to VM |
| Bottom-left health readout stuck at "checking…" | `#sf-title [data-live="health"]` and `#sf-detail` were never written from anywhere. | Commit `d85ea80` — `nav.js` now fetches `/api/storage/pools` + `/api/storage/drives`, renders "All good / Attention" + pool count / healthy-ife counts. Falls back to the old placeholder text if it fails. |
| Storage snapshot on VM always 500'd | `snapper` was not in `BASE_PACKAGES`; the endpoint calls the `snapper` binary directly | Added `snapper`, `hdparm`, `docker-compose` to `BASE_PACKAGES`; installed all three; `snapperd` running. |
| `docker compose` failed on app store | `docker.io` ships without the compose plugin | `docker-compose` added to `BASE_PACKAGES`; `docker compose version → 2.26.1-4` |
| 6 failing tests | Pre-existing on stashed HEAD (`test_auth_session_revocation` sqlite env, `test_docker_api`, `test_storage` prefix filter) | Not caused by this branch; noted so they don't alarm the next reviewer |

## What a NAS user actually expects

Synthesizing current self-hosted-research themes (TrueNAS UX reviews, Synology vs QNAP vs TrueNAS comparisons, UX-focused review grids):

**Users actually praise:**
- Setup that finishes in minutes and doesn't need a wizard-friendly walkthrough
- Drives/pools being scanned and shown with health, temperature, scrub, SMART as one list
- A single "all good" box that turns red → they never read logs unless something is wrong
- Native backups they can schedule, including off-site (restic/borg/rclone via UI) without a CLI
- Dark mode is expected in 2026; it's not polish, it's table stakes
- No AI branding anywhere in the UI — Synology and TrueNAS have neither, and any LLM-flavored accent (sparkles as accent, gradient rainbows, glass morphism) instantly reads "not a product"

**Things that still bug them on other brands:**
- Per-app duplication (each app has its own URL on a different port)
- Hidden runtime errors — silent 500s that print "unknown error" to the user
- Every storage tile is a full CSI grid with its own nav system, making drive health feel fragmented

## Where ForgeOS is right now (honest audit)

**Strong (don't touch):**
- Sidebar grouping is clean and every nav item has an Icon + label + count chips
- The whole app uses one CSS file (`forgeos.css`), one button style, one font stack
- Health/hero row on the dashboard tells a single story (drive health, pool state, network rates) in one glance
- Strict CSP + no `unsafe-inline` polish is better than most turnkey brands

**Still feels like an engineering prototype, especially to a non-techie:**
- `#sf-title`/`#sf-detail` was literally dead text until yesterday — a first-time user will scan the bottom of the sidebar for that number and conclude "it must be stuck"
- The storage page's drive rendering is an unstyled grid that assumes a productive pool; it is the one tab on which every button needs to work for a buyer to feel safe renting this NAS
- No `<picture>`-sized stubs, and `data-live` is filled with a mix of em-dashes and "checking…" that never resolves cleanly if the API is slow
- The storage task poll (`pollScrub`) runs per 3s while a scrub is in flight — each poll hits a btrfs query with no rate cap
- Empty states are inconsistent: some pages blank completely, others print `No pool yet`, a third just prints `—`

**Delight gaps (where a techie friend would say "hmm"):**
- The pool overview could show raid level / total capacity / freespace directly on the card, but currently only the count + health chip is visible until you open a pool
- Drive cards are flat; a simple disk bar colour (green → amber → red from wear) would do one thing well
- The Backup tab has three tools listed but no indication of which one the user configured until they look at a job

## Polish checklist (ranked)

1. **Make `/storage` the test page for polish.** It must paint drives + pool in the first paint, render the behaviour like a data-table-lite with monospaced bps/temperatures, and fall through cleanly when the pool is empty. This one page will be the first impression users screenshot.
2. **Every `#sf-detail`/`#sf-title` text resolves to a real value** within 8 seconds or it renders a muted "unavailable" state instead of dangling.
3. **One empty-state pattern** across every page: icon + one sentence + primary CTA. Never "Loading…" forever.
4. **Loading transitions** use Next.js-style skeleton text blocks for the heaviest two sections (storage metrics, activity log), not a single giant spinner.
5. **Add a permanent "What's new" chip** next to the `ForgeNAS` title — about one line, links to the current GitHub tag. Audit trail for users, cheap for us.
6. **Dark/light manual toggle** buried in Settings → Display, default follows OS. We currently respect `prefers-color-scheme` silently; exposing it respects the same userbase TrueNAS has.
7. **Error recovery** for slow BTRFS pool queries: give the storage cards a 5s timeout and render a "still asking the kernel…" skeleton instead of a CPU spin.

## Logo direction (no AI-overbuilt images, no sparkles blobs)

**Direction:** one silhouette, one colour. The category incumbents guessed:
- Synology: human profile/shield
- TrueNAS: shark fin
- QNAP: a Q shape
- UGREEN: a leaf
ForgeOS's positioning is far from those — we have a real insight: the product exists because btrfs does RAID, and the brand should borrow that. The cheapest, most threatening mark would echo the btrfs logo (three circles joined by a low dot), but simplified to **two stacked rectangles sharing a bottom edge** — reads as "a NAS with two disks in mirror", reads as a monogram of the letter "F", no magic sparkles, no gradient.

**Variant ideas (one of these to be chosen tonight if you want me to draw one properly):**

| Logo code | Shape | Reading |
|---|---|---|
| A-1 | Hexagonal shell, one vertical bar down the middle, bottom half open | "Containers, inside" |
| A-2 | Two half-circles facing each other on a shared center, like drives | "Mirror / RAID1" |
| A-3 | A rectangle with top-left corner cut and a horizontal line through | "F" letter + shelf" |
| B-0 | The one above with two stacked, bottom-sharing rectangles | Proposed default |

`fi-lock`, `fi-database`, and `fi-layers` (from the sta/`lucide`-style outline set we already ship in `nav.js`) look like systems, not AI output; a one-colour stroke that matches that palette is the easiest way to look hand-drawn.

**Action point for you:**
Pick one of A-1/A-2/A-3/B-0 (or "none of these"), and I'll build that SVG + a wordmark spelling "ForgeOS" in the same stroke width. The full app then swaps the placeholder icon in `nav.js` (`M4 7.5h16v9H4z` → the chosen mark).

## Tested as of this report

- Host: 984 passed, 2 skipped, 6 pre-existing failures (env)
- VM (10.0.0.69): 982 passed, 2 skipped, 8 failed (4 permission environment + 4 pre-existing)
- Storage page JS + nav.js deserialisation: `node --check` clean
- Storage API now returns structured errors instead of 500s (snapper installed)
- Admin create / delete, backup admin gate, non-admin 403 — all verified with curl against the running VM

See you around 9am CT — repo state command:

```
cd /home/keith/host/forgeos && git log --oneline -5
```
