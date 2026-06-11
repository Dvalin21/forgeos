# ForgeOS Architecture Research

Assessment of how production NAS platforms are built, and why ForgeOS v2
adopts the config-DB + generator + app-store model.

## How the real ones are built
- **OpenMediaVault (closest analog):** Debian-based, web-managed, modular
  via plugins distributed as Debian packages. NOT a bash installer that
  installs everything. Base is minimal; features added on demand. Config
  lives in a config DB (omv-confdbadm); omv-salt reads it and generates
  every service's config + starts/stops/restarts the service.
- **TrueNAS SCALE:** Debian-based but ships as an immutable prebuilt image;
  apps as containers; middleware owns all config.
- **CasaOS/Zima:** minimal base + Git-based app store of docker-compose
  apps with metadata in an x-casaos compose extension.

## Common threads
1. Minimal base, features added modularly — never "install 19 subsystems
   in one shot."
2. Single source of truth for config (a DB), with config files generated
   from it — never hand-edited inline.
3. The web UI is the front-end to that config DB; a feature without a UI +
   sane defaults is considered unfinished.
4. Idempotent, re-runnable.

## What was wrong with ForgeOS v1 (root causes)
1. Monolithic install (19 modules, dozens of packages, several Docker
   stacks, ~15 repeated apt updates) — slow, cascading failures, lots of
   third-party software at once.
2. Config by inline heredoc in bash — brittle (webdav.conf + certbot hook
   "no such file or directory"; forgeos-samba generated CLI syntax error).
3. No web-UI/defaults contract for features.
Plus a recurring bug class: bare (( x++ )) under set -e, heredoc-to-missing-
dir, Ubuntu package names on Debian, generated CLIs with syntax errors.

## Decision
Adopt CasaOS/Zima model: minimal base + GitHub app store + config-DB/
generator pattern (the OMV insight, implemented lighter in Python). This
eliminates the bug class by construction and matches the proven model.
