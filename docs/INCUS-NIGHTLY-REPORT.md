# Incus integration — overnight report

Everything below was verified by running it on the test VM (10.0.0.69) against
a real Incus 6.0.4 on Debian 13 trixie. Where a claim could not be verified, it
says so.

Commits: `d6e31ea` (the work), `821a500` (tooling fixes). Nothing pushed.

---

## 1 · The finding that mattered: ufw silently breaks every container

This is the one to read first. It is not theoretical — it was reproduced,
diagnosed and fixed on the box.

**Symptom.** With the firewall at default-deny:

```
incus launch images:debian/13 forgeos-test   ->  RUNNING
incus exec forgeos-test -- echo hi           ->  works
ip -4 addr show eth0 (inside)                ->  no address, no route, no DNS
```

The container starts and is completely unreachable. Every symptom points at a
broken hypervisor. It is a broken firewall.

**Proof of cause.** `tcpdump -ni incusbr0 'udp port 67 or 68'` while the
container started:

```
23:29:02 IP 0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request ...
23:29:07 IP 0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request ...
```

DISCOVER leaves the container and reaches the bridge. **No OFFER ever comes
back.** dnsmasq is correctly bound (`UNCONN 0.0.0.0%incusbr0:67`) and the DHCP
range is configured. The reply is discarded by ufw's INPUT chain before it
reaches the container — DHCP is locally delivered, so it traverses INPUT, not
FORWARD.

**Why it compounds.** `generators/ufw.py:95` opens `apply()` with
`ufw --force reset`, which also wipes Incus's own nftables rules. So every time
anyone edits the firewall, containers break again.

**Fix.** `_incus_rules()` emits three carve-outs before `ufw enable`:
`allow in on <bridge>`, `route allow in on <bridge>`, `route allow out on
<bridge>`.

This is the **third** instance of a pattern already documented twice in that
same file. The WireGuard guard carries the comment: *"without this guard the
default-deny policy silently eats the handshake and the VPN 'runs' but no
client can ever connect."* Same words, same shape.

**Verified fixed.** After a full `ufw --force reset` + generator rebuild:

```
Anywhere on incusbr0       ALLOW       Anywhere   # ForgeOS Incus bridge incusbr0
Anywhere (v6) on incusbr0  ALLOW       Anywhere (v6)
container: 10.141.33.207, DNS resolves, TCP/443 out: connected
```

Test `test_applied_before_enable` asserts ordering — the carve-outs must land
before `ufw enable`, or every apply re-breaks the containers.

---

## 2 · The deploy that silently did nothing

`ExecStart=/usr/bin/python3 /opt/forgeos/forgeos-api.py`. That makes
`/opt/forgeos` **sys.path[0]**, so every module file sitting there overrides the
installer's `dist-packages` copy.

The box had **~30 stale duplicates plus an entire `generators/` package**
shadowing `dist-packages`. I deployed the ufw fix correctly, confirmed it by
checksum, restarted, and **nothing changed** — because the service was still
importing `/opt/forgeos/generators/ufw.py`.

Found by printing `module file:` from inside the running service rather than
assuming the deploy had landed.

**Fixed**, and now guarded:

- Removed the shadowing files (entrypoints + web tree only remain in `$APP`).
- `./scripts/vm.sh shadow` exits 1 and names every offender.
- `cmd_deploy`'s filter no longer narrows after each path — `deploy a.py b.py`
  used to report *"no manifest entry matches: b.py"*.

---

## 3 · What was built

**`src/incus_api.py`** — `/api/incus/*`. Instances are NOT in the config DB;
Incus is its own source of truth, exactly as Docker is for containers. The DB
carries only settings.

`status`, `instances` (list/get), `instances` (create), `start`, `stop`,
`restart`, `update`, `snapshot`, `exec`, `delete`.

**Hardware passes through unclamped.** The API takes what the user typed and
hands it to Incus. Tests assert `limits.memory=3GiB` reaches Incus as `3GiB`,
and that `"1; rm -rf /"` is a 400 rather than reaching argv.

**Config** — `IncusConfig{enabled, bridge, storage_pool}`, schema **v14**, with
an additive migrator. Older boxes load unchanged with Incus off.

**Frontend** — nav is now `Apps` / `Containers` / `Virtual Machines`. The old
group and item shared a name. `apps.js` no longer calls the dead
`/api/lxc/containers` endpoint.

**Editable hardware, as asked.** Presets *fill* the cpu/memory/disk inputs and
never lock them. No create-stop-edit-start dance to change a size.
`test_hardware_fields_are_editable_not_preset_locked` pins this **inside the
preset handler** — my first version was a whole-file substring check and was
fooled by the create body mentioning the same field. I verified it catches the
regression.

