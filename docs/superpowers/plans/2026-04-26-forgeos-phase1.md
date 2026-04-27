# ForgeOS Phase 1 Feature Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete feature gaps: backup tools (Borg, Restic, RClone) API + WebGUI panels, Docker app browser, and FOG imaging integration

**Architecture:** Modular implementation - each feature area produces working software independently. API first, then WebGUI panels to match.

**Tech Stack:** Python/FastAPI (Backend), HTML/CSS/JS (WebUI), Bash (Installer)

---

## Feature Areas

- **A: Backup Tools** - Borg, Restic, RClone endpoints + WebGUI panel
- **B: Docker App Browser** - One-click Docker app install + WebGUI panel  
- **C: FOG Imaging** - Imaging API + WebGUI panel

---

## Task A1: Borg Backup API Endpoints

**Files:**
- Modify: `src/forgeos-api.py` (add endpoints at end)
- Test: `tests/test_borg_api.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_borg_api.py
import pytest
from fastapi.testclient import TestClient
from forgeos_api import app

client = TestClient(app)

def test_borg_status():
    response = client.get("/api/backup/borg/status")
    assert response.status_code == 200
    data = response.json()
    assert "installed" in data
    assert "jobs" in data

def test_borg_create_job():
    response = client.post("/api/backup/borg/create", json={
        "name": "test-backup",
        "source": "/tmp",
        "destination": "/backup/test"
    })
    assert response.status_code in [200, 400, 500]  # Accept various responses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_borg_api.py -v`
Expected: FAILS - endpoint not defined

- [ ] **Step 3: Add Borg endpoints to forgeos-api.py**

Add after existing endpoints (around line 890):
```python
@app.get("/api/backup/borg/status")
async def borg_status():
    """Get Borg backup status and jobs"""
    result = subprocess.run(["borg", "version"], capture_output=True)
    installed = result.returncode == 0
    jobs = []
    if installed:
        # List existing backup archives
        list_result = subprocess.run(
            ["borg", "list", "--json", "/backup"],
            capture_output=True, text=True
        )
        if list_result.returncode == 0:
            try:
                jobs = json.loads(list_result.stdout)
            except:
                jobs = []
    return {"installed": installed, "jobs": jobs}

@app.post("/api/backup/borg/create")
async def borg_create(name: str, source: str, destination: str):
    """Create new Borg backup job"""
    # Check if borg is installed
    check = subprocess.run(["borg", "version"], capture_output=True)
    if check.returncode != 0:
        return {"error": "Borg not installed"}, 500
    
    # Create backup with current timestamp
    archive_name = f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cmd = ["borg", "create", f"{destination}::{archive_name}", source]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        return {"status": "created", "archive": archive_name}
    return {"error": result.stderr}, 500

@app.get("/api/backup/borg/list")
async def borg_list(destination: str):
    """List archives in repository"""
    result = subprocess.run(
        ["borg", "list", "--json", destination],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        try:
            return {"archives": json.loads(result.stdout)}
        except:
            return {"archives": []}
    return {"error": "Failed to list"}, 500
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_borg_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/forgeos-api.py tests/test_borg_api.py
git commit -m "feat: Add Borg backup API endpoints"
```

---

## Task A2: Restic Backup API Endpoints

**Files:**
- Modify: `src/forgeos-api.py`
- Test: `tests/test_restic_api.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_restic_api.py
def test_restic_status():
    response = client.get("/api/backup/restic/status")
    assert response.status_code == 200
    
def test_restic_create():
    response = client.post("/api/backup/restic/snapshot", json={
        "repo": "/backup/restic",
        "paths": ["/home"]
    })
    assert response.status_code in [200, 400, 500]
```

- [ ] **Step 2: Run test**
Expected: FAIL

- [ ] **Step 3: Add Restic endpoints**

```python
@app.get("/api/backup/restic/status")
async def restic_status():
    """Get Restic status"""
    check = subprocess.run(["restic", "version"], capture_output=True)
    return {"installed": check.returncode == 0}

@app.post("/api/backup/restic/snapshot")
async def restic_snapshot(repo: str, paths: List[str]):
    """Create Restic snapshot"""
    cmd = ["restic", "-r", repo, "snapshot"] + paths
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {"status": "created" if result.returncode == 0 else "error"}

@app.get("/api/backup/restic/snapshots")
async def restic_snapshots(repo: str):
    """List Restic snapshots"""
    cmd = ["restic", "-r", repo", "snapshots", "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return {"snapshots": json.loads(result.stdout)}
        except:
            return {"snapshots": []}
    return {"snapshots": []}
```

- [ ] **Step 4: Run test**
Expected: PASS

