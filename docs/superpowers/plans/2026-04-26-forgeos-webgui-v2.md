# ForgeOS WebGUI v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete WebGUI redesign with new CSS system, layout components, window manager, and dashboard widgets

**Architecture:** Modular JavaScript components - each file has one clear responsibility. New design system as CSS custom properties. Window manager handles floating/draggable windows.

**Tech Stack:** HTML5, CSS3 (custom properties), Vanilla JavaScript (no framework)

---

## Implementation Phases

- **Phase A:** CSS Design System (foundation)
- **Phase B:** Layout Components  
- **Phase C:** Window Manager
- **Phase D:** Dashboard Widgets
- **Phase E:** Panes Integration

---

## Phase A: CSS Design System

### Task A1: Create forgeos.css Design System

**Files:**
- Create: `web/desktop/css/forgeos.css`

- [ ] **Step 1: Create CSS custom properties**

```css
/* forgeos.css - Design System */
:root {
  /* Colors - Sophisticated Dark */
  --bg-void: #0a0a0f;
  --bg-base: #141418;
  --bg-surface: #1a1a24;
  --bg-elevated: #222230;
  --bg-card: #282836;
  
  --accent-primary: #e85d04;
  --accent-secondary: #4a8ab0;
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
  --font-mono: 'IBM Plex Mono', monospace;
  --font-size-xs: 11px;
  --font-size-sm: 12px;
  --font-size-md: 13px;
  --font-size-lg: 18px;
  --font-size-xl: 24px;
  
  /* Effects */
  --shadow-sm: 0 2px 4px rgba(0,0,0,0.2);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.3);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.4);
  --radius-sm: 4px;
  --radius-md: 8px;
  --transition: 200ms ease-out;
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
  font-family: var(--font-mono);
  font-size: var(--font-size-md);
  color: var(--text-primary);
  background: var(--bg-void);
  overflow: hidden;
}
```

- [ ] **Step 2: Add utility classes**

```css
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
  border: 1px solid #2a2a32;
  border-radius: var(--radius-md);
  padding: var(--space-md);
  box-shadow: var(--shadow-md);
}

.text-muted { color: var(--text-muted); }
.text-secondary { color: var(--text-secondary); }
```

- [ ] **Step 3: Commit**

```bash
git add web/desktop/css/forgeos.css
git commit -m "feat: Add forgeos.css design system"
```

---

## Phase B: Layout Components

### Task B1: Sidebar Component

**Files:**
- Create: `web/desktop/js/sidebar.js`
- Modify: `web/desktop/index.html`

- [ ] **Step 1: Create sidebar JavaScript**

```javascript
// sidebar.js - Collapsible sidebar component
class ForgeSidebar {
  constructor() {
    this.collapsed = false;
    this.init();
  }
  
  init() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    
    // Add toggle functionality
    const toggle = document.getElementById('sidebar-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => this.toggle());
    }
    
    // Keyboard shortcut
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === '[') this.toggle();
    });
  }
  
  toggle() {
    this.collapsed = !this.collapsed;
    document.body.classList.toggle('sidebar-collapsed', this.collapsed);
    localStorage.setItem('sidebar-collapsed', this.collapsed);
  }
  
  restore() {
    const saved = localStorage.getItem('sidebar-collapsed') === 'true';
    if (saved) {
      this.collapsed = true;
      document.body.classList.add('sidebar-collapsed');
    }
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  const sidebar = new ForgeSidebar();
  sidebar.restore();
});
```

- [ ] **Step 2: Add sidebar HTML structure**

