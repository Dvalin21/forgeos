# ForgeOS

**Open-source NAS and home server platform for Ubuntu/Debian.**
Built natively on the OS — not a repackaged distro.

---

## What This Repo Contains

This repo contains the **web backend API and desktop UI** for ForgeOS. The installer (`install/`) applies everything to a bare Ubuntu/Debian system, but this repo is specifically:

| Directory | Contents |
|-----------|----------|
| `src/` | FastAPI backend — REST endpoints, WebSocket handlers, auth |
| `web/` | Desktop web UI — SPA with widget system, dev server |
| `install/` | Idempotent installer modules (base, storage, docker, ...) |
| `docs/` | Post-install guides, database config, Coral TPU notes |

The Python modules in `src/` are installed as a systemd service at `/opt/forgeos/api/` and served behind nginx. The web UI is served from `/opt/forgeos/web/`.

---

## Features — At a Glance

### Storage
- **ForgeRAID** — mdadm + LVM + btrfs. Mixed-size drives. RAID 1/5/6/10 and JBOD
- **Drive classification** — automatic HDD / SSD / NVMe / USB detection
- **Cache drives** — bcache SSD/NVMe caching for HDD pools (writeback, writethrough, writearound)
- **Hot-swap** — udev-driven detection, SMART health check on insert, auto-rejoin to degraded arrays
- **SMART predictive failure** — smartd continuous monitoring, four alert levels, tray indicators
- **btrfs snapshots** — Snapper timeline, web snapshot browser, one-click restore

### Networking
- **Reverse proxy** — nginx with automatic Let's Encrypt certificates
- **VPN** — WireGuard server with per-client QR codes; optional Netbird mesh
- **mDNS** — Avahi broadcasts `hostname.local` and all services on LAN

### File Sharing
- **SMB** — Samba 4, SMB3, macOS Time Machine, five share templates
- **NFS v4** — v3 disabled, for Linux/ESXi clients
- **FTPS** — ProFTPD with mandatory TLS, passive mode for NAT
- **WebDAV** — nginx-backed, Windows network drive compatible
- **FileBrowser** — web-based file manager

### File-Based Database (ForgeFileDB)
- Coordinates concurrent access for ElevateDB, DBISAM, dBase, FoxPro, MS Access, NexusDB, SQLite, Firebird, Paradox
- Prevents SMB oplock corruption without client-side changes
- Versioned snapshots with one-click restore (btrfs instant or rsync fallback)
- mDNS discovery on `_forgeos-filedb._tcp` and `_edb-server._tcp`

### Containers
- **Docker CE** — official repo, overlay2 storage, Compose v2
- **Incus** — LXC/LXD successor for system containers and VMs

### AI / Compute
- **GPU drivers** — NVIDIA (ubuntu-drivers + CUDA + container toolkit), AMD (ROCm + VA-API), Intel Arc (i915/xe + Quick Sync)
- **Google Coral TPU** — PCIe single/dual via gasket+apex kernel modules (KyleGospo fork for kernel 6.x). Frigate NVR compose auto-generated
- **Frigate NVR** — Docker Compose with correct TPU passthrough, auto-configured camera template

### Security
- UFW (default deny inbound) + Fail2ban + CrowdSec
- AppArmor (enforcing) + auditd + AIDE + rkhunter
- Mandatory TLS everywhere — no plaintext protocols
- Optional HIPAA compliance module (auditd rules, gocryptfs ePHI, 6-year retention)

### Monitoring
- Prometheus + Grafana + Alertmanager (Docker Compose)
- node_exporter, smartctl_exporter
- Gotify push + Apprise multi-channel (Discord, Slack, Telegram, etc.)
- Fan control via lm-sensors + fancontrol

### Authentication (optional)
- **lldap** — lightweight LDAP
- **Authentik** — OIDC/OAuth2 SSO with TOTP + WebAuthn 2FA
- nginx `forward_auth` snippet for protecting any service

### Mail (optional)
- Postfix + Dovecot + Rspamd + ClamAV + SOGo webmail
- DKIM auto-generation, DNS record printer
- Mandatory TLS on all ports

### Backup
- **Restic** — AES-256 encrypted, deduplicated, to local + cloud
- **Rclone crypt** — client-side encrypted sync to B2/S3/R2/SFTP
- Systemd timers: Restic 02:00, Rclone 04:30, 1h random delay

### Cloud (optional)
- **MinIO** — self-hosted S3-compatible
- Rclone encrypted sync wizard for B2, AWS S3, Cloudflare R2

### Applications
- **OnlyOffice** — self-hosted office suite with Microsoft Core Fonts
- **Immich** — self-hosted Google Photos with GPU-accelerated AI

---

## Architecture — API

The backend lives in `src/` and is a **FastAPI application** serving REST + WebSocket endpoints.

```
src/
├── forgeos-api.py          # Main app: mounts sub-routers, hosts system endpoints + WebSockets
├── forgeos_auth.py         # Shared auth: JWT create/verify, bcrypt, LoginRequest model
├── filedb_api.py           # ForgeFileDB REST + WebSocket API
├── docker_lxc_api.py       # Docker + LXC container management
├── rustfs_api.py           # RustFS S3-compatible storage API
└── __init__.py             # Package marker
```

