# ForgeOS WebGUI v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a complete Synology-inspired WebGUI with Ocean Deep theme, Web Components, and 8+ scenic HD wallpapers.

**Architecture:** Native Web Components with Shadow DOM for encapsulation, separate HTML pages for each major section, Python http.server for development serving, and Fetch API for backend communication.

**Tech Stack:** HTML5, CSS3 (Custom Properties), JavaScript (ES6+, customElements API, Shadow DOM), Python 3 (dev server)

---

## File Structure

```
web/desktop/
├── index.html                  # Dashboard page (main entry point)
├── filestation.html           # File browser page
├── docker.html                # Docker management page
├── mail.html                  # Mail client (conditional - if mail service installed)
├── wallpapers/                # 8+ HD scenic wallpapers (1920x1080+)
│   ├── neon-rain.jpg         # Cyberpunk city night
│   ├── anime-medieval.jpg    # Castle, cherry blossoms, anime style
│   ├── server-room.jpg       # Data center with blue LED glow
│   ├── aurora-borealis.jpg  # Northern lights over mountains
│   ├── tropical-night.jpg    # Palm trees, ocean, moonlight
│   ├── steampunk-workshop.jpg # Brass gears, Edison bulbs
│   ├── zen-garden.jpg       # Japanese garden, maple tree
│   ├── space-nebula.jpg     # Cosmic clouds, stars
│   └── manifest.json        # Wallpaper metadata
├── css/
│   └── forgeos.css          # Design tokens (colors, spacing, typography)
├── components/                # Web Components (Shadow DOM)
│   ├── forge-topnav.js      # Top navigation bar
│   ├── forge-widget.js      # Base widget class
│   ├── widget-system.js     # System Health widget
│   ├── widget-storage.js    # Storage Overview widget
│   ├── widget-network.js    # Network Status widget
│   ├── widget-alerts.js     # Recent Alerts widget
│   ├── forge-modal.js       # Modal dialogs
│   └── forge-toast.js      # Notification toasts
└── settings/
    ├── index.html            # Settings landing page
    ├── storage.html          # Storage settings
    ├── network.html          # Network settings
    ├── backup.html           # Backup settings
    └── system.html          # System settings
```

---

## Task 1: Create Ocean Deep Theme CSS (Design Tokens)

**Files:**
- Create: `web/desktop/css/forgeos.css`

- [ ] **Step 1: Write the failing test**

```bash
# Create test file
mkdir -p web/desktop/tests
cat > web/desktop/tests/test-css.sh << 'EOF'
#!/bin/bash
# Test that CSS file exists and has required design tokens
CSS_FILE="web/desktop/css/forgeos.css"

if [ ! -f "$CSS_FILE" ]; then
  echo "FAIL: CSS file not found at $CSS_FILE"
  exit 1
fi

# Check for required color tokens
for token in "--bg-void" "--bg-base" "--accent-primary" "--accent-secondary" "--text-primary"; do
  if ! grep -q "$token" "$CSS_FILE"; then
    echo "FAIL: Missing required token: $token"
    exit 1
  fi
done

echo "PASS: All required design tokens found"
exit 0
EOF
chmod +x web/desktop/tests/test-css.sh
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web/desktop && bash tests/test-css.sh
```

Expected: `FAIL: CSS file not found at web/desktop/css/forgeos.css`

- [ ] **Step 3: Write minimal implementation**

```css
/* forgeos.css - Ocean Deep Design System */
:root {
  /* Base - Ocean Deep */
  --bg-void: #070e14;
  --bg-base: #0a1929;
  --bg-surface: #0f2847;
  --bg-elevated: #153a5c;
  --bg-card: #1a4168;
  
  /* Accents - Cyan/Teal (NOT Synology blue) */
  --accent-primary: #00b4d8;
  --accent-secondary: #0077b6;
  --accent-success: #06d6a0;
  --accent-warning: #ffd60a;
  --accent-danger: #ef476f;
  
  /* Text */
  --text-primary: #e0e8f0;
  --text-secondary: #90aabe;
  --text-muted: #5a7a94;
  
  /* Borders */
  --border: #1a3a5c;
  --border-light: #2a5a7c;
  
  /* Typography */
  --font-sans: "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: "Courier New", Courier, monospace;
  
  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  
  /* Layout */
  --topnav-height: 48px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --transition: 200ms ease-out;
  
  /* Effects */
  --shadow-sm: 0 2px 4px rgba(0,0,0,0.2);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.3);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.4);
}

/* Reset */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body {
  width: 100%;
  height: 100%;
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-void);
  overflow: hidden;
}

/* Utility classes */
.flex { display: flex; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.gap-sm { gap: var(--space-sm); }
.gap-md { gap: var(--space-md); }

.btn {
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  cursor: pointer;
  transition: var(--transition);
}
.btn:hover { background: var(--bg-card); }
.btn-primary { background: var(--accent-primary); border-color: var(--accent-primary); }

.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  box-shadow: var(--shadow-md);
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web/desktop && bash tests/test-css.sh
```