---

## 4 · Four real bugs in my own code, all found by tests

1. **Disk size always read "unlimited".** Incus returns `"20GiB"`; `int()` threw
   and fell through to 0. Added `_parse_size()`.
2. **Endpoints returned an async function.** `return get_instance(...)` from an
   async handler yields a coroutine FastAPI does not await. Extracted a sync
   `_instance_view()`.
3. **Missing instance returned 400, not 404.**
4. **`--instance-only`** — a flag I assumed exists. It does not exist in Incus
   6.0.4 (checked `incus launch --help`). Removed the dead code.

Two mistakes worth naming:

- I wrote `ok, _ = _run([...]), None` and a `if False else None` line before
  verifying anything. Removed both.
- A cleanup script I wrote deleted ~30 files from `/opt/forgeos` *before* its
  backup copy succeeded (no `set -e`, `rm` ran after a failed `cp`). No source
  was lost — identical modules were in `dist-packages` and the repo is
  authoritative — but the box had no backup of those files for ~10 minutes.
  The end state is the layout the installer intended.

---

## 5 · Cross-cutting conflicts found, with evidence

| # | Where | Conflict | Status |
|---|---|---|---|
| 1 | `network_api.py:60` | `_HIDE_IFACE_RE` hides `lo\|docker*\|br-*\|veth\|virbr\|wg*`. Incus bridges are `incusbr0` — **not matched**. Confirmed live: `/api/net/interfaces` returned `['ens18', 'incusbr0']`. The Network page would offer to reconfigure Incus's bridge. | **NOT FIXED** — needs `incusbr\d+` added to the regex |
| 2 | `storage_api.py:110` | `_btrfs_scan()` lists every btrfs fs; `/api/storage/unmanaged` offers adopt **or destroy (wipe)**. An Incus btrfs-backed storage pool would be offered for wiping. | Avoided in practice by using the `dir` driver; **not yet guarded** |
| 3 | `storage_api.py:499` | `_enrich_drive_roles` — an Incus disk shows as "spare" and may be offered to a ForgeOS pool. | **NOT FIXED** |
| 4 | `storage_api.py:690` | Snapper snapshots vs Incus snapshots — same user-facing word, two systems. | Cosmetic, noted |
| 5 | `forgeos_config.py:729` | ForgeOS `StoragePool` vs Incus "storage pool" — **same name, different things**. | Naming risk |
| 6 | `forgeos_health.py:18` | `DEFAULT_SERVICES` has no `incus` entry, so a downed Incus raises no alert. | **NOT FIXED** |
| 7 | nginx `forgeos-ui.conf` | `proxy_read_timeout 60s`. A VM console is idle for minutes; nginx drops it. `/ws` survives only because it transmits every 2s. | **NOT FIXED** — console needs its own location block |

---

## 6 · WebSockets — no new infrastructure needed

Checked on the live box, not assumed:

```nginx
# /etc/nginx/forgeos.d/forgeos-ui.conf
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $forgeos_connection_upgrade;
```

And the API already ships working WebSocket endpoints: `/ws` (live metrics, 2s)
and `/ws/logs`, both JWT-authenticated over `Sec-WebSocket-Protocol`.

**This is exactly Proxmox's shape** — `pveproxy` serves the UI, proxies to the
backend and handles the upgrade itself. ForgeOS was already built that way, so
Incus adds no new component.

The one real gap is #7 above: the 60s read timeout. Anything streaming must
send within a minute or nginx cuts it.

---

## 7 · State

- Suite: **1088 passed / 0 failed / 2 skipped**
- VM: api active, 0 tracebacks, incus active, 6 incusbr0 rules,
  `forgeos-test` RUNNING on `10.141.33.207` with IPv6, all endpoints 200
- Docker on the box untouched: `photoprism`, `navidrome`
- `./scripts/vm.sh check` → **IN SYNC (113 files)**; `./scripts/vm.sh shadow` → clean
- This host's 14 Docker containers untouched; mockups served from
  `/var/www/html/forgeos-incux/` on :80

---

## 8 · Recommended next steps, in order

