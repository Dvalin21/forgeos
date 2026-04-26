# ForgeOS Comprehensive Redesign Specification

> **Version:** 2.0  
> **Date:** 2026-04-26  
> **Status:** Design approved - Ready for implementation

---

## 1. Executive Summary

ForgeOS 2.0 represents a complete redesign and feature completion based on:
- Original specification from README.md (features not yet implemented)
- User requirements captured 2026-04-26
- All missing features from v1.0 now prioritized

### Core Philosophy
- **ALL non-Docker features MUST be configurable via WebGUI**
- **If an app has no WebGUI, create one in ForgeOS**
- First-boot installer includes ALL dependencies
- No ISO build until full feature complete

---

## 2. WebGUI Redesign

### 2.1 Design Direction

**Hybrid aesthetic sources:**
- **ZimaOS** - Modern, clean, app-centric tiles
- **Synology** - Feature-rich, familiar, professional
- **Proxmox custom dashboards** - Technical but accessible, data-dense widgets
- **Homarr** - Dark, widget-based, draggable panels

### 2.2 Visual Style

| Element | Design Choice |
|---------|-------------|
| Theme | Dark mode primary (ZimaOS-inspired), Light mode toggle |
| Navigation | Left sidebar collapsible (Proxmox), top bar for context |
| Dashboard | Widget-based grid (Homarr-style draggable) |
| Cards | Rounded corners (Synology), subtle shadows |
| Colors | Forge orange accent, steel blue secondary, green/red/yellow status |
| Typography | Clean sans-serif, monospace for technical data |
| Wallpapers | New designs - abstract tech, nature+tech blend |

### 2.3 Window Structure

| Window | Purpose | Features |
|--------|---------|----------|
| Dashboard | System overview | CPU/RAM/Disk widgets, active alerts, quick actions |
| Storage | Pool management | Drive health heat map, pool status, snapshots |
| Docker | Container management | App grid with icons, one-click install |
| Network | All networking | Interfaces, VPN, proxy, firewall |
| Shares | File sharing | SMB/NFS/FTP/WebDAV management |
| Backup | All backup tools | Borg/Restic/RClone/MinIO/FOG unified panel |
| Imaging | System recovery | FOG management, Clonezilla ISO download |
| Mail | Mail server | MailCow status, queue, logs |
| Auth | Users/SSO | LDAP, SSO, local users |
| Settings | System config | All settings unified |

### 2.4 Taskbar

| Pin | Function |
|-----|----------|
| Dashboard | Main system overview widget |
| Apps | Docker app grid (Homarr integration) |
| Storage | Pool management + SMART |
| Settings | Full system configuration |

---

## 3. Wallpaper Redesign

### 3.1 New Design Direction

Current wallpapers (dark-forge, dark-circuit, light-blueprint, light-dawn) to be replaced with fresh designs.

### 3.2 Proposed Themes

| Wallpaper | Description |
|----------|-------------|
| Nebula | Deep space with subtle forge orange accents |
| Aurora | Northern lights + server rack subtle glow |
| Forge 2.0 | Metallic/industrial but modernized |
| Zen Garden | Minimal tech + nature blend |
| Dark Mode Default | Deep void with subtle grid pattern |

### 3.3 Technical Requirements

- Optimized for full-screen (1920x1080 up to 4K)
- SVG format where possible
- File size: < 500KB each
- Include both light and dark variants

---

## 4. Backup & Imaging Suite

### 4.1 Complete Tool Stack

| Tool | Purpose | WebGUI Required | Status |
|------|---------|-----------------|--------|
| **Borg** | Local encrypted backup | Yes - create in ForgeOS | New |
| **Restic** | Cloud encrypted backup | Yes - create in ForgeOS | New |
| **RClone** | Cloud sync | Yes - create in ForgeOS | New |
| **MinIO** | Local S3 storage | Yes - expand console | Existing |
| **Rsync** | Live directory sync | Yes - create in ForgeOS | New |
| **FOG** | Network imaging | Yes - create in ForgeOS | New |
| **Clonezilla** | Recovery ISO | Download link only | New |

