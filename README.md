# ForgeOS

**Open-source NAS and home server platform for Ubuntu/Debian.**  
Built natively on the OS — not a repackaged distro.

---

## Overview

ForgeOS transforms a bare Ubuntu 22.04/24.04 or Debian 12 installation into a fully-featured NAS and home server with a web-based desktop interface, modular installer, and a complete CLI toolkit.

It is designed for both homelabs and small businesses. Enterprise features (HIPAA compliance, LDAP/SSO, ElevateDB file-database coordination) are optional modules — a homelab user running the wizard never sees them.

---

## Features

### Storage
- **ForgeRAID** — mdadm + LVM + btrfs. Mixed-size drives. Supports RAID 1/5/6/10 and JBOD
- **Drive classification** — automatic HDD / SSD / NVMe / USB detection, displayed in the Web UI
- **Cache drives** — bcache SSD/NVMe caching in front of HDD pools (writeback, writethrough, writearound)
- **Hot-swap** — udev-driven detection, SMART health check on insert, auto-rejoin to degraded arrays
- **SMART predictive failure** — smartd continuous monitoring, four alert levels (OK / WARN / PREDICT / ERR), tray indicators in the Web UI
- **btrfs snapshots** — Snapper timeline schedules, Web UI snapshot browser, one-click restore

### Networking
- **Reverse proxy** — nginx with automatic Let's Encrypt certificates
- **VPN** — WireGuard server with per-client QR code generation; optional Netbird mesh
- **mDNS** — Avahi broadcasts `hostname.local` and all ForgeOS services on the LAN

### File Sharing
- **SMB** — Samba 4, SMB3, macOS Time Machine, five share templates
- **NFS v4** — v3 disabled, high-performance for Linux/ESXi clients
- **FTPS** — ProFTPD with mandatory TLS, passive mode for NAT
- **WebDAV** — nginx-backed, Windows network drive compatible
- **FileBrowser** — web-based drag-drop file manager

### File-Based Database Support (ForgeFileDB)
- Coordinates concurrent access for **ElevateDB, DBISAM, dBase, FoxPro, MS Access, NexusDB, SQLite, Firebird, Paradox**
- Prevents SMB oplock corruption without any client-side changes
- Versioned snapshots with one-click restore (btrfs instant or rsync fallback)
- mDNS discovery on `_forgeos-filedb._tcp` and `_edb-server._tcp`
- Web UI at `https://filedb.domain`

### Containers
- **Docker CE** — official repo, overlay2 storage, Compose v2
- **Incus** — LXC/LXD successor for system containers and VMs

### AI / Compute
- **GPU drivers** — NVIDIA (ubuntu-drivers + CUDA + container toolkit), AMD (ROCm + VA-API), Intel Arc (i915/xe + Quick Sync)
- **Google Coral TPU** — PCIe single and dual support via `gasket`+`apex` kernel modules (KyleGospo fork for kernel 6.x compatibility). Frigate NVR compose auto-generated
- **Frigate NVR** — Docker Compose with correct TPU device passthrough, auto-configured camera config template

### Security
- UFW (default deny inbound) + Fail2ban + CrowdSec
- AppArmor (enforcing) + auditd + AIDE file integrity + rkhunter
- Mandatory TLS everywhere — no plaintext protocols
- GDPR compliant: no age verification, no backdoors, exportable audit logs
- Optional HIPAA compliance module (auditd rules, gocryptfs ePHI, 6-year log retention)

### Monitoring
- Prometheus + Grafana + Alertmanager (Docker Compose)
- node_exporter, smartctl_exporter
- Gotify push notifications + Apprise multi-channel (Discord, Slack, Telegram, etc.)
- Fan control via lm-sensors + fancontrol

### Authentication (optional)
- **lldap** — lightweight LDAP, replaces OpenLDAP complexity
- **Authentik** — OIDC/OAuth2 SSO portal with TOTP + WebAuthn 2FA
- nginx `forward_auth` snippet for protecting any service

### Mail (optional)
- Postfix + Dovecot + Rspamd + ClamAV + SOGo webmail
- DKIM auto-generation, DNS record printer
- Mandatory TLS on all ports

### Backup
- **Restic** — AES-256 encrypted, deduplicated, to local + cloud
- **Rclone crypt** — client-side encrypted sync to B2/S3/R2/SFTP
- Systemd timers: Restic 02:00, Rclone 04:30, both with 1h random delay

### Cloud Storage (optional)
- **MinIO** — self-hosted S3 compatible, works with any AWS SDK
- Rclone encrypted cloud sync wizard for Backblaze B2, AWS S3, Cloudflare R2

### Applications
- **OnlyOffice** — self-hosted office suite with **Microsoft Core Fonts** pre-installed for layout-accurate document rendering
- **Immich** — self-hosted Google Photos with GPU-accelerated AI face/object recognition

### Web UI
- Industrial Steel / Forge Orange desktop interface
- KDE/Windows-style taskbar (Dashboard, Storage, Network, Settings)
- Live drive health with pool grouping, SMART heat maps, hot-swap indicators
- nginx proxy manager, Samba share manager, container view
- ForgeFileDB panel with live connection monitoring and snapshot browser
- 4 wallpapers (dark forge, dark circuit, light blueprint, light dawn)

---

## Requirements

