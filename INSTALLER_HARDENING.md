# ForgeOS Installer Hardening Sprint

**Goal:** make the installer survive non-bare-metal and minimal environments
(Proxmox LXC, VMs, missing hardware) instead of dying silently under
`set -euo pipefail`. Triggered by a real failure: install aborted on a
Proxmox Debian 13 LXC, log stopped mid-"Detecting hardware" with no error.

**Method:** same discipline as the API production-readiness sprints —
findings registry, each fix verified before moving on, no quick patches.

---

## Root cause (empirically confirmed, not assumed)

The installer runs under `set -euo pipefail` but probes hardware that may
legitimately be absent. With **no `ERR`/`EXIT` trap to log a death**, any
unguarded non-zero return kills the installer silently — the log just stops.

Three kill-site CLASSES, each reproduced in isolation under `set -e`:

- **A — bare `(( x++ ))` at value 0.** Post-increment returns the OLD value;
  `(( 0 ))` is arithmetic-false → exit 1 → death. Reproduced: TEST A.
- **B — `false && echo` as a function's last statement.** The `&&` chain
  returns 1; as the final command it becomes the function's exit status,
  propagating under `set -e`. Reproduced: TEST B.
- **C — pipeline ending in a `grep`/filter that matches nothing, under
  `pipefail`.** e.g. `grep x /proc/cpuinfo | head | cut | xargs` → exit 1 →
  death. Reproduced: TEST C.

NOTE: process substitution `done < <(... | grep)` does NOT propagate to
`set -e` (async). Tested — so line 126 lsblk|grep is NOT a killer. This
correction matters: the fix must target A/B/C, not the pipe into the loop.

---

## Findings registry

Severity: CRIT = stops install silently; HIGH = wrong behavior/data; MED =
fragility; LOW = cosmetic.