### 4.2 Unified Backup Panel

Each tool needs:
- Create/manage backup jobs
- View/restore from backups
- Schedule management
- Alert configuration
- Storage usage analytics

### 4.3 System Imaging (FOG)

| Feature | Implementation |
|--------|----------------|
| Web interface | Integrated into ForgeOS WebGUI |
| PXE boot | Network configuration |
| Image storage | On ForgeOS storage pools |
| Deploy workflow | Web → Network → Target machine |
| Recovery ISO | Clonezilla download link |

---

## 5. Docker Integration

### 5.1 Docker Dashboard

**Purpose:** Manage all Docker apps from single WebGUI panel

| Feature | Implementation |
|---------|----------------|
| App browser | Curated list of common apps (click to install) |
| Icon auto-import | Apps get dashboard icons automatically |
| Container list | All containers with status/start/stop |
| Compose support | YAML editor + parse existing |
| Resource monitoring | CPU/RAM/disk per container |
| Logs viewer | Web-based log viewer |
| Volume management | Create/attach/detach volumes |
| Network management | Docker networks |

### 5.2 Native Apps (Auto-installed)

| App | Installation | Dashboard Icon |
|-----|--------------|----------------|
| **Homarr** | Docker auto-install | ✓ Required |
| Portainer | Docker auto-install | ✓ Required |
| Yacht | Alternative to Portainer | Optional |

### 5.3 App Browser Categories

```
- Media: Jellyfin, Plex, Radarr, Sonarr, Lidarr, qBittorrent
- Home Automation: Home Assistant, Frigate
- Productivity: OnlyOffice, Immich, Paperless-NGX
- Networking: AdGuard, Traefik, Nginx Proxy Manager
- Monitoring: Prometheus, Grafana, Uptime Kuma
- Security: Authentik, Vaultwarden
- Cloud: MinIO, Nextcloud
```

---

## 6. Mail Server

### 6.1 Installation Approach

**Primary: MailCow** - Full-featured mail server

| Consideration | Solution |
|---------------|-----------|
| Docker from mailcow/docker-mailcow | Clone repo, docker-compose up |
| WebGUI | Integrate into ForgeOS (MailCow UI) |
| Update management | Built-in MailCow updater |
| Storage | On ForgeOS pools |

### 6.2 Alternative: Traditional Stack

If MailCow not desired:
- Postfix + Dovecot + Rspamd + SOGo
- Requires more manual configuration

### 6.3 Integration Points

- Status panel in WebGUI
- Queue monitoring
- Log viewer
- Quick actions (restart services)

---

## 7. First-Boot Installer

### 7.1 Complete Dependency Set

**ALL software dependencies installed in first run:**

| Category | Packages |
|----------|----------|
| Base | build-essential, curl, wget, git, jq, htop, tmux |
| Storage | mdadm, lvm2, btrfs-progs, smartmontools |
| Docker | docker.io, docker-compose |
| Networking | nginx,certbot,wireguard |
| Backup | borgbackup, restic, rclone, rsync |
| Monitoring | prometheus, grafana, node-exporter |
| Security | ufw, fail2ban, crowdsec |
| Development | python3, python3-pip, nodejs, npm |
| Hardware | lm-sensors, smartctl, nvme-cli |
| Filesystem tools | cifs-utils, nfs-kernel-server, smbclient |

### 7.2 Module Structure

Each component installed on-demand via interactive wizard:

```
1. Base system (required)
2. Storage pools
3. Docker + Container runtime
4. Network services (VPN, proxy)
5. File sharing (SMB/NFS/FTP)
6. Backup suite
7. Mail server
8. Authentication (LDAP/SSO)
9. Monitoring
10. GPU drivers (NVIDIA/AMD/Intel)
11. Applications (optional)
```

---

## 8. Feature Gap Analysis

### 8.1 Original Spec (README.md) vs Current

