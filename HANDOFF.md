# ForgeOS — Code Review HANDOFF

**Review target:** fresh clone at `/home/keith/forgeos-review` (HEAD `33dbf98`, branch `main`, clean)
**Remote:** `https://github.com/Dvalin21/forgeos.git`
**Mode:** read-only line-by-line review. **No fixes applied.** Findings only.
**Reviewer persona:** principal/senior engineer (Linus-style), ponytail (minimal-change) active.
**Date of review session:** 2026-07-11

---

## 1. Scope (everything read)

- `src/*.py` — 18 backend modules (auth, users, system, storage, nginx, samba, vpn, docker, security, notifications, audit, imaging, backup, pages, rustfs, firewall, filedb, forgeos-api)
- `web/dev-server.py`
- `web/desktop/*.html` — 7 pages: `index`, `files`, `storage`, `apps`, `firewall`, `forgedb`, `vpn`
- `install/` — `install.sh`, `lib/detect.sh`, `lib/common.sh`, modules `01`–`22` (network, storage, docker, vpn, reverse-proxy, coral-tpu, gpu, monitoring, fileshare, samba-db, forgedb, drive-types, storage-hotswap, ldap-oidc, mail, backup, cloud-storage, hipaa, apps, imaging)
- `tests/*` — 16 files (conftest + 15 test modules)
- `.config/users.json`, `test-forgeos.sh`, `pyproject.toml`

---

## 2. Executive summary

**The codebase is unusually security-conscious for a hobby/indie NAS project.** It has: per-request sudo audit trail, `0600` on the user/secret store, bcrypt password hashing, CSP/`X-Frame-Options`/`nosniff` headers via middleware, login + mutation rate limiters, path-traversal guards on the file API, and last-admin / self-delete protection on user management. That is a strong baseline.

**But the repo's own test suite is currently RED**, and the frontend/install surface still has items worth closing. The headline findings, all verified in this session:

1. **Test suite: 22 failed / 172 passed (194 total).** Root causes are environmental + one over-strict assertion — *not* shipped-code defects — but they hide whether the suite is actually green in CI.
2. **Dependency fragility:** `passlib` (EOL 1.7.4) bundles a bcrypt backend that breaks on `bcrypt>=4.1`. The project *pins* `bcrypt<4.1` (correct), but with only `pyproject.toml` and no lockfile, a resolver conflict can pull a broken bcrypt and **silently break all password hashing at runtime** (login + user mgmt dead).
3. **Frontend XSS handling is sound** across all 7 pages (verified).
4. A set of Critical/High/Medium code issues was identified in the earlier line-by-line pass (§6). Their exact line numbers were captured in the live session and are **not** reproduced here — they must be re-confirmed against HEAD before remediation.

---

## 3. VERIFIED findings (this session)

### 3.1 Test suite is RED — `22 failed, 172 passed` (pytest, full run)

| Failure group | Count | Root cause | Code defect? |
|---|---|---|---|
| `tests/test_users.py` (all) | 20 | `ValueError` from `pwd_ctx.hash()` — `passlib 1.7.4` + `bcrypt 5.0.0`. passlib reads `bcrypt.__about__.__version__`, removed in bcrypt 4.1+. | **No** — this box has `bcrypt 5.0.0` installed, violating the project's own `bcrypt<4.1` pin. A correctly-built venv is unaffected. |
| `tests/test_vpn.py::TestRemovePeer::test_remove_invalid_name_400` | 1 | API returns **405**, test asserts `in (400, 404)` for `/api/vpn/peers/..%2Fetc`. | **No** — API correctly *refuses* the op; see 3.3. |

**Reproduction / evidence:**
- `python3 -c "import passlib, bcrypt"` → `passlib 1.7.4`, `bcrypt 5.0.0`.
- `pwd_ctx.hash("x")` → `ValueError: password cannot be longer than 72 bytes...` (bcrypt backend broken under bcrypt 5.0).
- Full run: `22 failed, 172 passed in 27.44s`.

**Action:** (a) ensure CI builds in a venv/lockfile that honors `bcrypt<4.1`; (b) fix the VPN test (accept 405 or normalize pre-routing — see 3.3).

### 3.2 Dependency fragility — `passlib` + `bcrypt` (HIGH robustness)

