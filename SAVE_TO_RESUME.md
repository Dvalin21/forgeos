# ForgeOS WebUI - Project Notes

## Last Updated: 2026-04-19

## DESIGN LOCKED: Desktop UI with Floating Windows

## Project Structure
```
/home/keith/forgeos-review/
├── web/desktop/index.html     # Main WebUI (1319 lines)
├── src/forgeos-api.py       # Backend API
├── backups/
│   ├── 20260417/            # Original backup
│   └── working/             # Working backups before changes
└── docs/
```

## BACKUP SYSTEM
- Before ANY change: `cp web/desktop/index.html backups/working/$(date +%Y%m%d_%H%M%S)_<desc>.html`
- Revert: `cp backups/working/<backup_file> web/desktop/index.html`

## CURRENT STATE (Original)
- Desktop UI with floating windows (win-dash, win-net)
- 2 windows: System Overview, nginx Reverse Proxy
- 8 tabs: overview, storage, sensors, logs, vhosts, add-vhost, certs, raw-nginx
- Uses orange (#e85d04) as primary color

## FEATURES TO ADD (from API)
| Feature | API Endpoint | Window Needed | Status |
|---------|--------------|---------------|--------|
| Storage/Pools | /api/storage/* | win-dash tab | ✓ exists |
| Docker | /api/docker/* | NEW window | TODO |
| Incus/LXC | /api/incus/* | NEW window | TODO |
| SMB/NFS Shares | /api/samba/* | NEW window | TODO |
| VPN (WireGuard) | /api/network/vpn | NEW window | TODO |
| Reverse Proxy | /api/nginx/* | win-net | ✓ exists |
| Mail Server | /api/mail/* | NEW window | TODO |
| Auth (LDAP) | /api/auth/* | NEW window | TODO |
| Cloud (MinIO) | /api/cloud/* | NEW window | TODO |
| Apps | /api/apps/* | NEW window | TODO |
| Firewall | /api/security/firewall | NEW window | TODO |
| Fail2ban | /api/security/fail2ban | NEW window | TODO |
| Backups | /api/backups/* | NEW window | TODO |
| Settings | /api/settings | NEW window | TODO |

## HOW TO ADD A NEW WINDOW
1. Backup first!
2. Add window HTML (follow existing .win pattern)
3. Add taskbar pin (.tb-pin)
4. Add JavaScript handlers
5. Test

## Server
- Run: `cd /home/keith/forgeos-review/web/desktop && python3 -m http.server 8080`
- Access: http://10.0.0.239:8080

## Complete Build (2026-04-19)
- Total file: 1961 lines
- All 19 tabs functional
- API integration added
- Modals for config

## Features Complete
| Feature | Tab | API Connected | Modal |
|--------|-----|--------------|-------|
| Overview | tab-overview | ✓ via /api/system/stats | - |
| Storage | tab-storage | ✓ via /api/storage/pools | - |
| Docker | tab-docker | ✓ via /api/docker/containers | - |
| Incus | tab-incus | ✓ via /api/incus/containers | - |
| Shares | tab-shares | ✓ via /api/samba/shares | - |
| Network | tab-network | ✓ via /api/network | - |
| VPN | tab-vpn | ✓ via /api/network/vpn | ✓ modal-vpn-peer |
| Proxy | tab-proxy | ✓ via /api/nginx/vhosts | ✓ modal-add-vhost |
| Mail | tab-mail | - | - |
| Cloud | tab-cloud | - | - |
| Apps | tab-apps | - | - |
| Auth | tab-auth | - | - |
| Firewall | tab-firewall | ✓ via /api/security/firewall | ✓ modal-firewall-rule |
| Fail2ban | tab-fail2ban | ✓ via /api/security/fail2ban | - |
| Backups | tab-backups | - | - |
| Settings | tab-settings | ✓ via /api/settings | - |
| Sensors | tab-sensors | ✓ via /api/system/stats | - |
| Logs | tab-logs | - | - |

## JavaScript Functions Added
- forgeAPI(path) - API fetch helper
- fetchStats() - System stats
- fetchStorage() - Storage pools  
- fetchDocker() - Docker containers
- fetchIncus() - Incus containers
- fetchShares() - SMB/NFS shares
- fetchNetwork() - Network interfaces + WireGuard + nginx
- fetchFail2ban() - Fail2ban status
- createVpnPeer() - Add WireGuard peer
- createVhost() - Add nginx vhost
- addFirewallRule() - Add firewall rule
- saveSettings() - Save settings
- fmtBytes() - Format bytes utility
- Modal functions: showAddVpnPeer(), showAddVhost(), showAddFirewallRule(), closeModal()

## Modals Added
- modal-vpn-peer: Create WireGuard peer
- modal-add-vhost: Create nginx vhost
- modal-firewall-rule: Add UFW rule

## Backups
- backups/working/20260419_*_complete_build.html