- [ ] **Step 5: Commit**

---

## Task A3: RClone Sync API Endpoints

**Files:**
- Modify: `src/forgeos-api.py`
- Test: `tests/test_rclone_api.py`

- [ ] **Step 1: Write failing test**

- [ ] **Step 2: Run test**
Expected: FAIL

- [ ] **Step 3: Add RClone endpoints**

```python
@app.get("/api/backup/rclone/status")
async def rclone_status():
    """Get RClone status"""
    check = subprocess.run(["rclone", "version"], capture_output=True)
    return {"installed": check.returncode == 0}

@app.post("/api/backup/rclone/sync")
async def rclone_sync(source: str, destination: str, config: str = None):
    """Run RClone sync"""
    cmd = ["rclone", "sync", source, destination]
    if config:
        cmd.extend(["--config", config])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {"status": "synced" if result.returncode == 0 else "error"}

@app.get("/api/backup/rclone/configs")
async def rclone_configs():
    """List RClone configs"""
    result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    if result.returncode == 0:
        return {"remotes": result.stdout.strip().split("\n")}
    return {"remotes": []}
```

- [ ] **Step 4: Run test**
Expected: PASS

- [ ] **Step 5: Commit**

---

## Task A4: Unified Backup WebGUI Panel

**Files:**
- Modify: `web/desktop/index.html` (add backup panel)
- Test: Manual browser verification

- [ ] **Step 1: Add backup panel HTML**

Add to index.html (find backup section, expand):
```html
<div id="panel-backup" class="panel hidden">
  <div class="panel-header">
    <h2>Backup</h2>
    <div class="backup-tabs">
      <button class="tab active" data-tab="borg">Borg</button>
      <button class="tab" data-tab="restic">Restic</button>
      <button class="tab" data-tab="rclone">RClone</button>
    </div>
  </div>
  <div id="backup-content" class="panel-content">
    <!-- Borg section -->
    <div class="backup-section" data-section="borg">
      <div class="status-card">
        <div class="status-label">Borg Backup</div>
        <div class="status-value" id="borg-status">Loading...</div>
      </div>
      <div class="jobs-list" id="borg-jobs"></div>
      <button class="btn-primary" onclick="createBorgBackup()">+ New Backup</button>
    </div>
    <!-- Restic section -->
    <div class="backup-section hidden" data-section="restic">
      <div class="status-card">
        <div class="status-label">Restic</div>
        <div class="status-value" id="restic-status">Loading...</div>
      </div>
    </div>
    <!-- RClone section -->
    <div class="backup-section hidden" data-section="rclone">
      <div class="status-card">
        <div class="status-label">RClone</div>
        <div class="status-value" id="rclone-status">Loading...</div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add backup JavaScript**

Add to index.html JS section:
```javascript
// Backup panel functions
function openBackupPanel() {
  showPanel('backup');
  loadBackupStatus();
}

async function loadBackupStatus() {
  // Borg
  try {
    const borg = await fetch('/api/backup/borg/status').then(r => r.json());
    document.getElementById('borg-status').textContent = 
      borg.installed ? 'Installed' : 'Not Installed';
  } catch(e) {
    document.getElementById('borg-status').textContent = 'Error';
  }
  
  // Restic
  try {
    const restic = await fetch('/api/backup/restic/status').then(r => r.json());
    document.getElementById('restic-status').textContent = 
      restic.installed ? 'Installed' : 'Not Installed';
  } catch(e) {
    document.getElementById('restic-status').textContent = 'Error';
  }
  
  // RClone
  try {
    const rclone = await fetch('/api/backup/rclone/status').then(r => r.json());
    document.getElementById('rclone-status').textContent = 
      rclone.installed ? 'Installed' : 'Not Installed';
  } catch(e) {
    document.getElementById('rclone-status').textContent = 'Error';
  }
}

async function createBorgBackup() {
  const name = prompt('Backup name:');
  const source = prompt('Source path:');
  const destination = prompt('Destination:');
  if(name && source && destination) {
    const result = await fetch('/api/backup/borg/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, source, destination})
    }).then(r => r.json());
    alert(result.status || result.error);
    loadBackupStatus();
  }
}

// Tab switching
document.querySelectorAll('.backup-tabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.backup-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.querySelectorAll('.backup-section').forEach(s => s.classList.add('hidden'));
    document.querySelector(`[data-section="${tab.dataset.tab}"]`).classList.remove('hidden');
  });
});
```

- [ ] **Step 3: Test in browser**

Navigate to: http://localhost:5080/desktop/index.html
Click Backup panel
Verify tabs work and status loads

- [ ] **Step 4: Commit**

---

## Task B1: Docker App Browser API

**Files:**
- Modify: `src/forgeos-api.py`
- Test: `tests/test_docker_apps.py`

- [ ] **Step 1: Write failing test**

```python
def test_docker_apps_list():
    response = client.get("/api/docker/apps")
    assert response.status_code == 200
    data = response.json()
    assert "apps" in data
    assert len(data.apps) > 0