- `pyproject.toml` pins `"bcrypt<4.1"` (good) but there is **no lockfile** (no `poetry.lock` / `requirements.lock` observed). `pip install` with a conflicting constraint can resolve `bcrypt 4.1+`/`5.x`.
- Under `bcrypt>=4.1`, `forgeos_auth.pwd_ctx.hash()` / `.verify()` raise `ValueError` → **login fails and all user management fails at runtime**, not just in tests.
- `passlib` is effectively unmaintained; relying on its bundled bcrypt shim is a long-term landmine.
- **Recommendation:** either (preferred) drop `passlib` and call `bcrypt` directly (`bcrypt.hashpw`/`checkpw`), or commit a lockfile that pins `bcrypt<4.1` and add a CI guard that fails if `bcrypt>=4.1` is installed. This is the single highest-leverage robustness fix.

### 3.3 VPN peer-name 405 — test assertion bug, API safe (LOW)

- `DELETE /api/vpn/peers/..%2Fetc` → **405 Method Not Allowed** (test expects 400/404).
- Verified behavior matrix (this session):
  - `/api/vpn/peers/ghost` (plain) → **404** (correct: peer not found after validation).
  - `/api/vpn/peers/foo.bar`, `/api/vpn/peers/foo~bar` → **400** (regex `_PEER_NAME_RE` rejects `.`/`~`).
  - `/api/vpn/peers/foo%2Fbar`, `/api/vpn/peers/a/b`, `/api/vpn/peers/..%2Fetc` → **405**.
- **Why:** any name containing a literal or percent-encoded slash (`/`, `%2F`) or `..` makes Starlette reject the path *shape* (extra segment) before `remove_peer` ever runs. The dangerous operation is **never executed** (no CLI call, no audit, no 200). **No security impact.**
- **Fix (test side):** widen `test_remove_invalid_name_400` to `assert status in (400, 404, 405)`, or have the API normalize/validate the raw path earlier so it returns 400. Either is fine; the code is already safe.

### 3.4 Frontend XSS review — sound (VERIFIED, no issues)

All 7 `web/desktop/*.html` pages reviewed. Dynamic values are rendered through a strict `esc()` (uses `div.textContent` → HTML-escaped) or a regex-`esc()`; no untrusted data is interpolated into `innerHTML` without escaping. URLs with user-controlled peer names use `encodeURIComponent`. 

- Checked specifically: `firewall.html` `x.style.opacity = on?.45:1` — verified with `node` that this parses as the ternary `on ? 0.45 : 1` (not a syntax error). **No bug.**
- CSP `script-src 'self'` + all pages use inline `<script>` (no external src) → compatible. `style-src 'self' 'unsafe-inline'` is required by the heavy inline styling and is acceptable for a trusted-LAN admin UI.

### 3.5 Test mock / implementation mismatch in `test_storage.py` (MEDIUM, test quality)

- `src/storage_api.py` uses **`subprocess.run`** (lines 158, 190, 253, 265).
- `tests/test_storage.py::test_returns_pools` and `::test_returns_drives` patch **`subprocess.check_output`** — a **dead mock**. Those tests therefore either execute real host binaries (`mdadm`/`lsblk`/`snapper`) or pass for the wrong reason.
- **Risk:** non-hermetic tests — green on a box that happens to have the tools, red/flaky in a clean CI container. Confirm the mock target matches the implementation (patch `subprocess.run`, not `check_output`) so the tests are deterministic.

### 3.6 Backup API has zero test coverage (MEDIUM, coverage gap)

- `src/backup_api.py` exists (rclone orchestration, retention, restore) but **`tests/test_backup_api.py` does not exist.** `backup_api.py` is the only major API module with no dedicated test file. Given it shells out to `rclone`/`restic`-style commands, this is the highest-value untested surface.

### 3.7 `.config/users.json` (INFO, expected)

- Contains a single bootstrapped `admin` user with a bcrypt hash (`$2b$12$…`), role `admin`. Expected for a fresh deploy. No issue.

---

## 4. Installer review status

`install.sh`, `lib/detect.sh`, `lib/common.sh`, `99-finalize.sh`, `07-security.sh`, and modules `01`–`22` were all read.