### Auth Flow

| Layer | Mechanism |
|-------|-----------|
| REST endpoints | `Authorization: Bearer <JWT>` header, or `forgeos_token` cookie fallback |
| WebSocket | `?token=<JWT>` query parameter |
| Token expiry | 12 hours from issue, HS256-signed |
| Credentials | bcrypt-hashed, stored in `/etc/forgeos/api-users.json` |

The `forgeos_auth.verify_token()` function is wired as a **router-level dependency** on every sub-router. WebSocket routes call `verify_ws_token()` explicitly since FastAPI does not propagate `include_router(dependencies=[])` to WebSocket handlers.

### API Endpoint Map

| Prefix | Sub-Router | Auth |
|--------|-----------|------|
| `/api/system/*` | `forgeos-api.py` (inline) | Header / cookie |
| `/api/storage/*` | `forgeos-api.py` (inline) | Header / cookie |
| `/api/docker/*` | `docker_lxc_api.py` | Router-level |
| `/api/lxc/*` | `docker_lxc_api.py` | Router-level |
| `/api/filedb/*` | `filedb_api.py` | Router-level |
| `/api/rustfs/*` | `rustfs_api.py` | Router-level |
| `/ws/metrics` | `forgeos-api.py` (inline) | Query token |
| `/ws/logs` | `forgeos-api.py` (inline) | Query token |
| `/ws/docker/exec` | `forgeos-api.py` (inline) | Query token |
| `/ws/lxc/exec` | `forgeos-api.py` (inline) | Query token |
| `/ws/filedb` | `filedb_api.py` | Query token via `verify_ws_token()` |

---

## Architecture — Web UI

The frontend is a **client-side SPA** served from `web/desktop/`. No framework — vanilla JS with a custom widget system.

```
web/desktop/
├── index.html                  # Main desktop shell — login overlay, taskbar, desktop area
├── docker.html                 # Docker container management page
├── filedb.html                 # ForgeFileDB management page
├── filestation.html            # File browser (local)
├── filestation-rustfs.html     # File browser (RustFS S3)
│
├── js/
│   ├── forgeos.js              # Core: auth flow, API client, dashboard, data-stat wiring
│   ├── dashboard.js            # Dashboard widget data loader
│   ├── sidebar.js              # Sidebar navigation
│   ├── taskbar.js              # Taskbar (window list, clock, user menu)
│   ├── topbar.js               # Top navigation bar
│   ├── window-manager.js       # Desktop window management
│   └── icons.js                # SVG icon definitions
│
├── components/
│   ├── forge-topnav.js         # Top navigation component
│   ├── forge-widget.js         # Base widget class
│   ├── forge-terminal.js       # Terminal component
│   ├── widget-alerts.js        # Alerts/notifications widget
│   ├── widget-filedb.js        # FileDB status widget
│   ├── widget-network.js       # Network stats widget
│   ├── widget-storage.js       # Storage pool widget
│   └── widget-system.js        # System info widget
│
├── css/
│   └── forgeos.css             # All desktop styles
│
├── settings/
│   ├── index.html              # Settings hub
│   ├── backup.html             # Backup configuration
│   ├── network.html            # Network settings
│   ├── storage.html            # Storage settings
│   ├── system.html             # System settings
│   └── wallpaper-selector.js   # Wallpaper picker
│
├── backgrounds/
│   ├── manifest.json           # Wallpaper definitions (CSS gradients)
│   ├── abyss.svg               # Wallpaper: Abyss (default)
│   ├── horizon.svg             # Wallpaper: Horizon
│   ├── pulse.svg               # Wallpaper: Pulse
│   ├── strata.svg              # Wallpaper: Strata
│   └── zenith.svg              # Wallpaper: Zenith
│
├── tests/                      # Functional and visual test files
│   ├── icons-reference.html
│   ├── test-all-widgets.html
│   ├── test-all-widgets.js
│   ├── test-css.sh
│   ├── test-forge-widget.html
│   ├── test-pages.sh
│   ├── test-topnav.html
│   ├── test-widget-system.js
│   └── test-widgets-syntax.sh
│
└── icons.svg                   # SVG sprite sheet
```

### Frontend-Backend Contract

The SPA communicates with the backend through `forgeos.js` which exposes:

| Function | Purpose |
|----------|---------|
| `api(path, options)` | Authenticated fetch wrapper — auto-attaches JWT, handles 401 redirect |
| `login(username, password)` | POST `/api/token`, stores JWT in cookie |
| `logout()` | Clears token cookie, redirects to login |
| `refreshDashboard()` | Loads CPU, memory, storage, network stats into data-stat attributes |

Dashboard widgets bind to elements with **`data-stat` attributes** (not fragile array indices). For example:

```html
<div class="stat-card" data-stat="cpu_percent">...</div>
<div class="stat-card" data-stat="memory_percent">...</div>
```