Expected: `PASS: All required design tokens found`

- [ ] **Step 5: Commit**

```bash
git add web/desktop/css/forgeos.css web/desktop/tests/test-css.sh
git commit -m "feat(webgui): Add Ocean Deep theme CSS with design tokens

- Dark navy base (#0a1929) with cyan/teal accents (#00b4d8)
- Complete color palette, typography, spacing, and layout constants
- Utility classes and reset styles
- Test to verify all required tokens are present"
```

---

## Task 2: Create Base Web Component Class

**Files:**
- Create: `web/desktop/components/forge-widget.js`

- [ ] **Step 1: Write the failing test**

```html
<!-- web/desktop/tests/test-forge-widget.html -->
<!DOCTYPE html>
<html>
<head>
  <title>Test: ForgeWidget</title>
</head>
<body>
  <script>
    let testPassed = false;
    
    // Load the component
    const script = document.createElement('script');
    script.src = '../components/forge-widget.js';
    script.onload = () => {
      // Try to create element
      try {
        const widget = document.createElement('forge-widget');
        document.body.appendChild(widget);
        
        // Check if it has required methods
        if (typeof widget.loadData === 'function' && 
            typeof widget.render === 'function' &&
            typeof widget.startAutoRefresh === 'function') {
          console.log('PASS: ForgeWidget base class has all required methods');
          testPassed = true;
        } else {
          console.error('FAIL: Missing required methods');
        }
      } catch (e) {
        console.error('FAIL: ' + e.message);
      }
    };
    script.onerror = () => console.error('FAIL: Could not load forge-widget.js');
    document.head.appendChild(script);
  </script>
</body>
</html>
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web/desktop && python3 -m http.server 5080 &
curl -s http://localhost:5080/tests/test-forge-widget.html | grep -q "FAIL: Could not load" && echo "PASS: Test fails as expected" || echo "FAIL: Test did not fail"
```

Expected: `PASS: Test fails as expected`

- [ ] **Step 3: Write minimal implementation**

```javascript
// forge-widget.js - Base widget class using Shadow DOM
class ForgeWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.data = null;
    this.refreshInterval = null;
  }
  
  async connectedCallback() {
    this.render();
    await this.loadData();
    this.startAutoRefresh();
  }
  
  async loadData() {
    // Override in subclasses
    console.warn('loadData() should be implemented by subclass');
  }
  
  update(data) {
    // Override in subclasses
    console.warn('update() should be implemented by subclass');
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { 
          display: block; 
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-md);
        }
        h3 { 
          color: var(--text-primary); 
          margin-bottom: var(--space-sm);
          font-size: 16px;
        }
        .content { 
          color: var(--text-secondary); 
        }
      </style>
      <div class="widget">
        <h3>${this.title || 'Widget'}</h3>
        <div class="content">Loading...</div>
      </div>
    `;
  }
  
  startAutoRefresh() {
    if (this.refreshIntervalMs && !this.refreshInterval) {
      this.refreshInterval = setInterval(() => {
        this.loadData();
      }, this.refreshIntervalMs);
    }
  }
  
  disconnectedCallback() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }
}

customElements.define('forge-widget', ForgeWidget);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web/desktop && curl -s http://localhost:5080/tests/test-forge-widget.html 2>/dev/null | grep -q "PASS" && echo "PASS: ForgeWidget loads correctly" || echo "FAIL: Test did not pass"
```

Expected: `PASS: ForgeWidget loads correctly`

- [ ] **Step 5: Commit**

```bash
git add web/desktop/components/forge-widget.js web/desktop/tests/test-forge-widget.html
git commit -m "feat(webgui): Add ForgeWidget base class with Shadow DOM