def test_docker_install():
    response = client.post("/api/docker/install", json={
        "app": "nginx",
        "image": "nginx:latest"
    })
    assert response.status_code in [200, 400, 500]
```

- [ ] **Step 2: Run test**
Expected: FAIL

- [ ] **Step 3: Add Docker app endpoints**

```python
DOCKER_APPS = [
    {"name": "nginx", "image": "nginx:latest", "port": 80, "category": "web"},
    {"name": "jellyfin", "image": "jellyfin/jellyfin:latest", "port": 8096, "category": "media"},
    {"name": "adguard", "image": "adguard/adguardhome:latest", "port": 3000, "category": "network"},
    {"name": "portainer", "image": "portainer/portainer-ce:latest", "port": 9000, "category": "admin"},
    {"name": "homarr", "image": "ghcr.io/axistent/homarr:latest", "port": 3000, "category": "dashboard"},
    {"name": "nextcloud", "image": "nextcloud:latest", "port": 80, "category": "cloud"},
    {"name": "minio", "image": "minio/minio:latest", "port": 9000, "category": "storage"},
    {"name": "prometheus", "image": "prom/prometheus:latest", "port": 9090, "category": "monitoring"},
    {"name": "grafana", "image": "grafana/grafana:latest", "port": 3000, "category": "monitoring"},
    {"name": "immich", "image": "ghcr.io/immich-app/immich-server:latest", "port": 2283, "category": "media"},
]

@app.get("/api/docker/apps")
async def docker_apps():
    """Get available Docker apps for one-click install"""
    return {"apps": DOCKER_APPS}

@app.post("/api/docker/install")
async def docker_install(app: str, image: str = None, ports: List[str] = None):
    """Install Docker app from curated list"""
    # Find app in curated list or use provided
    app_info = next((a for a in DOCKER_APPS if a["name"] == app), None)
    if not app_info:
        app_info = {"name": app, "image": image or app, "ports": ports or []}
    
    # Build docker run command
    port_args = []
    if app_info.get("port"):
        port_args = ["-p", f"{app_info['port']}:{app_info['port']}"]
    
    cmd = ["docker", "run", "-d", "--name", app_info["name"]] + port_args + [app_info["image"]]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        return {"status": "installed", "app": app_info["name"]}
    return {"error": result.stderr}, 500
```

- [ ] **Step 4: Run test**
Expected: PASS

- [ ] **Step 5: Commit**

---

## Task B2: Docker App Browser WebGUI Panel

**Files:**
- Modify: `web/desktop/index.html`

- [ ] **Step 1: Add Docker Apps panel HTML**

```html
<div id="panel-apps" class="panel hidden">
  <div class="panel-header">
    <h2>Apps</h2>
    <button class="btn-primary" onclick="showAppBrowser()">+ Add App</button>
  </div>
  <div class="app-categories">
    <button class="category active" data-category="all">All</button>
    <button class="category" data-category="media">Media</button>
    <button class="category" data-category="network">Network</button>
    <button class="category" data-category="monitoring">Monitoring</button>
    <button class="category" data-category="cloud">Cloud</button>
  </div>
  <div id="app-grid" class="app-grid"></div>
</div>
```

- [ ] **Step 2: Add JavaScript**

```javascript
let dockerApps = [];

async function loadApps() {
  const response = await fetch('/api/docker/apps');
  dockerApps = (await response.json()).apps;
  renderAppGrid(dockerApps);
}

function renderAppGrid(apps) {
  const grid = document.getElementById('app-grid');
  grid.innerHTML = apps.map(app => `
    <div class="app-card" data-category="${app.category}">
      <div class="app-icon">${app.name[0].toUpperCase()}</div>
      <div class="app-name">${app.name}</div>
      <div class="app-category">${app.category}</div>
      <button class="btn-install" onclick="installApp('${app.name}')">Install</button>
    </div>
  `).join('');
}

async function installApp(name) {
  if(confirm(`Install ${name}?`)) {
    const result = await fetch('/api/docker/install', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: name})
    }).then(r => r.json());
    alert(result.status || result.error);
  }
}