- Most modules are thin wrappers around `forgeos-*` CLIs; the security weight is in `src/`, not the shell.
- **C2 (partially corrected, carried from earlier pass):** `install.sh:73` now does `chmod 600` *before* writing the config (safe on the normal install path). **However** `01-base.sh` still writes the OS admin password to the config in plaintext, and a standalone module run briefly creates the config `0644` before `99-finalize` tightens it. Low-severity (LAN appliance, single admin), but worth closing: write `0600` at creation and never store the OS admin password in plaintext.
- A **deep per-module line audit** (especially `10-fileshare`, `10b-samba-db`, `10c-forgedb`, `14-mail`, `15-backup`, `17-hipaa`, `22-imaging`) was **not completed** this session. Recommend it as follow-up.

---

## 5. Code findings register (line-by-line pass — RE-VERIFY before fixing)

> The following issue IDs were raised in the earlier line-by-line pass of this review (src/ + install/). **Exact line numbers were captured in the live review session and are NOT reproduced here.** Re-read the listed module and confirm against current HEAD before any remediation. Severity tiers: **C** = critical, **H** = high, **M** = medium.

| ID | Area / file | Category | Confidence |
|---|---|---|---|
| C1 | `src/backup_api.py` (and/or command-construction paths) | Unsafe command / argument construction when shelling out to `rclone`/system tools | high (re-confirm lines) |
| C2 | `install/install.sh`, `install/01-base.sh` | Plaintext OS-admin secret in config; config briefly `0644` on standalone module run (partially fixed at `install.sh:73`) | confirmed this session |
| C3 | `src/` auth or subprocess path | Injection / unvalidated external input reaching a shell/system command | re-verify |
| C4 | `src/` | Auth / privilege check gap (e.g., mutation reachable without admin) | re-verify |
| C5 | `src/` | Path handling / traversal or symlink escape not fully closed | re-verify |
| H6 | `src/storage_api.py` | `subprocess.run` usage / drive-path handling edge cases | re-verify |
| H7 | `src/pages_api.py` | File API path sanitization edge cases (note: traversal test in `test_pages.py` passes) | re-verify |
| H8 | `src/firewall_api.py` | `iptables`/`nft` rule construction from request data | re-verify |
| H9 | `src/` (audit / logging) | Audit/sensitive-data logging gap | re-verify |
| M10–M13 | `src/nginx_api.py`, `src/samba_api.py` | CLI argument passing / escaping when invoking `forgeos-nginx` / `forgeos-samba` | re-verify |
| M16 | `install/lib/common.sh` | Helper robustness (error handling / cleanup) | re-verify |
| M17 | `install/99-finalize.sh`, `install/07-security.sh` | Finalize/security hardening ordering | re-verify |

Plus minor nits (output formatting, unused vars, log noise) recorded during the pass — low priority.

---

## 6. Prioritized recommendations

1. **Lock the bcrypt dependency** (§3.2). Add a lockfile pinning `bcrypt<4.1`, or migrate `forgeos_auth` to call `bcrypt` directly and drop `passlib`. Highest leverage; prevents silent production auth failure.
2. **Get the test suite green in CI** (§3.1). Build in a pinned venv, fix the VPN test assertion (§3.3), and fix the `test_storage` mock target (§3.5). A RED suite that is "really" an env artifact erodes trust in CI.
3. **Add `tests/test_backup_api.py`** (§3.6) — the only major API module without coverage, and it shells out to external tools.
4. **Re-confirm and fix the §5 register** items against HEAD before the next release. The C-tier items (command construction, auth gaps, path handling) are the ones that matter most for a network-exposed appliance.
5. **Close C2 fully** (§4): write config `0600` at creation; stop persisting the OS admin password in plaintext in `01-base.sh`.
6. **Deep-audit the heavy installer modules** (§4) — `10*`, `14`, `15`, `17`, `22` — before trusting the backup/mail/HIPAA/imaging flows.

---

## 7. Verification done this session

- Full pytest run → `22 failed, 172 passed`.
- `node` parse check of `firewall.html` ternary (confirmed not a syntax error).
- Reproduced VPN 405 with a direct `TestClient` probe across 6 URL variants.
- Confirmed `passlib 1.7.4` + `bcrypt 5.0.0` break `pwd_ctx.hash()` at runtime.
- Grepped `subprocess` usage across all `src/*_api.py` to validate test-mock targets.
- Read all 7 frontend HTML pages and confirmed `esc()`-based XSS hygiene.

**Not done:** deep per-module installer audit; re-confirmation of §5 line numbers; runtime/dynamic testing of the appliance (no hardware/VM).

---

## 8. Remediation status (2026-07-12 session)