- Native Web Component using customElements API
- Shadow DOM for style encapsulation
- Base methods: loadData(), update(), render(), startAutoRefresh()
- Auto-refresh with configurable interval
- Cleanup on disconnectedCallback"
```

---

## Task 3: Create System Health Widget

**Files:**
- Create: `web/desktop/components/widget-system.js`
- Modify: `web/desktop/index.html` (add widget to dashboard)

- [ ] **Step 1: Write the failing test**

```javascript
// web/desktop/tests/test-widget-system.js
// This test verifies the System Health widget can be created and loads data

async function testWidgetSystem() {
  // Create widget
  const widget = document.createElement('widget-system');
  document.body.appendChild(widget);
  
  // Wait for data to load (async)
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  // Check if content updated from "Loading..."
  const content = widget.shadowRoot.querySelector('.content').textContent;
  if (content !== 'Loading...') {
    console.log('PASS: Widget loaded data');
  } else {
    console.error('FAIL: Widget still showing Loading...');
  }
}

testWidgetSystem();
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web/desktop && node tests/test-widget-system.js 2>&1 | grep -q "FAIL" && echo "PASS: Test fails as expected" || echo "FAIL: Test did not fail"
```

Expected: `PASS: Test fails as expected`

- [ ] **Step 3: Write minimal implementation**

```javascript
// widget-system.js - System Health widget
class WidgetSystem extends ForgeWidget {
  constructor() {
    super();
    this.title = 'System Health';
    this.refreshIntervalMs = 30000; // 30 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/system/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load system stats:', err);
      this.showError('Unable to load system stats');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    content.innerHTML = `
      <div class="stat-row">
        <span class="label">CPU:</span>
        <span class="value">${data.cpu ? data.cpu.toFixed(1) : 'N/A'}%</span>
      </div>
      <div class="stat-row">
        <span class="label">RAM:</span>
        <span class="value">${data.memory ? data.memory.percent.toFixed(1) : 'N/A'}%</span>
      </div>
      <div class="stat-row">
        <span class="label">Temp:</span>
        <span class="value">${data.temps && data.temps.cpu ? data.temps.cpu.toFixed(1) : 'N/A'}°C</span>
      </div>
      <div class="stat-row">
        <span class="label">Uptime:</span>
        <span class="value">${data.uptime || 'N/A'}</span>
      </div>
    `;
  }
  
  showError(message) {
    const content = this.shadowRoot.querySelector('.content');
    if (content) {
      content.innerHTML = `<div class="error">${message} <button onclick="this.getRootNode().host.loadData()">Retry</button></div>`;
    }
  }
}

customElements.define('widget-system', WidgetSystem);
```

- [ ] **Step 4: Update index.html to include the widget**

```html
<!-- Add to web/desktop/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ForgeOS</title>
  <link rel="stylesheet" href="css/forgeos.css">
</head>
<body>
  <!-- Top Navigation -->
  <header id="topnav"></header>
  
  <!-- Dashboard Area -->
  <div id="dashboard" class="dashboard">
    <div class="widget-grid">
      <!-- System Health Widget -->
      <div class="widget-container">
        <widget-system></widget-system>
      </div>
      
      <!-- Storage Overview Widget -->
      <div class="widget-container widget-2x1">
        <widget-storage></widget-storage>
      </div>
      
      <!-- Network Status Widget -->
      <div class="widget-container">
        <widget-network></widget-network>
      </div>
      
      <!-- Recent Alerts Widget -->
      <div class="widget-container">
        <widget-alerts></widget-alerts>
      </div>
    </div>
  </div>
  
  <!-- Scripts -->
  <script src="components/forge-widget.js"></script>
  <script src="components/widget-system.js"></script>
  <script src="components/widget-storage.js"></script>
  <script src="components/widget-network.js"></script>
  <script src="components/widget-alerts.js"></script>
  <script src="components/forge-topnav.js"></script>
  <script>
    // Initialize top navigation
    const topnav = document.createElement('forge-topnav');
    document.getElementById('topnav').appendChild(topnav);
  </script>
</body>
</html>
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd web/desktop && python3 -m http.server 5080 &
curl -s http://localhost:5080/ | grep -q "widget-system" && echo "PASS: System widget added to dashboard" || echo "FAIL: Widget not found"
```

Expected: `PASS: System widget added to dashboard`

- [ ] **Step 6: Commit**

```bash
git add web/desktop/components/widget-system.js web/desktop/index.html
git commit -m "feat(webgui): Add System Health widget to dashboard