---

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| CPU | 2 cores, x86_64 | 4+ cores |
| RAM | 4 GB | 8 GB+ |
| System disk | 32 GB SSD | 64 GB SSD |
| Data disks | 1 | 2+ for RAID |
| Network | 1 GbE | 2.5 GbE+ |

Also supported: Debian 12 (Bookworm), Ubuntu 22.04/24.04 on ARM64 (Raspberry Pi 4/5, Ampere).

---

## Quick Install

```bash
# On a fresh Ubuntu 22.04/24.04 or Debian 12 system
git clone https://github.com/Dvalin21/forgeos.git
cd forgeos
sudo bash install/install.sh
```

The interactive wizard runs in about 15-30 minutes depending on selected modules and internet speed. All modules are idempotent — safe to re-run.

### Unattended Install (CI / Automated)

```bash
export FORGEOS_HOSTNAME=nas
export FORGEOS_DOMAIN=home.example.com
export FORGEOS_ADMIN_USER=admin
export FORGEOS_TIMEZONE=America/Chicago
sudo bash install/install.sh --unattended --modules=base,storage,docker,security,proxy,fileshare,backup
```

---

## Post-Install Access

| Service | URL |
|---------|-----|
| ForgeOS Web UI | `https://nas.local` |
| FileBrowser | `https://files.nas.local` |
| Grafana | `https://grafana.nas.local` |
| OnlyOffice | `https://office.nas.local` |
| Immich | `https://photos.nas.local` |
| ForgeFileDB | `https://filedb.nas.local` |
| MinIO Console | `https://console.s3.nas.local` |
| Gotify | `https://push.nas.local` |
| SOGo Mail | `https://mail.nas.local/SOGo` |
| Authentik SSO | `https://auth.nas.local` |
| Frigate NVR | `https://nvr.nas.local` |

---

## Development

For frontend work, you can serve the web UI standalone without installing the full OS:

```bash
python3 web/dev-server.py
# → http://localhost:5080/desktop/index.html
```

The dev server disables browser caching (`Cache-Control: no-cache`) so edits take effect on reload. The API backend will not be available — you'll only see the login shell unless the actual API is running.

---

## CLI Reference

Every installed module has a dedicated CLI tool:

```bash
forgeos-ctl          # System control (status, restart-all, update)
forgeos-storage      # Pool management, snapshots
forgeos-cache        # bcache cache drive setup and monitoring
forgeos-drives       # Drive type detection and registry
forgeos-samba        # SMB share management
forgeos-fileshare    # NFS/FTP/WebDAV/FileBrowser management
forgeos-filedb       # ForgeFileDB coordinator
forgeos-db           # MariaDB/PostgreSQL/Firebird/ElevateDB
forgeos-nginx        # Reverse proxy vhost management
forgeos-vpn          # WireGuard peer management + QR codes
forgeos-backup       # Restic backup management
forgeos-cloud        # MinIO + Rclone cloud sync
forgeos-auth         # lldap/Authentik user management
forgeos-mail         # Mail server management
forgeos-coral        # Coral TPU + Frigate NVR
forgeos-hipaa        # HIPAA compliance tools
forgeos-notify       # Send notifications via Apprise
```

---

## Testing

```bash
# Full test suite (requires installed ForgeOS)
sudo bash test-forgeos.sh

# Quick mode (skip functional tests)
sudo bash test-forgeos.sh --quick

# Test a specific module
sudo bash test-forgeos.sh --module=storage
```

Results saved to `/var/log/forgeos/test-report-YYYYMMDD-HHMMSS.json`.

---

## Google Coral TPU Notes

The official Google `gasket-dkms` package from `packages.cloud.google.com` **does not build on Linux kernel 6.x+**. ForgeOS uses the community-maintained [KyleGospo/gasket-dkms](https://github.com/KyleGospo/gasket-dkms) fork with kernel 6.x patches.

**Single TPU** (M.2 or PCIe): creates `/dev/apex_0`
**Dual TPU** (M.2 dual card): creates `/dev/apex_0` + `/dev/apex_1` — requires PCIe x2 bifurcation on the motherboard.

If `/dev/apex_*` doesn't appear after reboot:
```bash
forgeos-coral fix-aspm   # Adds pcie_aspm=off to GRUB, then reboot
```

---

## ElevateDB / Atrex / File-Based Database Notes

ForgeFileDB coordinates concurrent SMB access to file-based database engines. No client-side changes needed.

```bash
# Create a share with all oplocks disabled
forgeos-samba create myapp /srv/nas/myapp elevatedb

# Supports 20-30 concurrent users; beyond that, consider MariaDB
forgeos-filedb status
```

See [docs/elevatedb.md](docs/elevatedb.md) for full details.

---

## GDPR / Privacy

- No age verification
- No backdoors, no telemetry, no phone-home
- Audit logs exportable (`ausearch -m USER_AUTH`)
- Log retention configurable (default 90 days)
- No advertising, no tracking

---

## License

GPL-3.0 — see [LICENSE](LICENSE).

ForgeOS is free and open source. Commercial deployments are welcome; contributions back are appreciated but not required.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