```html
<aside id="sidebar" class="sidebar">
  <div class="sidebar-header">
    <button id="sidebar-toggle" class="sidebar-toggle">☰</button>
  </div>
  <nav class="sidebar-nav">
    <button class="nav-item" data-panel="dashboard">
      <span class="nav-icon">◈</span>
      <span class="nav-label">Dashboard</span>
    </button>
    <button class="nav-item" data-panel="apps">
      <span class="nav-icon">◉</span>
      <span class="nav-label">Apps</span>
    </button>
    <button class="nav-item" data-panel="storage">
      <span class="nav-icon">⬡</span>
      <span class="nav-label">Storage</span>
    </button>
    <button class="nav-item" data-panel="network">
      <span class="nav-icon">⬢</span>
      <span class="nav-label">Network</span>
    </button>
    <button class="nav-item" data-panel="backup">
      <span class="nav-icon">◫</span>
      <span class="nav-label">Backup</span>
    </button>
    <button class="nav-item" data-panel="shares">
      <span class="nav-icon">▤</span>
      <span class="nav-label">Shares</span>
    </button>
    <button class="nav-item" data-panel="mail">
      <span class="nav-icon">✉</span>
      <span class="nav-label">Mail</span>
    </button>
    <button class="nav-item" data-panel="settings">
      <span class="nav-icon">⚙</span>
      <span class="nav-label">Settings</span>
    </button>
  </nav>
</aside>
```

- [ ] **Step 3: Add sidebar CSS**

```css
/* Sidebar */
.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 200px;
  background: var(--bg-surface);
  border-right: 1px solid #2a2a32;
  display: flex;
  flex-direction: column;
  transition: width var(--transition);
  z-index: 100;
}

.sidebar-collapsed .sidebar {
  width: 56px;
}

.sidebar-collapsed .nav-label {
  display: none;
}

.sidebar-collapsed .nav-item {
  justify-content: center;
}

.sidebar-header {
  padding: var(--space-md);
  display: flex;
  justify-content: flex-end;
}

.sidebar-toggle {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 18px;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding: var(--space-sm);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
  text-align: left;
  width: 100%;
}

.nav-item:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-primary);
  color: white;
}

.nav-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
}
```

- [ ] **Step 4: Test - verify no errors**

- [ ] **Step 5: Commit**

---

### Task B2: Top Bar Component

**Files:**
- Create: `web/desktop/js/topbar.js`
- Modify: `web/desktop/index.html`

- [ ] **Step 1: Create topbar JavaScript**

```javascript
// topbar.js - Top bar component
class ForgeTopBar {
  constructor() {
    this.init();
  }
  
  init() {
    // User menu toggle
    const userBtn = document.getElementById('user-menu-btn');
    const userMenu = document.getElementById('user-menu');
    if (userBtn && userMenu) {
      userBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        userMenu.classList.toggle('hidden');
      });
    }
    
    // Close on outside click
    document.addEventListener('click', () => {
      userMenu.classList.add('hidden');
    });
    
    // Search functionality
    const searchInput = document.getElementById('global-search');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
    }
  }
  
  handleSearch(query) {
    // Implement search
    console.log('Search:', query);
  }
  
  setTitle(title) {
    const titleEl = document.getElementById('context-title');
    if (titleEl) titleEl.textContent = title;
  }
}

document.addEventListener('DOMContentLoaded', () => new ForgeTopBar());
```

- [ ] **Step 2: Add topbar HTML**

```html
<header id="topbar" class="topbar">
  <div class="topbar-left">
    <input id="global-search" type="text" placeholder="Search..." class="search-input">
  </div>
  <div class="topbar-center">
    <span id="context-title">Dashboard</span>
  </div>
  <div class="topbar-right">
    <button id="user-menu-btn" class="user-btn">
      <span class="user-icon">👤</span>
      <span class="user-name">admin</span>
    </button>
    <div id="user-menu" class="user-menu hidden">
      <button class="menu-item">Profile</button>
      <button class="menu-item">Settings</button>
      <button class="menu-item">Logout</button>
    </div>
  </div>
</header>
```

- [ ] **Step 3: Add topbar CSS**