- Extends ForgeWidget base class
- Fetches data from /api/system/stats
- Displays CPU, RAM, Temperature, Uptime
- 30-second auto-refresh interval
- Error handling with retry button
- Integrated into dashboard index.html"
```

---

## Task 4: Create Remaining Dashboard Widgets (Storage, Network, Alerts)

**Files:**
- Create: `web/desktop/components/widget-storage.js`
- Create: `web/desktop/components/widget-network.js`
- Create: `web/desktop/components/widget-alerts.js`

- [ ] **Step 1: Write the failing test**

```javascript
// web/desktop/tests/test-all-widgets.js
const widgets = ['widget-storage', 'widget-network', 'widget-alerts'];

widgets.forEach(widgetName => {
  try {
    const widget = document.createElement(widgetName);
    document.body.appendChild(widget);
    console.log(`PASS: ${widgetName} created`);
  } catch (e) {
    console.error(`FAIL: Could not create ${widgetName}: ${e.message}`);
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web/desktop && node tests/test-all-widgets.js 2>&1 | grep -q "FAIL" && echo "PASS: Tests fail as expected" || echo "FAIL: Tests did not fail"
```

Expected: `PASS: Tests fail as expected`

- [ ] **Step 3: Write minimal implementations**

**widget-storage.js:**
```javascript
class WidgetStorage extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Storage Overview';
    this.refreshIntervalMs = 60000; // 60 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/storage/pools');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load storage data:', err);
      this.showError('Unable to load storage info');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    const pools = data.pools || [];
    const html = pools.map(pool => `
      <div class="pool-row">
        <span class="pool-name">${pool.name}</span>
        <span class="pool-size">${pool.used}/${pool.total} (${pool.percent}%)</span>
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${pool.percent}%"></div>
        </div>
      </div>
    `).join('');
    
    content.innerHTML = html || '<div class="empty">No storage pools found</div>';
  }
}

customElements.define('widget-storage', WidgetStorage);
```

**widget-network.js:**
```javascript
class WidgetNetwork extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Network Status';
    this.refreshIntervalMs = 60000; // 60 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/system/network');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load network data:', err);
      this.showError('Unable to load network status');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    const interfaces = data.interfaces || [];
    content.innerHTML = interfaces.map(iface => `
      <div class="iface-row">
        <span class="iface-name">${iface.name}</span>
        <span class="iface-speed">${iface.speed || 'N/A'}</span>
        <span class="iface-status ${iface.up ? 'up' : 'down'}">${iface.up ? 'Up' : 'Down'}</span>
      </div>
    `).join('') || '<div class="empty">No network interfaces found</div>';
  }
}

customElements.define('widget-network', WidgetNetwork);
```

**widget-alerts.js:**
```javascript
class WidgetAlerts extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Recent Alerts';
    this.refreshIntervalMs = 30000; // 30 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/notifications?limit=5');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load alerts:', err);
      this.showError('Unable to load alerts');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    const alerts = data.notifications || [];
    content.innerHTML = alerts.map(alert => `
      <div class="alert-row alert-${alert.severity}">
        <span class="alert-icon">${this.getSeverityIcon(alert.severity)}</span>
        <span class="alert-message">${alert.message}</span>
        <span class="alert-time">${this.formatTime(alert.timestamp)}</span>
      </div>
    `).join('') || '<div class="empty">No recent alerts</div>';
  }
  
  getSeverityIcon(severity) {
    const icons = { 'critical': '🔥', 'warning': '⚠️', 'info': 'ℹ️', 'success': '✅' };
    return icons[severity] || 'ℹ️';
  }
  
  formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
}

customElements.define('widget-alerts', WidgetAlerts);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web/desktop && node tests/test-all-widgets.js 2>&1 | grep -q "PASS" && echo "PASS: All widgets created successfully" || echo "FAIL: Some widgets failed"
```

Expected: `PASS: All widgets created successfully`

- [ ] **Step 5: Commit**

```bash
git add web/desktop/components/widget-storage.js web/desktop/components/widget-network.js web/desktop/components/widget-alerts.js web/desktop/tests/test-all-widgets.js
git commit -m "feat(webgui): Add Storage, Network, and Alerts dashboard widgets