| ID | Sev | Status | File:Line | Issue |
|----|-----|--------|-----------|-------|
| IH-001 | CRIT | 🟢 DONE | install.sh, common.sh | No ERR/EXIT trap → every set -e death is silent (no log line, no line number). Must add a trap that logs failing line+command before exit. THE debuggability fix — do first. |
| IH-002 | CRIT | 🟢 DONE | detect.sh:124 | `(( DATA_DISK_COUNT++ ))` dies when count is 0 (first iteration in any env). Class A. |
| IH-003 | CRIT | 🟢 DONE | detect.sh:17,21 | CPU detect pipelines die under pipefail when grep misses (non-x86, minimal /proc). Class C. |
| IH-004 | CRIT | 🟢 DONE | detect.sh:149,152-155 | `detect_print_summary` `$VAR && echo` chains die when the var is false and it's the last statement. Class B. |
| IH-005 | HIGH | 🔴 OPEN | detect.sh:7-14 | `detect_all` runs detection in bare-metal order; never consults IS_VM/container. Should detect virt FIRST and skip bare-metal-only probes (disks, GPU, dmidecode) in containers. |
| IH-006 | HIGH | 🔴 OPEN | modules/*.sh | Inconsistent error mode: 01/02/04 declare `set -euo pipefail`, 03-storage does not. Behavior varies module to module. Standardize + document the contract. |
| IH-007 | MED | 🔴 OPEN | install/ (11 sites) | 11 bare `(( x++ ))` across detect/common/modules (Class A). Audit each; `|| true` or `: $((x++))` form. |
| IH-008 | MED | 🔴 OPEN | install/ (8 sites) | 8 pipelines ending in bare grep (Class C). Audit each. |
| IH-009 | HIGH | 🔴 OPEN | (all 19 modules) | Per-module audit for A/B/C + LXC-hostile assumptions (raw /dev access, modprobe, systemd features unavailable in containers). One registry row per module as audited. |
| IH-010 | MED | 🔴 OPEN | test harness | No way to catch this in sandbox. Build a constrained-container test that runs detect_all + dry-run modules and asserts they survive missing hardware. |

---


## Debian-vs-Ubuntu compat findings (from cross-distro scan)

The installer was developed/tested on Ubuntu; these Ubuntu-isms break or
no-op on Debian. IH-DEB-001 fixed in module 01; others queued for IH-009.

| ID | Sev | Status | File:Line | Issue |
|----|-----|--------|-----------|-------|
| IH-SCOPE-001 | MED | 🟢 DONE | install.sh, 12-reverse-proxy.sh, 99-finalize.sh, 17-hipaa.sh | Removed OIDC/Authentik/lldap OFFERING (Sprint 6 decision: native user mgmt + 2FA, no external IdP). Dropped the install prompt, hardcoded module 13 to false (file kept dormant), removed the authentik nginx vhost + finalize-summary line + hipaa docstring. No active OIDC wiring remains. |
| IH-SCOPE-002 | MED | 🟢 DONE | install.sh, 05-coral-tpu.sh | De-bundled Frigate NVR from the Coral TPU module. Frigate was woven through 6 places (header docs, dir creation, generate_frigate_compose function ~140 lines, CLI frigate-* commands, CLI help, completion messages). Removed all of it; module 05 is now a clean standalone Coral Edge TPU driver (gasket/apex DKMS + runtime + CLI). Prompt changed from 'Coral TPU + Frigate NVR' to 'Coral TPU drivers'. Frigate is no longer offered at all. Verified: zero frigate refs, braces 52/52, CLI heredoc intact. |
| IH-SCOPE-003 | HIGH | 🟢 DONE | 16-cloud-storage.sh, 12-reverse-proxy.sh, 99-finalize.sh, 04-docker.sh, install.sh | Replaced MinIO with RustFS (S3-compatible, Apache-2.0). The installer deployed MinIO but the web API (rustfs_api.py) expects RustFS — architectural mismatch. Module 16 now: downloads the RustFS musl binary, runs it as an unprivileged 'rustfs' systemd service via RUSTFS_* env vars (same ports 9000 API / 9001 console), creates default buckets via boto3 from the API venv (RustFS has no bundled mc), forgeos-cloud CLI uses rustfs-* subcommands. rclone local remote [rustfs]. nginx vhosts + finalize summary + install prompt all updated. MINIO_* config keys kept as one-release aliases. Verified: syntax clean, braces 62/62, all heredocs balanced. Real validation pending Keith's run. |
| IH-DEB-001 | CRIT | 🟢 DONE (confirmed on HW) | 01-base.sh | `ntp` (no candidate on Debian 12+, use chrony), `software-properties-common` (Ubuntu pkg), `linux-headers-$(uname -r)` (host kernel, uninstallable in LXC). Split essentials from optional; skip headers in containers. |
| IH-DEB-002 | LOW | 🔴 OPEN | 18-apps.sh:44 | `add-apt-repository -y multiverse` is Ubuntu-only; comment claims Debian contrib path but code doesn't implement it. Guarded by `|| true` so non-fatal. |
| IH-DEB-003 | LOW | 🔴 OPEN | 06-gpu.sh:239 | Ubuntu HWE kernel packages (`linux-*-hwe-22.04`) don't exist on Debian. Optional so non-fatal but useless. |
| IH-DEB-004 | MED | 🔴 OPEN | 04-docker.sh:55 | Docker apt repo codename map handles Ubuntu noble→jammy but has no Debian branch; verify `trixie` (Debian 13) resolves to a real Docker repo. |

| IH-DEB-005 | CRIT | 🟢 DONE | 12-reverse-proxy.sh:43 | nginx repo hardcoded `/packages/mainline/ubuntu` but used `${codename}` (Debian 'trixie') → "no Release file" → fatal apt-get update (exit 100) during finalize. nginx.org has separate /debian and /ubuntu repo paths. Fixed: detect ID from /etc/os-release, pick correct path, fall back to distro nginx pkg on unknown OS or repo failure. Also dropped nginx-extras (not in nginx.org repo). Confirmed on Keith's log: ubuntu/trixie path 404s. |
| IH-DEB-006 | HIGH | 🔴 OPEN | 99-finalize.sh:2349 (log) | "Web UI source not found at .../web — install manually". Installer can't find the web/ dir relative to modules. Path resolution bug — web UI never installed. |
| IH-012 | LOW | 🔴 OPEN | common.sh:145 apt_update | Bare `apt-get update` dies on ANY single bad third-party repo (this is how IH-DEB-005 became fatal in finalize rather than module 12). Consider: tolerate per-repo failures, or validate repos before adding. Judgment call — failing loud is arguably correct. |
## Module audit tracker (IH-009 detail)

| Module | Audited | LXC-safe | Notes |
|--------|---------|----------|-------|
| 01-base | ⬜ | ? | |
| 02-network | ⬜ | ? | |
| 03-storage | ⬜ | ? | no `set -e` declared; RAID/mdadm needs real block devs |
| 03-storage-hotswap | ⬜ | ? | |
| 03c-drive-types | ⬜ | ? | |
| 04-docker | ⬜ | ? | |
| 05-coral-tpu | ⬜ | ? | `(( found++ ))` x2 |
| 06-gpu | ⬜ | ? | |
| 07-security | ⬜ | ? | |
| 09-monitoring | ⬜ | ? | |
| 10-fileshare | ⬜ | ? | |
| 10b-samba-db | ⬜ | ? | |
| 10c-forgeos-filedb | ⬜ | ? | |
| 11-vpn | ⬜ | ? | WireGuard kernel module — may not load in LXC |
| 12-reverse-proxy | ⬜ | ? | |
| 13-ldap-oidc | ⬜ | ? | |
| 14-mail | ⬜ | ? | |
| 15-backup | ⬜ | ? | |
| 16-cloud-storage | ⬜ | ? | |
| 17-hipaa | ⬜ | ? | `(( pass++ ))` |
| 18-apps | ⬜ | ? | |
| 99-finalize | ⬜ | ? | |

---

## Commit plan

1. **IH-001** ERR trap + logging (do first — makes everything else debuggable).
2. **IH-002/003/004** fix the detect.sh kill-sites that stop the boot path.
3. **IH-005** make detect_all virt-aware.
4. **IH-006** standardize module error-handling contract.
5. **IH-007/008** sweep remaining arithmetic + grep kill-sites.
6. **IH-009** per-module audit (may be several commits).
7. **IH-010** constrained-container test harness.

Each commit verified in sandbox (and, where possible, in a minimal container
that mimics the LXC) before delivery. Bundle per the established method.
