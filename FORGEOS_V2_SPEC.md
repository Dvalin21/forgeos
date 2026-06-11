# ForgeOS v2 — Architecture Spec (BUILD CONTRACT)

This is the agreed scope. Nothing gets added that isn't here without
explicit sign-off. Decided with Keith.

## Model
CasaOS/Zima-style: a **minimal base** that always installs, plus a
**GitHub-hosted app store** for optional apps. Underneath, a
**config database + generator** renders all service config files and
manages services — no more inline heredocs in bash.

## Base — always installed
- Security framework (profiles: Low / Medium / High)
- Backup (Restic + Rclone + Snapper)
- File sharing (Samba + NFS + FTPS + WebDAV)
- VPN (WireGuard)
- Reverse proxy (nginx + Let's Encrypt)
- Docker + Docker Compose        [GUI label: "Docker"]
- Incus                          [GUI label: "Containers" / "LXC" — never "Incus"]
- RustFS (S3 cloud storage)
- SMTP notifications

## Base — toggle (enable = install, disable = uninstall)
- ForgeFileDB
- Coral TPU driver        (also hardware-gated)
- GPU drivers             (also hardware-gated)

## App store (GitHub catalog)
- Monitoring (Grafana / Prometheus / Gotify) — first official app
- Future official apps
- Catalog format: git repo of app manifests + compose files.
  Base pulls the catalog and installs apps on demand from the web UI.

## DELETED entirely (removed from tree)
- HIPAA compliance mode (module 17)
- OnlyOffice
- Immich
- MS Core Fonts (ttf-mscorefonts-installer)
- Mail server (Postfix / Dovecot / SOGo — module 14)

## Security profiles (Low / Med / High)
- Set at install; **re-applicable anytime from the web UI** (generator
  re-renders all security configs when the profile changes).
- Tier matrix (declarative):
  - LOW:    ufw + fail2ban
  - MEDIUM: + apparmor + crowdsec
  - HIGH:   + auditd + aide + rkhunter
- Lowering the tier STOPS/disables the dropped tools but KEEPS them
  installed (fast switch-back). Default profile: medium.
- All 7 tools already existed in legacy 07-security.sh — v2 organizes
  them into tiers, adds no new security software.

## Config-DB + generator (the core architectural change)
- Single source of truth: /etc/forgeos/config.json (pydantic-validated).
- One generator per service: render() (pure: config -> files), apply()
  (mkdir -p, atomic write, chmod), reload(). Registry + forgeos-generate
  CLI orchestrate. Idempotent, re-runnable.

## App store decisions (Keith)
1. Catalog repo: github.com/Dvalin21/forgeos-appstore (separate repo).
2. Install auto-creates an app.<domain> nginx vhost by default.
3. Official ForgeOS catalog only for v1.
4. App data root: /srv/forgeos/apps/<id>/.

## LHSR
- github.com/Dvalin21/lhsr — private, not yet readable by Claude; Keith
  to describe. Future integration. Design a clean integration point.

## Build sequence
1. Config-DB + generator pattern, proven on Samba. [DONE]
2. Remaining base generators: nginx, security, wireguard, nfs. [DONE]
3. Registry + forgeos-generate CLI. [DONE]
4. SMTP notifications + health watcher. [DONE]
5. App store (forgeos_appstore.py, port allocator, install/uninstall,
   forgeos-app CLI, seed catalog, web UI). [NEXT]
6. Coral/GPU/ForgeFileDB toggles.
7. Wire the web API to the generators.