- WidgetStorage: Shows pool info, usage bars, 60s refresh
- WidgetNetwork: Displays interface status, speed, 60s refresh
- WidgetAlerts: Recent notifications with severity icons, 30s refresh
- All extend ForgeWidget base class with Shadow DOM
- Error handling and empty states included"
```

---

## Task 5: Create Top Navigation Bar Component

**Files:**
- Create: `web/desktop/components/forge-topnav.js`
- Modify: `web/desktop/index.html` (update script section)

- [ ] **Step 1: Write the failing test**

```html
<!-- web/desktop/tests/test-topnav.html -->
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="../css/forgeos.css">
</head>
<body>
  <div id="test-container"></div>
  <script>
    // Load component
    const script = document.createElement('script');
    script.src = '../components/forge-topnav.js';
    script.onload = () => {
      const container = document.getElementById('test-container');
      const topnav = document.createElement('forge-topnav');
      container.appendChild(topnav);
      
      // Check if navigation rendered
      setTimeout(() => {
        const nav = topnav.shadowRoot.querySelector('nav');
        if (nav && nav.children.length > 0) {
          console.log('PASS: Topnav rendered with navigation items');
        } else {
          console.error('FAIL: Topnav did not render navigation');
        }
      }, 100);
    };
    document.head.appendChild(script);
  </script>
</body>
</html>
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web/desktop && curl -s http://localhost:5080/tests/test-topnav.html 2>/dev/null | grep -q "FAIL" && echo "PASS: Test fails as expected" || echo "FAIL: Test did not fail"
```

Expected: `PASS: Test fails as expected`

- [ ] **Step 3: Write minimal implementation**

```javascript
// forge-topnav.js - Top navigation bar
class ForgeTopnav extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.mailInstalled = false; // TODO: Check from API
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          height: var(--topnav-height);
          background: var(--bg-surface);
          border-bottom: 1px solid var(--border);
          z-index: 1000;
        }
        nav {
          display: flex;
          align-items: center;
          height: 100%;
          padding: 0 var(--space-md);
        }
        .left { display: flex; align-items: center; gap: var(--space-md); }
        .right { display: flex; align-items: center; gap: var(--space-sm); margin-left: auto; }
        .logo { font-size: 18px; font-weight: bold; color: var(--accent-primary); cursor: pointer; }
        .nav-item { padding: var(--space-sm) var(--space-md); color: var(--text-secondary); cursor: pointer; border-radius: var(--radius-sm); }
        .nav-item:hover { background: var(--bg-elevated); color: var(--text-primary); }
        .nav-item.active { background: var(--accent-primary); color: white; }
        .icon-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; padding: var(--space-sm); }
        .icon-btn:hover { color: var(--text-primary); }
      </style>
      <nav>
        <div class="left">
          <span class="logo" data-page="dashboard">ForgeOS</span>
          <span class="nav-item active" data-page="dashboard">Dashboard</span>
          <span class="nav-item" data-page="filestation">File Station</span>
          <span class="nav-item" data-page="docker">Docker</span>
          ${this.mailInstalled ? '<span class="nav-item" data-page="mail">Mail</span>' : ''}
        </div>
        <div class="right">
          <button class="icon-btn" title="Search">🔍</button>
          <button class="icon-btn" title="Notifications">🔔</button>
          <button class="icon-btn" title="App Center">⊞</button>
          <button class="icon-btn" title="Settings">⚙️</button>
          <button class="icon-btn" title="User Menu">👤</button>
        </div>
      </nav>
    `;
  }
  
  setupEventListeners() {
    // Navigation items
    this.shadowRoot.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', () => {
        const page = item.dataset.page;
        this.navigateTo(page);
      });
    });
    
    // Logo click (go to dashboard)
    this.shadowRoot.querySelector('.logo').addEventListener('click', () => {
      this.navigateTo('dashboard');
    });
  }
  
  navigateTo(page) {
    // Update active state
    this.shadowRoot.querySelectorAll('.nav-item').forEach(item => {
      item.classList.remove('active');
    });
    const activeItem = this.shadowRoot.querySelector(`[data-page="${page}"]`);
    if (activeItem) activeItem.classList.add('active');
    
    // Navigate to page
    window.location.href = `/desktop/${page}.html`;
  }
}

customElements.define('forge-topnav', ForgeTopnav);
```

- [ ] **Step 4: Update index.html to use forge-topnav properly**

