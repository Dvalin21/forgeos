# ForgeOS v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement complete ForgeOS v2.0 redesign with all backup tools, Docker dashboard, and WebGUI overhaul

**Architecture:** Modular implementation - each task produces working software independently. Start with first-boot dependencies, then WebGUI core, then tool integrations.

**Tech Stack:** HTML/CSS/JS (WebUI), Python/FastAPI (Backend), Bash (Installer), Docker (Container runtime)

---

## Phase 1: Foundation

### Task 1: First-Boot Complete Dependencies

**Files:**
- Create: `install/modules/01-base.sh` (update complete dependency list)
- Modify: `install/install.sh` (confirm all deps installed)

- [ ] **Step 1: Verify current install.sh base module**

Read: `/home/keith/forgeos-review/install/modules/01-base.sh`

- [ ] **Step 2: Update with complete dependency list**

Create complete package list:
```bash
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential curl wget git jq htop tmux \
    mdadm lvm2 btrfs-progs smartmontools \
    docker.io docker-compose-plugin \
    nginx certbot wireguard-tools \
    borgbackup restic rclone rsync \
    prometheus-node-exporter \
    ufw fail2ban \
    python3 python3-pip python3-venv \
    nodejs npm \
    lm-sensors smartctl nvme-cli \
    cifs-utils nfs-kernel-server smbclient \
    acpid lm-sensors
```

- [ ] **Step 3: Add dependency verification to install.sh**

Add function to verify all packages installed before proceeding.

- [ ] **Step 4: Test on clean system**

Verify all packages install without error.

- [ ] **Step 5: Commit**

```bash
git add install/modules/01-base.sh install/install.sh
git commit -m "feat: Complete first-boot dependency set"
```

---

### Task 2: Install Module Restructure

**Files:**
- Create: `install/modules/XX-backup-suite.sh`
- Create: `install/modules/XX-docker-dashboard.sh`
- Create: `install/modules/XX-imaging.sh`

- [ ] **Step 1: Create backup suite module**

File: `install/modules/20-backup-suite.sh`
```bash
#!/bin/bash
# Backup Suite: Borg, Restic, RClone, MinIO, Rsync
# Creates WebGUI endpoints for each

install_borg() {
    apt-get install -y borgbackup
}

install_restic() {
    apt-get install -y restic
}

install_rclone() {
    curl -s https://rclone.org/install.sh | sudo bash
}

install_minio() {
    docker run -d --name minio \
        -p 9000:9000 -p 9001:9001 \
        -e MINIO_ROOT_USER=minioadmin \
        -e MINIO_ROOT_PASSWORD=minioadmin \
        -v minio-data:/data \
        minio/minio server /data --console-address ":9001"
}

install_rsync() {
    apt-get install -y rsync
}
```

- [ ] **Step 2: Create Docker dashboard module**

File: `install/modules/21-docker-dashboard.sh`
```bash
#!/bin/bash
# Docker Dashboard with Homarr auto-install

install_homarr() {
    docker run -d --name homarr \
        -p 3000:3000 \
        -v homarr-config:/config \
        -e TZ=UTC \
        ghcr.io/ax翰ent/homarr:latest
}

install_portainer() {
    docker run -d --name portainer \
        -p 9000:9000 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v portainer-data:/data \
        portainer/portainer-ce:latest
}
```

- [ ] **Step 3: Create imaging module**

File: `install/modules/22-imaging.sh`
```bash
#!/bin/bash
# FOG Project - Network Imaging

install_fog() {
    # Clone FOG repository
    git clone https://github.com/FOGProject/fogproject.git /opt/fog
    # Run FOG installation
    cd /opt/fog/bin
    ./installfog.sh
}
```

- [ ] **Step 4: Commit**

```bash
git add install/modules/20-backup-suite.sh install/modules/21-docker-dashboard.sh install/modules/22-imaging.sh
git commit -m "feat: Add backup suite, Docker dashboard, and imaging modules"
```

---

## Phase 2: WebGUI Core

### Task 3: WebGUI Redesign - Core Structure

**Files:**
- Modify: `web/desktop/index.html` (complete redesign)
- Create: `web/desktop/css/forgeos.css`
- Create: `web/desktop/js/forgeos.js`

- [ ] **Step 1: Create new CSS design system**