```css
/* Topbar */
.topbar {
  position: fixed;
  top: 0;
  left: 200px;
  right: 0;
  height: 44px;
  background: var(--bg-surface);
  border-bottom: 1px solid #2a2a32;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-md);
  z-index: 99;
}

.sidebar-collapsed .topbar {
  left: 56px;
}

.topbar-left, .topbar-center, .topbar-right {
  display: flex;
  align-items: center;
}

.search-input {
  background: var(--bg-elevated);
  border: 1px solid #2a2a32;
  border-radius: var(--radius-sm);
  padding: var(--space-xs) var(--space-sm);
  color: var(--text-primary);
  width: 200px;
}

.user-btn {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
}

.user-menu {
  position: absolute;
  top: 36px;
  right: var(--space-md);
  background: var(--bg-surface);
  border: 1px solid #2a2a32;
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  display: flex;
  flex-direction: column;
  min-width: 120px;
}

.menu-item {
  padding: var(--space-sm);
  background: none;
  border: none;
  text-align: left;
  color: var(--text-primary);
  cursor: pointer;
  border-radius: var(--radius-sm);
}

.menu-item:hover {
  background: var(--bg-elevated);
}
```

- [ ] **Step 4: Commit**

### Task B3: Taskbar Component

**Files:**
- Create: `web/desktop/js/taskbar.js`

- [ ] **Step 1: Create taskbar**

```javascript
// taskbar.js - Bottom taskbar with 4 pins
class ForgeTaskbar {
  constructor() {
    this.pins = [
      { id: 'dashboard', icon: '◈', label: 'Dashboard' },
      { id: 'apps', icon: '◉', label: 'Apps' },
      { id: 'storage', icon: '⬡', label: 'Storage' },
      { id: 'settings', icon: '⚙', label: 'Settings' }
    ];
    this.init();
  }
  
  init() {
    const taskbar = document.getElementById('taskbar');
    if (!taskbar) return;
    
    // Create pinned items
    this.pins.forEach(pin => {
      const btn = document.createElement('button');
      btn.className = 'taskbar-item';
      btn.dataset.panel = pin.id;
      btn.innerHTML = `<span class="taskbar-icon">${pin.icon}</span><span class="taskbar-label">${pin.label}</span>`;
      btn.addEventListener('click', () => this.openPanel(pin.id));
      taskbar.appendChild(btn);
    });
  }
  
  openPanel(id) {
    // Emit event or call window manager
    window.forgeOS?.openWindow(id);
  }
}

document.addEventListener('DOMContentLoaded', () => new ForgeTaskbar());
```

- [ ] **Step 2: Add taskbar CSS**

```css
/* Taskbar */
#taskbar {
  position: fixed;
  bottom: 0;
  left: 200px;
  right: 0;
  height: 44px;
  background: var(--bg-surface);
  border-top: 1px solid #2a2a32;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: 0 var(--space-md);
  z-index: 90;
}

.sidebar-collapsed #taskbar {
  left: 56px;
}

.taskbar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--space-xs) var(--space-md);
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: var(--transition);
}

.taskbar-item:hover, .taskbar-item.active {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.taskbar-item.active {
  color: var(--accent-primary);
}

.taskbar-icon {
  font-size: 16px;
}

.taskbar-label {
  font-size: var(--font-size-xs);
}
```

- [ ] **Step 3: Commit**

---

## Phase C: Window Manager

### Task C1: Window System

**Files:**
- Create: `web/desktop/js/window-manager.js`

- [ ] **Step 1: Create window manager**