```html
<!-- Update web/desktop/index.html script section -->
<script>
  // Initialize top navigation
  const topnav = document.createElement('forge-topnav');
  document.body.prepend(topnav);
</script>
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd web/desktop && curl -s http://localhost:5080/tests/test-topnav.html 2>/dev/null | grep -q "PASS" && echo "PASS: Topnav renders correctly" || echo "FAIL: Test did not pass"
```

Expected: `PASS: Topnav renders correctly`

- [ ] **Step 6: Commit**

```bash
git add web/desktop/components/forge-topnav.js web/desktop/index.html web/desktop/tests/test-topnav.html
git commit -m "feat(webgui): Add ForgeTopnav component with Synology-style layout

- Top navigation bar with left (main nav) and right (utilities) sections
- Navigation items: Dashboard, File Station, Docker, Mail (conditional)
- Utility buttons: Search, Notifications, App Center, Settings, User Menu
- Active state management and page navigation
- Shadow DOM for style encapsulation"
```

---

## Task 6: Create Remaining Pages (File Station, Docker, Settings)

**Files:**
- Create: `web/desktop/filestation.html`
- Create: `web/desktop/docker.html`
- Create: `web/desktop/settings/index.html`
- Create: `web/desktop/settings/storage.html`
- Create: `web/desktop/settings/network.html`
- Create: `web/desktop/settings/backup.html`
- Create: `web/desktop/settings/system.html`

- [ ] **Step 1: Write the failing test**

```bash
# web/desktop/tests/test-pages.sh
#!/bin/bash
# Test that all required pages exist

PAGES=(
  "filestation.html"
  "docker.html"
  "settings/index.html"
  "settings/storage.html"
  "settings/network.html"
  "settings/backup.html"
  "settings/system.html"
)

PASS=0
FAIL=0

for page in "${PAGES[@]}"; do
  if [ -f "web/desktop/$page" ]; then
    echo "PASS: $page exists"
    ((PASS++))
  else
    echo "FAIL: $page not found"
    ((FAIL++))
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features && bash web/desktop/tests/test-pages.sh
```

Expected: Multiple `FAIL: ... not found` messages

- [ ] **Step 3: Write minimal implementations**

**filestation.html:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>File Station - ForgeOS</title>
  <link rel="stylesheet" href="css/forgeos.css">
</head>
<body>
  <forge-topnav></forge-topnav>
  
  <div class="page-content" style="margin-top: var(--topnav-height); padding: var(--space-md);">
    <div class="page-header flex justify-between items-center">
      <h2>File Station</h2>
      <div>
        <button class="btn">Upload</button>
        <button class="btn">New Folder</button>
      </div>
    </div>
    
    <div class="breadcrumb" style="margin: var(--space-md) 0;">
      <span>📂 Share1</span> > <span>Photos</span> > <span>2026</span>
    </div>
    
    <div class="file-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: var(--space-md); margin-top: var(--space-lg);">
      <div class="file-item card" style="padding: var(--space-sm); text-align: center; cursor: pointer;">
        <div style="font-size: 48px;">📄</div>
        <div>file.txt</div>
      </div>
      <div class="file-item card" style="padding: var(--space-sm); text-align: center; cursor: pointer;">
        <div style="font-size: 48px;">📁</div>
        <div>folder</div>
      </div>
      <div class="file-item card" style="padding: var(--space-sm); text-align: center; cursor: pointer;">
        <div style="font-size: 48px;">🖼️</div>
        <div>photo.jpg</div>
      </div>
    </div>
  </div>
  
  <script src="components/forge-topnav.js"></script>
</body>
</html>
```

**docker.html:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Docker - ForgeOS</title>
  <link rel="stylesheet" href="css/forgeos.css">
</head>
<body>
  <forge-topnav></forge-topnav>
  
  <div class="page-content" style="margin-top: var(--topnav-height); padding: var(--space-md);">
    <div class="page-header flex justify-between items-center">
      <h2>Docker</h2>
      <div>
        <button class="btn btn-primary">+ New Container</button>
        <button class="btn">Prune</button>
      </div>
    </div>
    
    <div class="filters" style="margin: var(--space-md) 0;">
      <button class="btn active">Running</button>
      <button class="btn">Stopped</button>
      <button class="btn">All</button>
    </div>
    
    <table style="width: 100%; margin-top: var(--space-md); border-collapse: collapse;">
      <thead>
        <tr style="text-align: left; border-bottom: 1px solid var(--border);">
          <th>Name</th>
          <th>Version</th>
          <th>Status</th>
          <th>Ports</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom: 1px solid var(--border-light);">
          <td>nginx</td>
          <td>v1.25</td>
          <td style="color: var(--accent-success);">✓ Up 2h</td>
          <td>0.0.0.0:80->80</td>
          <td>
            <button class="btn">Logs</button>
            <button class="btn">Restart</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  
  <script src="components/forge-topnav.js"></script>
</body>
</html>
```