File: `web/desktop/css/forgeos.css`
```css
/* ForgeOS v2.0 Design System */

:root {
  /* Color palette - ZimaOS + Synology hybrid */
  --bg-void: #0a0a0f;
  --bg-base: #121218;
  --bg-surface: #1a1a24;
  --bg-elevated: #222230;
  --bg-card: #282836;
  
  --accent-primary: #e85d04;  /* Forge orange */
  --accent-secondary: #4a8ab0; /* Steel blue */
  --accent-success: #3daa60;
  --accent-warning: #d4860a;
  --accent-danger: #cc3344;
  
  --text-primary: #f0f0f4;
  --text-secondary: #a0a0b0;
  --text-muted: #606070;
  
  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  
  /* Typography */
  --font-display: 'Inter', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  
  /* Borders */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  
  /* Shadows */
  --shadow-sm: 0 2px 4px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 8px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.5);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-body);
  background: var(--bg-void);
  color: var(--text-primary);
  min-height: 100vh;
}
```

- [ ] **Step 2: Create sidebar navigation**

File: `web/desktop/js/forgeos.js`
```javascript
// ForgeOS v2.0 Navigation

const NAV_ITEMS = [
  { id: 'dashboard', icon: '◈', label: 'Dashboard' },
  { id: 'storage', icon: '⬡', label: 'Storage' },
  { id: 'docker', icon: '◉', label: 'Apps' },
  { id: 'network', icon: '⬢', label: 'Network' },
  { id: 'backup', icon: '◫', label: 'Backup' },
  { id: 'shares', icon: '▤', label: 'Shares' },
  { id: 'mail', icon: '✉', label: 'Mail' },
  { id: 'auth', icon: '⚿', label: 'Auth' },
  { id: 'settings', icon: '⚙', label: 'Settings' }
];

function renderSidebar() {
  const nav = document.getElementById('nav-sidebar');
  NAV_ITEMS.forEach(item => {
    const btn = document.createElement('button');
    btn.className = 'nav-item';
    btn.dataset.id = item.id;
    btn.innerHTML = `<span class="nav-icon">${item.icon}</span><span class="nav-label">${item.label}</span>`;
    btn.onclick = () => openPanel(item.id);
    nav.appendChild(btn);
  });
}
```

- [ ] **Step 3: Verify existing HTML integrates**

Run: `head -50 web/desktop/index.html`

- [ ] **Step 4: Commit**

```bash
git add web/desktop/css/forgeos.css web/desktop/js/forgeos.js
git commit -m "feat: Add v2.0 design system"
```

---

## Phase 3: Docker Integration

### Task 4: Docker App Browser

**Files:**
- Modify: `src/forgeos-api.py` (add Docker endpoints)
- Modify: `web/desktop/index.html` (add Docker panel)

- [ ] **Step 1: Add Docker API endpoints**

File: `src/forgeos-api.py` - Add functions:
```python
@app.get("/api/docker/apps")
async def get_docker_apps():
    """Curated app list with one-click install"""
    return {
        "apps": [
            {"name": "Homarr", "image": "ghcr.io/ax翰ent/homarr:latest", "port": 3000},
            {"name": "Portainer", "image": "portainer/portainer-ce:latest", "port": 9000},
            {"name": "Jellyfin", "image": "jellyfin/jellyfin:latest", "port": 8096},
            {"name": "AdGuard", "image": "adguard/adguardhome:latest", "port": 3000},
            {"name": "Nextcloud", "image": "nextcloud:latest", "port": 80},
            {"name": "MinIO", "image": "minio/minio:latest", "port": 9000}
        ]
    }

@app.post("/api/docker/install")
async def install_docker_app(app: str, image: str):
    """Install Docker app from curated list"""
    # Validate against app list
    # Run docker run with proper parameters
    return {"status": "installed", "app": app}
```

- [ ] **Step 2: Add Docker panel to WebUI**

Add to `index.html`:
```html
<div id="panel-docker" class="panel">
  <div class="panel-header">
    <h2>Apps</h2>
    <button class="btn-primary" onclick="showAppBrowser()">+ Add App</button>
  </div>
  <div id="app-grid" class="app-grid"></div>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add src/forgeos-api.py web/desktop/index.html
git commit -m "feat: Docker app browser with one-click install"
```

---

## Phase 4: Backup Suite Integration

### Task 5: Unified Backup Panel

**Files:**
- Modify: `src/forgeos-api.py` (add backup endpoints)
- Modify: `web/desktop/index.html` (add backup panel)

- [ ] **Step 1: Add backup API**