| Feature | README | Current WebUI | Gap |
|---------|--------|----------------|-----|
| ForgeRAID | ✓ | Partial | Re-implement full |
| Drive classification | ✓ | - | New |
| Cache drives (bcache) | ✓ | - | New |
| Hot-swap | ✓ | - | New |
| SMART monitoring | �� | Partial | Expand |
| btrfs snapshots | ✓ | - | New |
| WireGuard VPN | ✓ | Partial | Expand |
| nginx proxy | ✓ | ✓ | Keep |
| SMB/NFS/FTP | ✓ | - | New |
| FileBrowser | ✓ | - | New |
| ForgeFileDB | ✓ | - | Integrate |
| Docker | ✓ | Partial | Expand |
| Incus | ✓ | - | Add |
| GPU drivers | ✓ | - | Add |
| Coral TPU | ✓ | - | Add |
| UFW/Fail2ban | ✓ | Partial | Expand |
| Prometheus/Grafana | ✓ | - | New |
| LDAP/SSO | ✓ | - | Add |
| Mail server | ✓ | - | Add |
| Restic backup | ✓ | - | New |
| MinIO | ✓ | Partial | Expand |
| Homarr | ✓ | - | Add |
| Immich | ✓ | - | Add |
| OnlyOffice | ✓ | - | Add |

### 8.2 New Features for 2.0

| Feature | Purpose |
|---------|----------|
| Borg backup | Local encrypted backup |
| RClone sync | Cloud synchronization |
| Rsync | Live directory sync |
| FOG imaging | Network system imaging |
| System imaging | Full disaster recovery |
| App browser | One-click Docker installs |
| Unified backup panel | All backup tools in one place |
| Complete redesign | Full WebGUI overhaul |
| New wallpapers | Design refresh |

---

## 9. GPU Support

### 9.1 Arc A770 Integration

**Timeline:** User getting Arc A770 16GB in ~1 week

| Driver | Status | Notes |
|--------|--------|-------|
| Intel Xe Driver | Ready | i915/xe in kernel 6.12+ |
| VA-API | Ready | Video encode/decode |
| Quick Sync | Ready | Transcoding support |
| Compute | Ready | GPU compute workloads |

### 9.2 Fallback for Model Limitation

If OpenCode usage limits hit:
- Switch to alternative model
- Keep core features prioritized

---

## 10. Implementation Priorities

### Phase 1: Core (Must have)
1. WebGUI complete redesign
2. All backup tools with WebGUI
3. Docker dashboard with app browser
4. First-boot with all dependencies

### Phase 2: Integration
5. Homarr auto-install
6. FOG imaging integration
7. MailCow installation
8. Unified settings panel

### Phase 3: Polish
9. New wallpapers
10. Feature completion
11. Testing and validation

---

## 11. Validation Checklist

Before claiming complete:
- [ ] All backup tools accessible from WebGUI
- [ ] Docker apps install with one click, show on dashboard
- [ ] Homarr auto-installed and accessible
- [ ] FOG can capture/deploy system images
- [ ] First-boot installs ALL dependencies
- [ ] All original spec features now implemented
- [ ] WebGUI fully functional (no CLI required for config)
- [ ] Wallpapers updated

---

## 12. File Structure

```
forgeos/
├── docs/
│   ├── superpowers/
│   │   ├── specs/
│   │   │   └── 2026-04-26-forgeos-redesign.md  ← This spec
│   │   └── plans/
│   │       └── [implementation plans]
│   └── [existing docs]
├── web/
│   ├── desktop/
│   │   └── index.html  ← Redesigned WebUI
│   └── wallpapers/  ← New designs
├── install/
│   ├── modules/  ← Updated with all dependencies
│   └── install.sh
└── src/
    ├── forgeos-api.py  ← Expanded API
    └── [backup tool wrappers]
```

---

## 13. Design Self-Review

- [x] Placeholder scan: No TODOs or TBDs
- [x] Internal consistency: All sections aligned
- [x] Scope: Comprehensive for single implementation plan
- [x] Ambiguity: All requirements explicit
- [x] Feature coverage: All spec items addressed

---

**Spec Status:** ✓ Ready for implementation  
**Saved to:** `docs/superpowers/specs/2026-04-26-forgeos-redesign.md`