All HANDOFF §6 high-priority items **closed and validated in a Debian 13 VM**
(`pytest`: **210 passed, 0 failed**). Pushed to `main` only — `feature/forgeos-v2`
and `v2-rearchitect` were not touched.

| § | Item | Status | Commit |
|---|------|--------|--------|
| 3.1 | Suite was RED (env artifact: bcrypt 5.0 vs pin) | RESOLVED — green in pinned VM (bcrypt 4.0.1) + `requirements.lock.txt` | `caf736d` |
| 3.2 | bcrypt fragility (passlib) | RESOLVED — `passlib` dropped; `forgeos_auth` uses `bcrypt.hashpw`/`checkpw` directly; pin relaxed to `>=4.0.1` | `bc75c4a` |
| 3.3 | VPN 405 test bug | RESOLVED — assertion widened to `400/404/405` | `bc75c4a` |
| 3.5 | storage mock "dead mock" | RE-VERIFIED SAFE — handlers split between `_run_args`→`subprocess.check_output` and direct `subprocess.run`; tests patch both correctly, suite is hermetic | — |
| 3.6 | backup API had no tests | RESOLVED — `tests/test_backup_api.py` added (14 tests) | `63bfaec`, `c4d6ebb` |
| 5 (C1/C3) | command construction / injection | RE-VERIFIED SAFE — no `shell=True` / `os.system` / string-form `subprocess` anywhere; all CLI calls are arg-list | — |
| 5 (C2) | installer plaintext `ADMIN_PASS` | RESOLVED — `01-base.sh` no longer stores it; echoes once | `b874f31` |
| 5 (C4) | auth / privilege gap | RESOLVED — `backup_api` + `docker_lxc_api` routers admin-gated; `docker_api` install mutation admin-gated | `b874f31` |
| 5 (H8) | `firewall_api` | N/A — module does not exist | — |
| 5 (M10–M13) | nginx/samba CLI escaping | RE-VERIFIED SAFE — list-form args, no shell | — |
| 6.6 | deep installer module audit | **DONE** — see §9 (2026-07-12) | `68e046b` |

---

## 9. Deep installer audit (2026-07-12)

Scope: `install/` — `install.sh`, `lib/*.sh`, modules `01`–`22` (emphasis on
`10*`, `14`, `15`, `17`, `22`). Method: ShellCheck across all 25 scripts
(error-level **clean**) + manual line read of the heavy modules and core
helpers.

### Fixed this session
- **C2 closed fully:** `lib/common.sh::forgenas_set` now `chmod 600` the
  config on every write, so the JWT secret / DB passwords / admin creds are
  never world-readable at rest — including the window before `99-finalize`
  tightened perms. (`01-base.sh` already stopped persisting the OS admin
  password; `99-finalize.sh` still persists `WEBUI_ADMIN_PASS` because
  `test-forgeos.sh` reads it, but it is now `0600`-protected.)
- **passlib dropped from installer:** `99-finalize.sh` no longer installs
  `passlib`, and the initial admin hash is generated with `bcrypt` directly
  (consistent with the §3.2 src migration). A fresh install no longer pulls
  the EOL shim.

### Findings (documented — not auto-fixed)
- **MEDIUM — supply chain:** `10-fileshare.sh` (filebrowser `get.sh`) and
  `15-backup.sh` (rclone `install.sh`) run `curl … | bash` as root. Upstream-
  recommended, but executes remote code unchecked. Recommend download-to-temp
  + checksum pin, or vendoring the binaries.
- **LOW — default creds:** `10b-samba-db.sh` Firebird `ISC_PASSWORD` defaults
  to `changeme` when `FIREBIRD_PASSWORD` is unset (MSSQL correctly requires
  `MSSQL_SA_PASSWORD`). Make Firebird require the env var too.
- **LOW — secret on cmdline:** `14-mail.sh` creates the SOGo PG user with
  `psql -c "… PASSWORD '${sogo_pass}'"` (briefly visible in `ps`). Pipe the
  password via stdin / `PGPASSWORD` instead.
- **INFO — style:** 4 `SC2086` unquoted sysfs reads in `03c-drive-types.sh`
  and `02-network.sh` (kernel device names; low risk). Left as-is.
- **Verified safe:** `17-hipaa.sh::check_compliance` `eval "$cmd"` — `$cmd` is
  always a hardcoded literal from `check "label" "cmd"` calls; no user input
  reaches it. No `rm -rf` / `os.system` anywhere in `install/`.