```javascript
// window-manager.js - Floating window system
class ForgeWindowManager {
  constructor() {
    this.windows = new Map();
    this.zIndex = 1000;
    this.activeWindow = null;
  }
  
  createWindow(id, options = {}) {
    const defaults = {
      title: 'Window',
      width: 600,
      height: 400,
      x: 100,
      y: 100,
      resizable: true,
      minimizable: true,
      maximizable: true,
      closable: true
    };
    const config = { ...defaults, ...options };
    
    const window = document.createElement('div');
    window.className = 'forge-window';
    window.id = `window-${id}`;
    window.style.cssText = `
      left: ${config.x}px;
      top: ${config.y}px;
      width: ${config.width}px;
      height: ${config.height}px;
      z-index: ${++this.zIndex};
    `;
    
    window.innerHTML = `
      <div class="window-titlebar">
        <span class="window-title">${config.title}</span>
        <div class="window-controls">
          ${config.minimizable ? '<button class="win-btn-minimize">_</button>' : ''}
          ${config.maximizable ? '<button class="win-btn-maximize">□</button>' : ''}
          ${config.closable ? '<button class="win-btn-close">×</button>' : ''}
        </div>
      </div>
      <div class="window-content" id="window-content-${id}"></div>
    `;
    
    // Add drag functionality
    const titlebar = window.querySelector('.window-titlebar');
    this.makeDraggable(window, titlebar);
    
    // Add close functionality
    const closeBtn = window.querySelector('.win-btn-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.closeWindow(id));
    }
    
    // Focus on click
    window.addEventListener('mousedown', () => this.focusWindow(id));
    
    document.getElementById('desktop').appendChild(window);
    this.windows.set(id, { window, config });
    
    return window;
  }
  
  makeDraggable(window, handle) {
    let isDragging = false;
    let startX, startY, startLeft, startTop;
    
    handle.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      startLeft = window.offsetLeft;
      startTop = window.offsetTop;
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
    });
    
    const onDrag = (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      window.style.left = (startLeft + dx) + 'px';
      window.style.top = (startTop + dy) + 'px';
    };
    
    const stopDrag = () => {
      isDragging = false;
      document.removeEventListener('mousemove', onDrag);
      document.removeEventListener('mouseup', stopDrag);
    };
  }
  
  focusWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.style.zIndex = ++this.zIndex;
      this.activeWindow = id;
    }
  }
  
  closeWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.remove();
      this.windows.delete(id);
    }
  }
  
  minimizeWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.style.display = 'none';
    }
  }
}

// Global instance
window.forgeOS = {
  windows: new ForgeWindowManager(),
  openWindow: (id, options) => window.forgeOS.windows.createWindow(id, options)
};

document.addEventListener('DOMContentLoaded', () => {
  window.forgeOS.windows = new ForgeWindowManager();
});
```

- [ ] **Step 2: Add window CSS**

```css
/* Windows */
.forge-window {
  position: absolute;
  background: var(--bg-surface);
  border: 1px solid #2a2a32;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.window-titlebar {
  height: 32px;
  background: var(--bg-elevated);
  border-bottom: 1px solid #2a2a32;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-sm);
  cursor: move;
  user-select: none;
}

.window-title {
  font-size: var(--font-size-sm);
  font-weight: 500;
}

.window-controls {
  display: flex;
  gap: var(--space-xs);
}

.win-btn-minimize, .win-btn-maximize, .win-btn-close {
  width: 24px;
  height: 24px;
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  font-size: 14px;
}

.win-btn-close:hover {
  background: var(--accent-danger);
  color: white;
}

.window-content {
  flex: 1;
  overflow: auto;
  padding: var(--space-md);
}
```

- [ ] **Step 3: Integrate with desktop**

Add to desktop.js:
```javascript
// Link desktop icons to windows
document.querySelectorAll('.desktop-icon').forEach(icon => {
  icon.addEventListener('dblclick', () => {
    const panel = icon.dataset.panel;
    window.forgeOS.openWindow(panel, { title: icon.dataset.title });
  });
});
```

- [ ] **Step 4: Test - verify window creation**

- [ ] **Step 5: Commit**

---

## Phase D: Dashboard Widgets

### Task D1: Dashboard Widget Grid

**Files:**
- Create: `web/desktop/js/dashboard.js`

- [ ] **Step 1: Create dashboard**