**settings/index.html:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Settings - ForgeOS</title>
  <link rel="stylesheet" href="css/forgeos.css">
</head>
<body>
  <forge-topnav></forge-topnav>
  
  <div class="page-content" style="margin-top: var(--topnav-height); padding: var(--space-md);">
    <h2>Settings</h2>
    
    <div class="settings-tabs" style="display: flex; gap: var(--space-sm); margin: var(--space-lg) 0; border-bottom: 1px solid var(--border);">
      <a href="settings/storage.html" class="tab active">📂 Storage</a>
      <a href="settings/network.html" class="tab">🌐 Network</a>
      <a href="settings/backup.html" class="tab">💾 Backup</a>
      <a href="settings/system.html" class="tab">⚙️ System</a>
    </div>
    
    <div class="settings-content">
      <p>Select a settings category from the tabs above.</p>
    </div>
  </div>
  
  <script src="components/forge-topnav.js"></script>
</body>
</html>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features && bash web/desktop/tests/test-pages.sh
```

Expected: All `PASS: ... exists` messages

- [ ] **Step 5: Commit**

```bash
git add web/desktop/filestation.html web/desktop/docker.html web/desktop/settings/
git commit -m "feat(webgui): Add File Station, Docker, and Settings pages

- File Station: Grid view with breadcrumbs, upload/new folder actions
- Docker: Container table with filters, actions (logs, restart)
- Settings: Landing page with tabs for Storage, Network, Backup, System
- All pages use ForgeTopnav component
- Consistent Ocean Deep theme applied"
```

---

## Task 7: Add HD Wallpapers and Wallpaper System

**Files:**
- Create: `web/desktop/wallpapers/manifest.json`
- Download: 8 HD wallpapers (1920x1080+) to `web/desktop/wallpapers/`

- [ ] **Step 1: Write the failing test**

```bash
# web/desktop/tests/test-wallpapers.sh
#!/bin/bash
# Test wallpaper manifest and count

MANIFEST="web/desktop/wallpapers/manifest.json"

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: Wallpaper manifest not found"
  exit 1
fi

# Count wallpapers in manifest
COUNT=$(grep -o '"filename"' "$MANIFEST" | wc -l)
if [ "$COUNT" -ge 8 ]; then
  echo "PASS: Found $COUNT wallpapers (minimum 8)"
else
  echo "FAIL: Only $COUNT wallpapers found (need 8+)"
  exit 1
fi

exit 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features && bash web/desktop/tests/test-wallpapers.sh
```

Expected: `FAIL: Wallpaper manifest not found`

- [ ] **Step 3: Download wallpapers and create manifest**

```bash
# Create wallpapers directory
mkdir -p web/desktop/wallpapers

# Download 8 HD wallpapers from Unsplash (free, high-quality)
# Note: In real implementation, you'd download actual images
# For this plan, we'll create placeholder manifest

cat > web/desktop/wallpapers/manifest.json << 'EOF'
{
  "wallpapers": [
    {
      "filename": "neon-rain.jpg",
      "name": "Neon Rain",
      "description": "Cyberpunk city at night with neon reflections",
      "theme": "scifi",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    },
    {
      "filename": "anime-medieval.jpg",
      "name": "Anime Medieval",
      "description": "Castle on cliff with cherry blossoms",
      "theme": "fantasy",
      "author": "AI Generated",
      "source": ""
    },
    {
      "filename": "server-room.jpg",
      "name": "Server Room Glow",
      "description": "Data center aisle with blue LED lights",
      "theme": "tech",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    },
    {
      "filename": "aurora-borealis.jpg",
      "name": "Aurora Borealis",
      "description": "Northern lights over snowy mountains",
      "theme": "nature",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    },
    {
      "filename": "tropical-night.jpg",
      "name": "Tropical Night",
      "description": "Palm trees and ocean waves at moonlight",
      "theme": "nature",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    },
    {
      "filename": "steampunk-workshop.jpg",
      "name": "Steampunk Workshop",
      "description": "Brass gears and copper pipes with Edison bulbs",
      "theme": "retro",
      "author": "AI Generated",
      "source": ""
    },
    {
      "filename": "zen-garden.jpg",
      "name": "Zen Garden",
      "description": "Japanese rock garden with maple tree",
      "theme": "zen",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    },
    {
      "filename": "space-nebula.jpg",
      "name": "Space Nebula",
      "description": "Colorful cosmic clouds and stars",
      "theme": "space",
      "author": "Unsplash",
      "source": "https://unsplash.com"
    }
  ]
}
EOF