```python
@app.get("/api/backup/status")
async def get_backup_status():
    """Get status of all backup tools"""
    return {
        "borg": {"installed": check_command("borg"), "jobs": []},
        "restic": {"installed": check_command("restic"), "jobs": []},
        "rclone": {"installed": check_command("rclone"), "jobs": []},
        "rsync": {"installed": check_command("rsync"), "jobs": []},
        "fog": {"installed": check_service("fog"), "images": []}
    }

@app.post("/api/backup/borg/create")
async def create_borg_backup(destination: str, source: str):
    """Create new Borg backup job"""
    cmd = f"borg create {destination}::{name} {source}"
    return {"status": "created", "job": name}
```

- [ ] **Step 2: Add backup panel**

```html
<div id="panel-backup" class="panel">
  <div class="backup-tabs">
    <button class="tab active" onclick="showBackupTool('borg')">Borg</button>
    <button class="tab" onclick="showBackupTool('restic')">Restic</button>
    <button class="tab" onclick="showBackupTool('rclone')">RClone</button>
    <button class="tab" onclick="showBackupTool('fog')">Imaging</button>
  </div>
  <div id="backup-content"></div>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add src/forgeos-api.py web/desktop/index.html
git commit -m "feat: Unified backup panel with all tools"
```

---

## Phase 5: Imaging Integration

### Task 6: FOG Integration

**Files:**
- Modify: `src/forgeos-api.py` (add FOG endpoints)
- Modify: `web/desktop/index.html` (add imaging panel)

- [ ] **Step 1: Add FOG API**

```python
@app.get("/api/imaging/status")
async def get_imaging_status():
    """Get FOG imaging system status"""
    return {
        "fog": {"running": check_service("fog")},
        "images": list_fog_images(),
        "hosts": list_fog_hosts()
    }

@app.post("/api/imaging/capture")
async def capture_image(hostname: str, image_name: str):
    """Capture system image via network boot"""
    return {"status": "capturing", "host": hostname, "image": image_name}

@app.post("/api/imaging/deploy")
async def deploy_image(image_name: str, target_host: str):
    """Deploy image to target machine"""
    return {"status": "deploying", "image": image_name, "target": target_host}
```

- [ ] **Step 2: Add imaging panel**

- [ ] **Step 3: Commit**

---

## Phase 6: Mail Server

### Task 7: MailCow Integration

**Files:**
- Create: `install/modules/23-mailcow.sh`
- Modify: `src/forgeos-api.py` (add mail endpoints)

- [ ] **Step 1: Create MailCow installer**

```bash
#!/bin/bash
# MailCow Docker installation

install_mailcow() {
    cd /opt
    git clone https://github.com/mailcow/docker-mailcow.git
    cd docker-mailcow
    cp mailcow.conf.sample mailcow.conf
    # Edit mailcow.conf with ForgeOS settings
    docker-compose up -d
}
```

- [ ] **Step 2: Add mail API**

```python
@app.get("/api/mail/status")
async def get_mail_status():
    """Get MailCow status"""
    return {
        "running": check_container("mailcow"),
        "queue": get_mail_queue(),
        "domains": list_domains()
    }
```

- [ ] **Step 3: Commit**

---

## Phase 7: Settings & Polish

### Task 8: Complete Settings Panel

**Files:**
- Modify: `web/desktop/index.html` (add settings panel)

- [ ] **Step 1: Create unified settings**

```html
<div id="panel-settings" class="panel">
  <div class="settings-sections">
    <section id="settings-system">System</section>
    <section id="settings-network">Network</section>
    <section id="settings-storage">Storage</section>
    <section id="settings-security">Security</section>
    <section id="settings-notifications">Notifications</section>
    <section id="settings-backup">Backup Schedule</section>
    <section id="settings-updates">Updates</section>
  </div>
</div>
```

- [ ] **Step 2: Commit**

---

### Task 9: Wallpaper Refresh

**Files:**
- Create: `web/wallpapers/new-wallpapers/`

- [ ] **Step 1: Create new wallpaper SVG**

Design: Nebula-inspired (deep space with forge orange) for default

- [ ] **Step 2: Commit**

---

## Validation

After each task completes, verify:
- [ ] API endpoint responds correctly
- [ ] WebUI panel renders without error
- [ ] No console errors in browser
- [ ] Test passes if applicable

---

## Execution Choice

**Plan complete and saved to `docs/superpowers/plans/2026-04-26-forgeos-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-drivendevelopment

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans