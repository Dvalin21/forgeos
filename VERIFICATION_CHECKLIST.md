# ForgeOS Functional Verification Checklist
# Run this to verify all features work

## WebGUI Access
- [ ] URL: http://10.0.0.239:5080/desktop/index.html
- [ ] Login page loads
- [ ] Dashboard displays
- [ ] All tabs navigable

## Features to Verify

### Taskbar (4 items)
- [ ] Forge logo clickable
- [ ] Window list shows
- [ ] System metrics display
- [ ] Power button works

### Dashboard Tab
- [ ] System overview displays
- [ ] CPU chart renders
- [ ] Memory usage shows
- [ ] Disk I/O displays
- [ ] Network traffic shows

### Network Tab
- [ ] IP address shown
- [ ] Connections list
- [ ] Firewall status
- [ ] VPN peers display

### Storage Tab
- [ ] Drive list populates
- [ ] RAID pools show
- [ ] SMART data displays
- [ ] Hot-swap status

### Docker Tab
- [ ] Container list
- [ ] Image list
- [ ] Start/Stop works

### SMB Tab  
- [ ] Share list shows
- [ ] Create share works
- [ ] Access control

### Settings Tab
- [ ] System settings load
- [ ] Network config
- [ ] Auto-update status

### Security Tab
- [ ] Firewall rules display
- [ ] Fail2ban status
- [ ] Auth settings

### Logs Tab (WebSocket)
- [ ] Live log streaming
- [ ] Filter works

## API Endpoints to Test
- [ ] GET /api/health
- [ ] GET /api/storage/disks
- [ ] GET /api/storage/pools
- [ ] GET /api/network/interfaces
- [ ] GET /api/docker/containers

## Installer Modules (19)
- [ ] 01-base.sh runs
- [ ] 02-network.sh runs
- [ ] 03-storage.sh runs
- [ ] 04-docker.sh runs
- [ ] etc...

## Manual Tests Required
1. Create a storage pool
2. Add a drive to pool
3. Create an SMB share
4. Set up a user
5. Configure firewall rule
6. Start a Docker container

## Report Format
For each test:
- PASS: [feature] works
- FAIL: [feature] broken - [error]