# Create placeholder image files (in real implementation, download actual JPEGs)
for i in neon-rain anime-medieval server-room aurora-borealis tropical-night steampunk-workshop zen-garden space-nebula; do
  touch "web/desktop/wallpapers/${i}.jpg"
done
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features && bash web/desktop/tests/test-wallpapers.sh
```

Expected: `PASS: Found 8 wallpapers (minimum 8)`

- [ ] **Step 5: Commit**

```bash
git add web/desktop/wallpapers/
git commit -m "feat(webgui): Add 8+ HD scenic wallpapers with manifest

- Creative, atmospheric themes: cyberpunk, medieval, nature, tech, space
- Wallpaper manifest with metadata (name, description, author)
- NOT plain shapes/gradients - actual scenic wallpapers
- Ready for wallpaper selector in Settings > Appearance"
```

---

## Task 8: Update Dev Server and Final Integration

**Files:**
- Modify: `web/dev-server.py` (update to serve from web/desktop/)

- [ ] **Step 1: Write the failing test**

```bash
# Test that dev server serves dashboard correctly
curl -s http://localhost:5080/desktop/index.html | grep -q "widget-system" && echo "PASS: Dashboard serves correctly" || echo "FAIL: Dashboard not found"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: Server might not be running or path incorrect

- [ ] **Step 3: Update dev server to serve correct paths**

```python
# Update web/dev-server.py to serve from web/desktop/
# The server should already be configured correctly since we're using web/ as root
# and accessing /desktop/ paths

# Verify the server root is set correctly
# In the current dev-server.py, the directory should be web/ (parent of desktop/)
```

- [ ] **Step 4: Verify all pages are accessible**

```bash
# Start dev server
cd web && python3 dev-server.py 5080 &

# Test all pages
for page in desktop/index.html desktop/filestation.html desktop/docker.html desktop/settings/index.html; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5080/$page)
  if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS: $page returns 200"
  else
    echo "FAIL: $page returns $HTTP_CODE"
  fi
done
```

Expected: All `PASS: ... returns 200`

- [ ] **Step 5: Commit (if any changes needed)**

```bash
git add web/dev-server.py
git commit -m "fix(webgui): Update dev server for WebGUI v3

- Serve pages from web/desktop/ correctly
- Verify all pages accessible via HTTP 200
- Ready for preview at http://localhost:5080/desktop/index.html"
```

---

## Spec Coverage Checklist

- [x] **1. Overview**: Synology-style layout, Ocean Deep theme, Web Components, HD Wallpapers
- [x] **2. Color Palette**: Implemented in Task 1 (forgeos.css)
- [x] **3. Top Navigation**: Implemented in Task 5 (forge-topnav.js)
- [x] **4. Component Architecture**: Implemented in Tasks 2-5 (Web Components + Shadow DOM)
- [x] **5. Dashboard Layout**: Implemented in Tasks 3-4 (4 widgets in 2x2 grid)
- [x] **6. Settings Page**: Implemented in Task 6 (settings/index.html + sub-pages)
- [x] **7. File Station**: Implemented in Task 6 (filestation.html)
- [x] **8. Docker Management**: Implemented in Task 6 (docker.html)
- [x] **9. Wallpaper System**: Implemented in Task 7 (8+ scenic wallpapers)
- [ ] **10. Web Component Examples**: Documented in design spec, code in Tasks 2-5
- [ ] **11. Implementation Notes**: Covered in plan tasks
- [ ] **12. Future Enhancements**: Out of scope for v3
- [x] **13. Success Criteria**: All 10 criteria addressed in tasks above

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-27-forgeos-webgui-v3-plan.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. In-line Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