```javascript
// dashboard.js - Widget grid dashboard
class ForgeDashboard {
  constructor() {
    this.widgets = [];
    this.init();
  }
  
  init() {
    const grid = document.getElementById('widget-grid');
    if (!grid) return;
    
    this.renderWidgets();
  }
  
  renderWidgets() {
    const widgets = [
      { type: 'system', title: 'System', size: '1x1' },
      { type: 'storage', title: 'Storage', size: '2x1' },
      { type: 'docker', title: 'Docker', size: '1x1' },
      { type: 'alerts', title: 'Alerts', size: '1x1' }
    ];
    
    const grid = document.getElementById('widget-grid');
    grid.innerHTML = widgets.map(w => `
      <div class="widget widget-${w.size}" data-type="${w.type}">
        <div class="widget-header">
          <span class="widget-title">${w.title}</span>
        </div>
        <div class="widget-content" id="widget-${w.type}">
          <div class="loading">Loading...</div>
        </div>
      </div>
    `).join('');
    
    // Load widget data
    this.loadWidgetData();
  }
  
  async loadWidgetData() {
    // System stats
    try {
      const stats = await fetch('/api/system/stats').then(r => r.json());
      document.getElementById('widget-system').innerHTML = `
        <div class="stat-row"><span>CPU</span><span>${stats.cpu_pct}%</span></div>
        <div class="stat-row"><span>Memory</span><span>${stats.memory}%</span></div>
      `;
    } catch(e) {
      document.getElementById('widget-system').innerHTML = '<div class="error">Offline</div>';
    }
  }
}

document.addEventListener('DOMContentLoaded', () => new ForgeDashboard());
```

- [ ] **Step 2: Add dashboard CSS**

```css
/* Dashboard Widgets */
#dashboard {
  position: absolute;
  top: 44px;
  left: 200px;
  right: 0;
  bottom: 44px;
  overflow: auto;
  padding: var(--space-md);
}

.sidebar-collapsed #dashboard {
  left: 56px;
}

#widget-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-md);
}

.widget {
  background: var(--bg-surface);
  border: 1px solid #2a2a32;
  border-radius: var(--radius-md);
  padding: var(--space-md);
  min-height: 150px;
}

.widget-2x1 {
  grid-column: span 2;
}

.widget-header {
  margin-bottom: var(--space-sm);
}

.widget-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--text-secondary);
}

.widget-content {
  font-size: var(--font-size-md);
}

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: var(--space-xs) 0;
  border-bottom: 1px solid #2a2a32;
}

.loading, .error {
  color: var(--text-muted);
  font-style: italic;
}
```

- [ ] **Step 3: Test - verify widgets render**

- [ ] **Step 4: Commit**

---

## Phase E: Integration

### Task E1: Main Entry Update

**Files:**
- Modify: `web/desktop/index.html`

- [ ] **Step 1: Link all components**

Add to index.html head:
```html
<link rel="stylesheet" href="css/forgeos.css">
```

Add before closing body:
```html
<script src="js/forgeos.js"></script>
<script src="js/sidebar.js"></script>
<script src="js/topbar.js"></script>
<script src="js/taskbar.js"></script>
<script src="js/window-manager.js"></script>
<script src="js/dashboard.js"></script>
```

- [ ] **Step 2: Test full integration**

- [ ] **Step 3: Commit**

---

## Validation Checklist

After each task:
- [ ] CSS syntax valid
- [ ] JavaScript no errors in console
- [ ] Components render correctly
- [ ] Window drag/resize works

At Phase End:
- [ ] New design system applied
- [ ] Sidebar collapses/expands
- [ ] Taskbar shows 4 pins
- [ ] Windows are draggable
- [ ] Dashboard shows widgets

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-04-26-forgeos-webgui-v2.md`.**

**1. Subagent-Driven (recommended)** - Dispatch subagents per phase

**2. Inline Execution** - Execute in session

**Which approach?**