| Component | Minimum | Recommended |
|---|---|---|
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
git clone https://github.com/YOUR_USERNAME/forgeos.git
cd forgeos
sudo bash install/install.sh
```

The interactive wizard runs in about 15–30 minutes depending on selected modules and internet speed. All modules are idempotent — safe to re-run.

### Unattended install (CI / automated)

```bash
export FORGEOS_HOSTNAME=nas
export FORGEOS_DOMAIN=home.example.com
export FORGEOS_ADMIN_USER=admin
export FORGEOS_TIMEZONE=America/Chicago
sudo bash install/install.sh --unattended --modules=base,storage,docker,security,proxy,fileshare,backup
```

---

## Repository Structure

```
forgeos/
├── install/
│   ├── install.sh              # Master installer (interactive wizard)
│   ├── lib/
│   │   ├── common.sh           # Shared functions (logging, apt, services)
│   │   └── detect.sh           # Hardware detection (CPU/GPU/NIC/disk)
│   └── modules/
│       ├── 01-base.sh          # Core packages, sysctl, SSH hardening
│       ├── 02-network.sh       # Static IP, mDNS, DNS, bonding
│       ├── 03-storage.sh       # ForgeRAID (mdadm+LVM+btrfs)
│       ├── 03-storage-hotswap.sh  # Hot-swap udev, SMART daemon
│       ├── 03c-drive-types.sh  # HDD/SSD/NVMe/USB detection, bcache
│       ├── 04-docker.sh        # Docker CE + Incus
│       ├── 05-coral-tpu.sh     # Google Coral PCIe (single + dual)
│       ├── 06-gpu.sh           # NVIDIA/AMD/Intel Arc drivers
│       ├── 07-security.sh      # UFW, Fail2ban, CrowdSec, AppArmor
│       ├── 09-monitoring.sh    # Prometheus + Grafana + Alertmanager
│       ├── 10-fileshare.sh     # NFS v4, ProFTPD, WebDAV, FileBrowser
│       ├── 10b-samba-db.sh     # Samba + ElevateDB/file-DB templates
│       ├── 10c-forgeos-filedb.sh  # ForgeFileDB installer
│       ├── 11-vpn.sh           # WireGuard server + Netbird
│       ├── 12-reverse-proxy.sh # nginx + Let's Encrypt
│       ├── 13-ldap-oidc.sh     # lldap + Authentik SSO
│       ├── 14-mail.sh          # Postfix + Dovecot + SOGo
│       ├── 15-backup.sh        # Restic + Rclone + Snapper
│       ├── 16-cloud-storage.sh # MinIO S3 + Rclone cloud sync
│       ├── 17-hipaa.sh         # HIPAA compliance mode
│       ├── 18-apps.sh          # OnlyOffice + MS Fonts + Immich
│       └── 99-finalize.sh      # API service, summary
├── src/
│   ├── forgeos-api.py          # FastAPI backend (REST + WebSocket)
│   └── forgeos-filedb.py       # ForgeFileDB daemon
├── web/
│   ├── desktop/
│   │   └── index.html          # ForgeOS desktop Web UI
│   ├── filedb.html             # ForgeFileDB management UI
│   └── wallpapers/             # 4 SVG wallpapers
├── docs/
│   ├── post-install.md         # First-boot checklist
│   ├── drive-setup.md          # ForgeRAID + cache setup guide
│   ├── elevatedb.md            # ElevateDB/Atrex configuration
│   ├── coral-tpu.md            # Coral TPU troubleshooting
│   └── hipaa.md                # HIPAA module reference
├── test-forgeos.sh             # End-to-end test suite
├── .github/
│   └── workflows/
│       └── ci.yml              # Lint + shellcheck CI
├── .gitignore
├── LICENSE                     # GPL-3.0
└── README.md
```

---

## Post-Install Access

After the installer completes, it prints a summary with all URLs and the initial admin password. Example:

| Service | URL |
|---|---|
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

Results are saved to `/var/log/forgeos/test-report-YYYYMMDD-HHMMSS.json`.

---

## Google Coral TPU Notes

The official Google `gasket-dkms` package from `packages.cloud.google.com` **does not build on Linux kernel 6.x+**. ForgeOS uses the community-maintained [KyleGospo/gasket-dkms](https://github.com/KyleGospo/gasket-dkms) fork which contains the necessary kernel 6.x compatibility patches.

**Single TPU** (M.2 or PCIe): creates `/dev/apex_0`  
**Dual TPU** (M.2 dual card): creates `/dev/apex_0` + `/dev/apex_1` — requires PCIe x2 bifurcation support in your motherboard M.2 slot.

If `/dev/apex_*` doesn't appear after reboot:
```bash
forgeos-coral fix-aspm   # Adds pcie_aspm=off to GRUB
# then reboot
```

---

## ElevateDB / Atrex / File-Based Database Notes

ForgeFileDB coordinates concurrent SMB access to file-based database engines. No changes are needed to the client application — it continues using its standard local/file session mode.

For ElevateDB applications (Atrex, etc.):
```bash
# Create a share with all oplocks disabled (prevents corruption)
forgeos-samba create myapp /srv/nas/myapp elevatedb

# Supports 20-30 concurrent users; beyond that, consider MariaDB migration
forgeos-filedb status
```

See [docs/elevatedb.md](docs/elevatedb.md) for full details.

---

## GDPR / Privacy

- No age verification of any kind
- No backdoors, no telemetry, no phone-home
- Audit logs are exportable on request (`ausearch -m USER_AUTH`)
- Log retention configurable (default 90 days)
- No advertising, no tracking

---

## License

GPL-3.0 — see [LICENSE](LICENSE).

ForgeOS is free and open source. If you deploy it commercially, contributions back to the project are appreciated but not required.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
