# ForgeOS WebGUI Redesign Specification v2.0

> **Version:** 2.0  
> **Date:** 2026-04-26  
> **Status:** Design approved - Ready for implementation

---

## 1. Design Overview

### 1.1 Purpose
Complete redesign of ForgeOS WebGUI inspired by ZimaOS, Synology DSM, Proxmox, and Homarr - combining the best elements into a modern, sophisticated NAS management interface.

### 1.2 Core Principles

| Principle | Implementation |
|---------|--------------|
| Hybrid Layout | Left sidebar + Top bar + Widget dashboard |
| Sophisticated Dark | Charcoal backgrounds, muted accents |
| Floating Windows | Draggable, resizable, overlap capable |
| Monospace Typography | IBM Plex Mono throughout |
| Hybrid App Access | Desktop icons + App drawer |

---

## 2. Layout Structure

### 2.1 Main Layout

```
┌─────────────────────────────────────────────────────────────┐
│  TOP BAR: Search | Context Title | User Menu              │ ← Top Bar
├──────────┬──────────────────────────────────────────────┤
│          │                                            │
│  SIDE    │           MAIN CONTENT AREA                 │
│  BAR     │                                            │
│  (collap- │   ┌─────────┐  ┌─────────┐               │
│   sible)  │   │ Widget  │  │ Widget  │  ← Dashboard │
│          │   └─────────┘  └─────────┘               │
│ • Dash   │                                            │
│ • Apps  │   ┌─────────┐  ┌─────────┐               │
│ • Stor  │   │ Widget  │  │ Widget  │               │
│ • Set   │   └─────────┘  └─────────┘               │
│          │                                            │
├──────────┴──────────────────────────────────────────────┤
│  TASKBAR: Dashboard | Apps | Storage | Settings           │ ← 4 pins
└─────────────────────────────────────────────────────┘
```

### 2.2 Sidebar

| Property | Value |
|----------|-------|
| Width expanded | 200px |
| Width collapsed | 56px (icons only) |
| Position | Left, fixed |
| Toggle | Click hamburger / keyboard shortcut |
| Items | Icon + Label |

### 2.3 Top Bar

| Element | Position | Function |
|---------|----------|----------|
| Search | Left | Global search |
| Context | Center | Current page title |
| User Menu | Right | User info, logout |

### 2.4 Taskbar

| Pin | Function |
|-----|----------|
| Dashboard | Main widget dashboard |
| Apps | Docker app browser |
| Storage | Pool management |
| Settings | Full configuration |

---

## 3. Visual Design

### 3.1 Color Palette

| Name | Hex | Usage |
|------|-----|-------|
| bg-void | #0a0a0f | Main background |
| bg-base | #141418 | Window background |
| bg-surface | #1a1a24 | Cards/panels |
| bg-elevated | #222230 | Hover/cards |
| accent-primary | #e85d04 | Forge orange (muted) |
| accent-secondary | #4a8ab0 | Steel blue |
| accent-success | #3daa60 | Green status |
| accent-warning | #d4860a | Yellow status |
| accent-danger | #cc3344 | Red status |
| text-primary | #f0f0f4 | Main text |
| text-secondary | #a0a0b0 | Muted text |
| text-muted | #606070 | Disabled |

### 3.2 Typography

| Element | Font | Size | Weight |
|--------|------|------|--------|
| Headers | IBM Plex Mono | 18-24px | 600 |
| Body | IBM Plex Mono | 13px | 400 |
| Labels | IBM Plex Mono | 11px | 500 |
| Data | IBM Plex Mono | 13px | 400 |
| Code | IBM Plex Mono | 12px | 400 |

### 3.3 Spacing

| Token | Value |
|-------|-------|
| xs | 4px |
| sm | 8px |
| md | 16px |
| lg | 24px |
| xl | 32px |

### 3.4 Effects

| Effect | Implementation |
|--------|--------------|
| Shadows | `0 4px 12px rgba(0,0,0,0.3)` |
| Card shadows | `0 2px 8px rgba(0,0,0,0.2)` |
| Borders | `1px solid #2a2a32` |
| Border radius | 8px cards, 4px buttons |
| Transitions | 200ms ease-out |

---

## 4. Desktop & Windows

### 4.1 Desktop