1. **`_HIDE_IFACE_RE` + `incusbr\d+`** (conflict #1). Smallest change with the
   worst failure mode — a user editing the bridge takes down every container.
2. **A btrfs Incus pool would be offered for wiping** (conflict #2). Either
   forbid the btrfs driver in the Incus UI, or filter Incus paths out of
   `/api/storage/unmanaged`.
3. **Add `incus` to `DEFAULT_SERVICES`** so a downed hypervisor alerts.
4. **Console location block** in nginx before anyone builds a console UI.
5. **Remove or re-point `lxc_api.py`.** It still mounts at `/api/lxc` and still
   shells out to a binary Debian no longer ships. Nothing calls it now.
6. **Clean-install verification.** Every finding here came from a box with
   accumulated history. A fresh install is the only real test of the installer.
---

## 9 · Clean-install verification (2026-10-14, §8.6)

Ran the report's own last recommendation, twice, on the test box:

- deleted the `forgeos-test` container and the `default` Incus pool (the
  pool refused deletion until the default profile's root disk device was
  removed — `used_by: /1.0/profiles/default`)
- stopped and disabled forgeos-api / incus / scrub timer, unmounted
  `/srv/nas/tank` and `/mnt/backup`, cleaned their fstab entries
- wiped `/dev/sda /dev/sdb /dev/sdc /dev/sdd` (wipefs -a + sgdisk --zap-all
  + 4 MiB zero). `/dev/sde` (boot) excluded by construction; Docker app
  data lives on the root fs (`/srv/apps`, `/srv/nas`) and was untouched
- wiped ForgeOS state (`/etc/forgeos`, `/opt/forgeos`, nginx forgeos.d,
  pip-uninstalled the package)
- ran the real install path from a synced repo copy:
  `bootstrap.sh --unattended --hostname forgeos --timezone America/Chicago
  --lan-cidr 10.0.0.0/24 --profile medium`

**First run: installer PASSED all 9 phases** — including `verify` (login
200 + token) and `secaudit` — and then `vm.sh shadow` failed: **64 module
files shadowing dist-packages**. The installer itself re-created the §2
incident on a box that had never been hand-deployed to:
`_default_deploy_web` copied the whole `src/` tree into `/opt/forgeos`,
which is `sys.path[0]` for `ExecStart=/usr/bin/python3
/opt/forgeos/forgeos-api.py`. Every future deploy to such a box silently
does nothing.

**Fixed** (`d90493c`+): `_default_deploy_web` now copies only the
entrypoint and web assets; the pip package is the single copy of the
modules. Guard test `test_deploy_web_copies_only_entrypoint_and_web` pins
the layout.

**Second run: all 9 phases ✓ again, and `vm.sh shadow` clean** (0 stray
files), `vm.sh check` IN SYNC (109 files), `/opt/forgeos` contains exactly
`forgeos-api.py` + `web/`.

Verified live on the fresh box: login → token (157 chars), `/health` ok,
UI serves over nginx, `forgeos-generate all` clean, journal free of
tracebacks, `/api/net/interfaces` hides `incusbr0`, `/api/lxc/*` now 404,
schema v14 seeded, and all four wiped drives visible in
`/api/storage/drives` for the LHSR flow to claim.

Also fixed: `vm.sh`'s manifest still expected the three old entrypoints
in `/opt/forgeos` — they are pip console scripts / repo-tree artifacts
since the layout correction, and the check false-alarmed until updated.

The §8 list is now fully closed: 1–5 fixed in `d90493c`, 6 verified here.

---

## 10 · Full functional test of the clean-install box (2026-10-14, evening)

Exercised the fresh box end-to-end (101-endpoint read battery + write
paths). 80/87 parameterless GETs return 200 — the 7 non-200s are correct
behavior (5× 422 missing-param validation, 1× 404 no compose file, 1×
RustFS-down 500; RustFS is not enabled on a fresh box). All 21 UI pages
serve. WebSockets: `/ws/metrics` streams, `/ws/logs` connects idle, no-token
connections refused. TOTP enroll→verify→backup codes verified against
pyotp. User create/login/RBAC(403)/delete verified.

**Five real bugs found and fixed** — all would have shipped silently:

| # | Bug | Blast radius |
|---|---|---|
| 1 | `execute_pool` guarded the whole fresh disk list, not the plan's devices → every pool create refused ("/dev/sda" → "/dev/sde holds the system") | pool creation 100% broken on any box |
| 2 | Pool mounts made inside the API's private mount namespace — invisible to samba/docker/host | pools looked mounted, were unreadable everywhere else |
| 3 | `/etc/fstab` not in the unit's ReadWritePaths → pool create died after mkfs+mount | half-created pools (fs on disk, no config, no fstab) |
| 4 | `SERVICE_WHITELIST` referenced, never defined → entire service-control endpoint was a NameError 500 | every start/stop/restart dead |
| 5 | `vm.sh deploy` never restarted the API despite its documented contract | every deploy silently ran old code |

Fix details in commit `fix: five live-testing findings on the clean-install
box`. Post-fix, verified live: pool create→mount(fstab+config)→destroy
(unmount+wipefs+fstab cleanup), service restart of docker/nginx/self,
RustFS noted as the one endpoint needing a running service.