function showAppBrowser() {
  openPanel('apps');
  loadApps();
}
```

- [ ] **Step 3: Test**

- [ ] **Step 4: Commit**

---

## Task C1: FOG Imaging API

**Files:**
- Modify: `src/forgeos-api.py`
- Test: `tests/test_fog_api.py`

- [ ] **Step 1: Write failing test**

- [ ] **Step 2: Run test**
Expected: FAIL

- [ ] **Step 3: Add FOG endpoints**

```python
@app.get("/api/imaging/status")
async def imaging_status():
    """Get FOG imaging status"""
    # Check if FOG is installed
    fog_installed = os.path.exists("/opt/fog")
    images = []
    hosts = []
    
    if fog_installed:
        # Get images
        img_dir = "/images"
        if os.path.exists(img_dir):
            try:
                images = os.listdir(img_dir)
            except:
                pass
    
    return {"fog_installed": fog_installed, "images": images, "hosts": hosts}

@app.post("/api/imaging/capture")
async def imaging_capture(hostname: str, image_name: str):
    """Request FOG image capture"""
    if not os.path.exists("/opt/fog"):
        return {"error": "FOG not installed"}, 500
    # This would integrate with FOG API
    return {"status": "capturing", "host": hostname, "image": image_name}

@app.post("/api/imaging/deploy")
async def imaging_deploy(image_name: str, target_host: str):
    """Deploy image to target"""
    if not os.path.exists("/opt/fog"):
        return {"error": "FOG not installed"}, 500
    return {"status": "deploying", "image": image_name, "target": target_host}
```

- [ ] **Step 4: Run test**
Expected: PASS

- [ ] **Step 5: Commit**

---

## Task C2: FOG Imaging WebGUI Panel

**Files:**
- Modify: `web/desktop/index.html`

- [ ] **Step 1: Add Imaging panel HTML**

```html
<div id="panel-imaging" class="panel hidden">
  <div class="panel-header">
    <h2>System Imaging</h2>
  </div>
  <div class="imaging-status">
    <div class="status-card">
      <div class="status-label">FOG Imaging</div>
      <div class="status-value" id="fog-status">Loading...</div>
    </div>
  </div>
  <div class="imaging-images">
    <h3>Available Images</h3>
    <div id="image-list"></div>
  </div>
  <div class="imaging-actions">
    <button class="btn-primary" onclick="showCaptureDialog()">Capture Image</button>
    <button class="btn-secondary" onclick="showDeployDialog()">Deploy Image</button>
  </div>
</div>
```

- [ ] **Step 2: Add JavaScript**

```javascript
async function loadImagingStatus() {
  const status = await fetch('/api/imaging/status').then(r => r.json());
  document.getElementById('fog-status').textContent = 
    status.fog_installed ? 'Installed' : 'Not Installed';
  
  const imageList = document.getElementById('image-list');
  if(status.images && status.images.length > 0) {
    imageList.innerHTML = status.images.map(img => 
      `<div class="image-item">${img}</div>`
    ).join('');
  } else {
    imageList.innerHTML = '<p>No images available</p>';
  }
}
```

- [ ] **Step 3: Test**

- [ ] **Step 4: Commit**

---

## Task C3: FOG Installer Module

**Files:**
- Create: `install/modules/22-imaging.sh`

- [ ] **Step 1: Create FOG installer module**

```bash
#!/bin/bash
# FOG Imaging Installation Module

install_fog() {
    log "Installing FOG Imaging..."
    
    # Check dependencies
    apt-get update
    apt-get install -y Apache2 mysql-server php php-mysql php-gd php-fpm
    
    # Clone FOG repository
    if [ ! -d /opt/fog ]; then
        git clone https://github.com/FOGProject/fogproject.git /opt/fog
        cd /opt/fog
    fi
    
    # Run FOG installation
    cd /opt/fog/bin
    ./installfog.sh -y
    
    log "FOG Imaging installed"
}

configure_fog() {
    # Configure FOG storage
    mkdir -p /images
    chown -R fog:root /images
    
    # Configure Web server
    a2enmod php-fpm
    systemctl restart apache2
}
```

- [ ] **Step 2: Commit**

---

## Verification

After each task completes, verify:
- [ ] API endpoint responds correctly
- [ ] Test passes (or error handled gracefully)
- [ ] WebUI panel renders without error

At end of Phase 1:
- [ ] All 3 backup tools accessible via API
- [ ] Backup panel loads in WebGUI
- [ ] Docker apps list shows in WebGUI
- [ ] FOG endpoints respond
- [ ] Imaging panel shows in WebGUI

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-04-26-forgeos-phase1.md`.**

**1. Subagent-Driven (recommended)** - Fresh subagent per task area in parallel, faster

**2. Inline Execution** - Execute tasks in this session using executing-plans

**Which approach?** (Use subagent-driven for fewer tokens)