| Element | Behavior |
|---------|----------|
| Background | Customizable wallpaper |
| Icons | User-pinned shortcuts |
| Double-click | Open window |
| Drag | Reorder icons |
| Context menu | Right-click |

### 4.2 App Drawer

| Element | Behavior |
|---------|----------|
| Trigger | Grid icon in corner |
| Layout | Scrollable grid (4 columns) |
| Categories | Filter tabs |
| Search | Filter by name |

### 4.3 Floating Windows

| Property | Behavior |
|----------|---------|
| Draggable | By title bar |
| Resizable | By edges/corners |
| Overlap | Multiple windows allowed |
| Z-index | Click to bring forward |
| Minimize | To taskbar |
| Maximize | Fill content area |
| Close | X button |

### 4.4 Window Controls

| Control | Position | Function |
|---------|----------|----------|
| Minimize | Title bar left | Min to taskbar |
| Maximize | Title bar left | Toggle maximize |
| Close | Title bar right | Close window |
| Settings | Title bar right | Window options |

---

## 5. Panels & Features

### 5.1 Window Structure

| Window | Purpose | Key Features |
|--------|---------|-------------|
| Dashboard | System overview | Widget grid with gauges |
| Storage | Pool management | Drive heat map, snapshots |
| Apps | Docker browser | App grid, one-click install |
| Network | Networking | Interfaces, VPN, firewall |
| Backup | Backup tools | Borg/Restic/RClone |
| Shares | File sharing | SMB/NFS/FTP |
| Mail | Mail server | MailCow status |
| Auth | Users/SSO | LDAP, users |
| Settings | Configuration | Unified settings |

### 5.2 Navigation

- **Desktop**: Click icons to open windows
- **App Drawer**: Grid icon → scrollable app list
- **Taskbar**: 4 pinned quick access
- **Sidebar**: Full navigation with labels

---

## 6. Dashboard Widgets

### 6.1 Widget Grid

| Layout | Configuration |
|--------|-------------|
| Columns | Responsive (2-4) |
| Gap | 16px |
| Padding | 16px |

### 6.2 Widget Types

| Widget | Content | Size |
|--------|---------|------|
| System Gauge | CPU/RAM/Storage | 1x1 |
| Drive Health | Heat map | 2x1 |
| Docker Status | Container count + quick stats | 1x1 |
| Alerts | Active warnings | 1x1 |

---

## 7. Taskbar

### 7.1 Structure

| Element | Implementation |
|---------|--------------|
| Position | Fixed bottom |
| Height | 44px |
| Background | Surface color |
| Items | 4 pinned icons + labels |

### 7.2 Pinned Items

| Pin | Icon | Label | Function |
|-----|------|-------|----------|
| 1 | ◈ | Dashboard | Widget dashboard |
| 2 | ◉ | Apps | Docker app browser |
| 3 | ⬡ | Storage | Pool management |
| 4 | ⚙ | Settings | System settings |

---

## 8. Responsive Behavior

### 8.1 Breakpoints

| Breakpoint | Width | Layout Change |
|------------|-------|-------------|
| Desktop | >1200px | Full sidebar |
| Tablet | 768-1200px | Collapsed sidebar |
| Mobile | <768px | Hidden sidebar, hamburger |

### 8.2 Touch Support

- Drag handles larger for touch
- Hover states disabled
- Long-press for context menu

---

## 9. Implementation Checklist

- [ ] New CSS design system (CSS custom properties)
- [ ] Sidebar component (collapsible)
- [ ] Top bar component
- [ ] Taskbar component (4 pins)
- [ ] Desktop component (wallpaper, icons)
- [ ] App drawer component
- [ ] Window system (drag, resize, focus)
- [ ] Dashboard widgets
- [ ] All panel windows
- [ ] Login screen
- [ ] Wallpapers

---

## 10. File Structure

```
web/
├── desktop/
│   ├── index.html      # Main entry
│   ├── css/
│   │   └── forgeos.css  # Design system
│   └── js/
│       ├── app.js       # Main app
│       ├── desktop.js  # Desktop logic
│       ├── window.js   # Window management
│       └── widgets.js  # Dashboard widgets
└── wallpapers/        # New designs
```

---

**Spec Status:** ✓ Ready for implementation  
**Saved to:** `docs/superpowers/specs/2026-04-26-forgeos-webgui-v2.md`