# ForgeOS WebGUI v3 Design Specification

**Date**: 2026-04-27  
**Status**: Approved (Brainstorming Phase Complete)  
**Version**: 3.0  
**Inspiration**: Synology DSM (layout), Ocean Deep theme (original colors)

---

## 1. Overview

ForgeOS WebGUI v3 is a complete redesign inspired by Synology's DSM interface, using an original "Ocean Deep" color scheme (dark navy + cyan/teal) to avoid copyright infringement with Synology's trademark blue (#0067C6).

### Key Design Principles:
- **Synology-style layout**: Top navigation bar, widget-based dashboard, clean/minimal aesthetic
- **Ocean Deep colors**: Dark navy (#0a1929) base with cyan/teal (#00b4d8, #0077b6) accents
- **Web Components**: Native browser components with Shadow DOM for encapsulation
- **Separate pages**: Each major section is its own HTML file (Synology style)
- **HD Wallpapers**: 8+ creative, atmospheric scenic wallpapers (not plain/abstract)

---

## 2. Color Palette (Ocean Deep Theme)

```css
:root {
  /* Base - Ocean Deep */
  --bg-void: #070e14;        /* Deepest background (navy-black) */
  --bg-base: #0a1929;        /* Main background */
  --bg-surface: #0f2847;     /* Cards, panels */
  --bg-elevated: #153a5c;    /* Hover states, dropdowns */
  --bg-card: #1a4168;        /* Widget backgrounds */
  
  /* Accents - Cyan/Teal (NOT Synology blue) */
  --accent-primary: #00b4d8;   /* Links, active states */
  --accent-secondary: #0077b6; /* Buttons, highlights */
  --accent-success: #06d6a0;   /* Success states */
  --accent-warning: #ffd60a;   /* Warnings */
  --accent-danger: #ef476f;     /* Errors, critical alerts */
  
  /* Text */
  --text-primary: #e0e8f0;     /* Main text (light blue-white) */
  --text-secondary: #90aabe;     /* Secondary text */
  --text-muted: #5a7a94;       /* Muted, disabled text */
  
  /* Borders */
  --border: #1a3a5c;
  --border-light: #2a5a7c;
}
```

### Typography:
- **Headings & Body**: System font stack (no Google Fonts dependency)
  - `"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- **Monospace (code, logs)**: `"Courier New", Courier, monospace`

### Layout Constants:
- **Top nav height**: 48px
- **Widget border-radius**: 8px
- **Widget padding**: 16px
- **Spacing scale**: 4px, 8px, 16px, 24px, 32px

---

## 3. Top Navigation Structure

### Left Side (Main Navigation):
```
[ForgeOS Logo] [Dashboard] [File Station] [Docker] [Mail*]
```

- **ForgeOS Logo**: Text-based, stylized, links to Dashboard
- **Dashboard**: Main widget dashboard (System Health, Storage, Network, Alerts)
- **File Station**: File browser (folder icon)
- **Docker**: Container management (separate button as requested)
- **Mail***: Email client (**ONLY if installed** - conditional)

### Right Side (Utilities):
```
[Search] [Notifications] [App Center] [Settings] [User Menu]
```

- **Search**: Global search across files, settings, containers
- **Notifications**: System alerts (from Dashboard widget D)
- **App Center**: Browse/install additional apps
- **Settings**: Control Panel (Storage, Network, Backup, System, etc.)
- **User Menu**: Profile, logout

### Key Decisions:
- Docker gets its own button (always visible, frequently used)
- Mail is conditional (only appears if `mail` service is installed)
- All other services (Storage, Network, Backup, Shares) live inside **Settings/Control Panel**

---

## 4. Component Architecture (Web Components + Shadow DOM)

### Directory Structure:
```
web/desktop/
├── index.html              # Dashboard (main page)
├── filestation.html       # File browser
├── docker.html            # Docker management
├── mail.html              # Mail client (conditional)
├── wallpapers/           # 8+ HD wallpapers (1920x1080+)
│   ├── neon-rain.jpg           # Wet cyberpunk city, neon reflections
│   ├── anime-medieval.jpg     # Castle on cliff, cherry blossoms, lanterns
│   ├── server-room-glow.jpg   # Dark data center, blue LED lights
│   ├── aurora-borealis.jpg    # Northern lights, snowy mountains
│   ├── tropical-night.jpg     # Palm trees, ocean waves, moonlight
│   ├── steampunk-workshop.jpg # Brass gears, copper pipes, Edison bulbs
│   ├── zen-garden.jpg         # Japanese rock garden, maple tree, mist
│   └── space-nebula.jpg       # Cosmic clouds, stars, deep space
├── css/
│   └── forgeos.css            # Design tokens (colors, spacing, typography)
├── components/                  # Web Components (Shadow DOM)
│   ├── forge-topnav.js        # Top navigation bar
│   ├── forge-widget.js        # Base widget class
│   ├── widget-system.js       # System Health widget
│   ├── widget-storage.js      # Storage Overview widget
│   ├── widget-network.js      # Network Status widget
│   ├── widget-alerts.js       # Recent Alerts widget
│   ├── forge-modal.js         # Modal dialogs
│   └── forge-toast.js        # Notification toasts
└── settings/
    ├── index.html              # Settings landing page
    ├── storage.html           # Storage settings
    ├── network.html           # Network settings
    ├── backup.html            # Backup settings
    └── system.html           # System settings
```

### Why Shadow DOM:
- ✅ **Perfect color isolation** - Ocean Deep theme won't leak between components
- ✅ **Widget reusability** - Each widget is self-contained
- ✅ **No CSS conflicts** - Critical when supporting 8+ wallpapers + theme changes

---

## 5. Dashboard Layout (2x2 Widget Grid)

```
+-------------------------------------------------------+
| [Logo] [Dashboard] [File Station] [Docker] [Mail*]     |
|                                      [🔍][🔔][⊞][⚙][👤]|
+-------------------------------------------------------+
|                                                       |
|  [System Health]            [Storage Overview]         |
|  CPU: 12%                   Pool: main (2.1TB/4TB)   |
|  RAM: 45%                    Disks: 4 healthy          |
|  Temp: 42°C                  ↑ Healthy               |
|                                                       |
|  [Network Status]           [Recent Alerts]            |
|  eth0: 1Gbps                 ⚠️ Disk sdb SMART warning|
|  Firewall: Active            ✅ Backup completed        |
|                              ℹ️ Docker update avail.  |
|                                                       |
+-------------------------------------------------------+
```

### Widget Details:

#### Widget A: System Health
- **Data source**: `GET /api/system/stats`
- **Displays**: CPU usage (%), RAM usage (%), Temperature (°C), Uptime
- **Refresh**: Every 30 seconds
- **Alert thresholds**: CPU >80%, RAM >90%, Temp >60°C

#### Widget B: Storage Overview
- **Data source**: `GET /api/storage/pools`, `/api/storage/drives`
- **Displays**: Pool name, used/total, disk health, hover for details
- **Refresh**: Every 60 seconds
- **Alerts**: Pool >80% full, disk SMART warnings

#### Widget C: Network Status
- **Data source**: `GET /api/system/network`
- **Displays**: Interface name, speed, firewall status, public IP
- **Refresh**: Every 60 seconds
- **Alerts**: Interface down, firewall inactive

#### Widget D: Recent Alerts
- **Data source**: `GET /api/notifications?limit=5`
- **Displays**: Last 5 alerts with severity icons (⚠️ warning, ✅ success, ℹ️ info, 🔥 critical)
- **Refresh**: Every 30 seconds
- **Click action**: Opens full notification panel

---

## 6. Settings Page Structure

```
+-------------------------------------------------------+
| Settings > Storage          [Save] [Cancel]            |
+-------------------------------------------------------+
|                                                       |
|  [📂 Storage] [🌐 Network] [💾 Backup] [⚙ System]  |
|                                                       |
|  --- Storage Settings ---                              |
|  [Pool Management] [Disk Health] [SMART Tests]        |
|  [Hot-Swap Log]                                       |
|                                                       |
+-------------------------------------------------------+
```

### Settings Tabs:
1. **Storage**: Pool management, disk health, SMART tests, hot-swap log
2. **Network**: Interfaces, firewall rules, port forwarding, DNS settings
3. **Backup**: Backup jobs, schedules, cloud providers (Borg, Restic, RClone)
4. **System**: Users, services, startup, updates, power management

### Navigation:
- Top tabs switch between sections
- Each tab loads its own content area
- Breadcrumb shows current location (e.g., "Settings > Storage")
- Save/Cancel buttons appear when editing

---

## 7. File Station Layout

```
+-------------------------------------------------------+
| File Station                [Upload] [New Folder] [⚙️] |
+-------------------------------------------------------+
|  📂 Share1 > Photos > 2026                             |
|                                                         |
|  [📄 file.txt] [📁 folder] [🖼️ photo.jpg] [📹 vid.mp4] |
|  [📁 2025] [📁 backups] [📄 doc.pdf] [🖼️ img.png]  |
|  [📁 projects] [📄 notes.md] [📹 clip.mp4] [📁 src]  |
|                                                         |
|  --- Selected: photo.jpg ---                            |
|  Size: 2.4MB  Modified: 2026-04-27  Permissions: rw  |
+-------------------------------------------------------+
```

### Features:
- **Breadcrumb navigation**: Click to go up directories
- **Grid view**: Icons for files/folders (shown above)
- **List view**: Toggle to detailed table view (name, size, modified, permissions)
- **Actions**: Upload, New Folder, Delete, Rename, Download
- **Selection**: Click to select, double-click to open folder/preview file

---

## 8. Docker Management Layout

```
+-------------------------------------------------------+
| Docker            [+ New Container] [Prune] [Settings]   |
+-------------------------------------------------------+
|  [Running] [Stopped] [All]                              |
|                                                         |
|  ✓ nginx     v1.25    Up 2h    0.0.0.0:80->80      |
|  ✓ postgres  v16      Up 5d    5432/tcp               |
|  ✓ redis     v7       Up 1d    6379/tcp               |
|  ✗ old-api   v2.1     Exit 0   -                      |
|                                                         |
|  --- Selected: nginx ---                              |
|  Stats: CPU 0.5%  RAM 45MB  Network: 1.2GB ↓ 800MB ↑|
|  [Start] [Stop] [Restart] [Logs] [Remove]              |
+-------------------------------------------------------+
```

### Features:
- **Filter tabs**: Running, Stopped, All
- **Container table**: Name, version, status, ports
- **Actions per container**: Start, Stop, Restart, Logs, Remove
- **Selected container details**: Stats (CPU, RAM, Network), volumes, environment
- **Global actions**: New Container (from image), Prune (remove unused), Settings

---

## 9. Wallpaper System

### Specifications:
- **Count**: Minimum 8 HD wallpapers (1920x1080+)
- **Style**: Creative, scenic, atmospheric (NOT plain shapes/gradients)
- **Selection**: User picks via Settings → Appearance
- **Storage**: Served from `/wallpapers/` directory
- **Default**: "Neon Rain" (cyberpunk city at night)

### Wallpaper Themes (Creative & Modern):
1. **"Neon Rain"** - Wet cyberpunk city at night, rain-soaked streets, neon reflections
2. **"Anime Medieval"** - Castle on cliff, cherry blossoms, lanterns, anime art style
3. **"Server Room Glow"** - Dark data center aisle, blue LED lights, rack servers
4. **"Aurora Borealis"** - Northern lights over snowy mountains, dramatic sky
5. **"Tropical Night"** - Palm trees, ocean waves, moonlight, tiki torch glow
6. **"Steampunk Workshop"** - Brass gears, copper pipes, warm Edison bulbs
7. **"Zen Garden"** - Japanese rock garden, maple tree, misty morning
8. **"Space Nebula"** - Colorful cosmic clouds, stars, deep space

### Technical Notes:
- Wallpapers should be JPEG (smaller file size) or WebP (better compression)
- Optimize images for web (compress to ~200-400KB each)
- Store wallpaper metadata (name, author, source) in `wallpapers/manifest.json`

---

## 10. Web Component Examples

### Base Widget Class (`forge-widget.js`):
```javascript
class ForgeWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.data = null;
  }
  
  async connectedCallback() {
    this.render();
    await this.loadData();
    this.startAutoRefresh();
  }
  
  async loadData() {
    // Override in subclasses
  }
  
  update(data) {
    // Override in subclasses
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .widget { 
          background: var(--bg-card); 
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-md);
        }
        h3 { color: var(--text-primary); margin-bottom: var(--space-sm); }
        .content { color: var(--text-secondary); }
      </style>
      <div class="widget">
        <h3>${this.title}</h3>
        <div class="content">Loading...</div>
      </div>
    `;
  }
  
  startAutoRefresh() {
    if (this.refreshInterval) {
      setInterval(() => this.loadData(), this.refreshInterval);
    }
  }
}

customElements.define('forge-widget', ForgeWidget);
```

### System Health Widget (`widget-system.js`):
```javascript
class WidgetSystem extends ForgeWidget {
  constructor() {
    super();
    this.title = 'System Health';
    this.refreshInterval = 30000; // 30 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/system/stats');
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load system stats:', err);
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    content.innerHTML = `
      <div>CPU: ${data.cpu}%</div>
      <div>RAM: ${data.memory.percent}%</div>
      <div>Temp: ${data.temps.cpu}°C</div>
      <div>Uptime: ${data.uptime}</div>
    `;
  }
}

customElements.define('widget-system', WidgetSystem);
```

---

## 11. Implementation Notes

### Technology Stack:
- **HTML5**: Semantic markup, separate pages
- **CSS3**: Custom properties (design tokens), Grid/Flexbox layouts
- **JavaScript (ES6+)**: Web Components (customElements), Shadow DOM, Fetch API
- **No frameworks**: Zero dependencies, native browser features only
- **No build tools**: Direct deployment, no compilation step

### Performance Considerations:
- **Lazy loading**: Widgets load data only when visible (Intersection Observer)
- **Auto-refresh**: Staggered intervals (30s for system, 60s for storage/network)
- **Error handling**: Widgets show "Unable to load" with retry button on fetch failure
- **Caching**: API responses cached briefly (5s) to prevent rapid re-fetches

### Accessibility:
- **Keyboard navigation**: All interactive elements reachable via Tab
- **ARIA labels**: Buttons, widgets, and navigation have proper ARIA attributes
- **Focus indicators**: Visible focus rings (not outline: none)
- **Color contrast**: All text meets WCAG 2.1 AA standard (4.5:1 ratio)

---

## 12. Future Enhancements (Out of Scope)

- **Mobile responsive**: Current design targets desktop/tablet (1024px+)
- **Dark/Light theme toggle**: Currently only "Ocean Deep" dark theme
- **Widget customization**: Drag-and-drop widget arrangement
- **Multi-language support**: i18n framework for translations
- **Real-time updates**: WebSocket connection for instant alerts
- **Advanced search**: Full-text search with filters, saved searches

---

## 13. Success Criteria

The WebGUI v3 is complete when:
1. ✅ Synology-style top navigation renders correctly with Ocean Deep colors
2. ✅ Dashboard shows 4 widgets (System, Storage, Network, Alerts) with live data
3. ✅ Settings page has 4 tabs (Storage, Network, Backup, System) with content
4. ✅ File Station displays files/folders in grid view with breadcrumbs
5. ✅ Docker page lists containers with status, actions, and details
6. ✅ Wallpaper selector shows 8+ scenic wallpapers, applies on select
7. ✅ All pages use Web Components with Shadow DOM
8. ✅ No external dependencies (Google Fonts, CDNs, frameworks)
9. ✅ Responsive to 1024px width (desktop/tablet)
10. ✅ Keyboard navigable with proper ARIA labels

---

**End of Design Specification**
