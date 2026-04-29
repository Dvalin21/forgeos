# ForgeOS NAS Navigation Design Specification

**Date**: 2026-04-28  
**Status**: Approved (Brainstorming Phase Complete)  
**Version**: 1.0  
**Inspiration**: Synology DSM (gold standard for NAS interfaces)

---

## 1. Overview

ForgeOS NAS navigation will follow **Synology DSM's proven pattern**:
- **Taskbar** = System tools ONLY (Dashboard, Storage, Network, Settings)
- **Applications** = Desktop icons + Start Menu (File Station, ForgeFileDB, Docker, Terminal)
- **NO emojis** - Use SVG icons (professional NAS standard)

### Key Design Principles:
- **Follow NAS conventions** - Users expect Synology-style navigation (20+ years of UX research)
- **Applications ≠ System Tools** - ForgeFileDB is an app, not a system function
- **Professional appearance** - No emojis, use SVG icons or icon fonts
- **Scalable** - Adding apps doesn't clutter the taskbar

---

## 2. Color Palette (Current Hybrid Design)

```css
:root {
  /* Accents - Hybrid ZimaOS/Synology */
  --accent-cyan:  #00d4ff;   /* System metrics, CPU, Dashboard */
  --accent-blue:  #0091D9;   /* Storage, drives, pools */
  
  /* Status Colors */
  --status-ok:    #00e676;
  --status-warn:  #ffb300;
  --status-err:   #ff5252;
  --status-predict: #b388ff;
  
  /* Backgrounds */
  --bg-void:  #000000;
  --bg-base:  #050505;
  --bg-shell: #0a0a0a;
  --bg-win:   #050505;
  
  /* Text */
  --t1: #ffffff;
  --t2: #b0b0b0;
  --t3: #606060;
}
```

### ForgeFileDB Special Color:
```css
.filedb { --filedb: #7c4dff; }  /* Purple for FileDB only */
```

---

## 3. Navigation Architecture (Synology Style)

### 3.1 Taskbar Structure (System Tools ONLY)

```
[Logo] [Dashboard] [Storage] [Network] [Settings] [...] [Search] [Notifications] [Power]
```

| Element | Type | Purpose | Implementation |
|---------|------|---------|-----------------|
| **Logo** | Button | Links to Dashboard | SVG hexagon, cyan accent |
| **Dashboard** | Window toggle | System overview, widgets | `data-win="win-dash"` |
| **Storage** | Window toggle | Pool/drive management | `data-win="win-storage"` |
| **Network** | Window toggle | VPN, firewall, nginx | `data-win="win-net"` |
| **Settings** | Window toggle | Control panel | `data-win="win-settings"` |
| **Search** | Button | Global search | Future feature |
| **Notifications** | Button | System alerts | Future feature |
| **Power** | Menu | Shutdown/restart/logout | Future feature |

### 3.2 Applications (NOT in Taskbar)

Following Synology DSM's **Main Menu + Desktop Icons** pattern:

| Application | Access Method | Page/Path | Icon Color |
|-------------|----------------|----------|------------|
| **File Station** | Desktop icon + Start menu | `/desktop/filestation.html` | Blue (--accent-blue) |
| **ForgeFileDB** | Desktop icon + Start menu | `/desktop/filedb.html` | Purple (--filedb) |
| **Docker** | Desktop icon + Start menu | `/desktop/docker.html` | Blue-gray |
| **Terminal** | Desktop icon + Start menu | Future: `/desktop/terminal.html` | Green |

---

## 4. Icon System (NO EMOJIS)

### 4.1 Icon Implementation

**DO NOT USE EMOJIS** - Professional NAS interfaces (Synology, TrueNAS) use:
- SVG icons (preferred for custom shapes like hexagon logo)
- Icon fonts (Font Awesome, custom icon font)
- CSS-drawn icons (for simple shapes)

### 4.2 Current Icons to Replace

| Current (WRONG) | Replacement (SVG/Icon Font) | Usage |
|-------------------|---------------------------|--------|
| 🖥️ | SVG hexagon or `<forge-logo>` component | ForgeOS logo |
| 📂 | SVG folder icon | File Station |
| 💽 | SVG database icon | Storage |
| 🗄 | SVG database/cylinder | ForgeFileDB |
| 🌐 | SVG globe/network | Network |
| ⚙ | SVG gear/settings | Settings |

### 4.3 Forge-Topnav Component

The `forge-topnav` web component should provide:
- SVG hexagon logo (cyan, `#00d4ff`)
- Consistent icon rendering
- Hover/active states
- No emoji dependencies

---

## 5. Taskbar HTML Structure

```html
<div id="taskbar">
  <div id="tb-logo">
    <svg class="logo-hex" viewBox="0 0 24 24">
      <!-- Cyan hexagon SVG -->
    </svg>
    <div class="logo-txt">ForgeOS</div>
  </div>
  
  <div id="tb-pins">
    <div class="tb-pin open" data-win="win-dash">
      <svg class="p-ico"><!-- Dashboard icon --></svg>
      <span class="p-lbl">Dashboard</span>
    </div>
    <div class="tb-pin" data-win="win-storage">
      <svg class="p-ico"><!-- Storage icon --></svg>
      <span class="p-lbl">Storage</span>
    </div>
    <div class="tb-pin" data-win="win-net">
      <svg class="p-ico"><!-- Network icon --></svg>
      <span class="p-lbl">Network</span>
    </div>
    <div class="tb-pin" data-win="win-settings">
      <svg class="p-ico"><!-- Settings icon --></svg>
      <span class="p-lbl">Settings</span>
    </div>
  </div>
  
  <div id="tb-tray">
    <!-- Search, Notifications, Power menu -->
  </div>
</div>
```

---

## 6. Desktop Icons (Applications)

```html
<div id="desktop">
  <!-- Desktop icon for File Station -->
  <div class="desktop-icon" onclick="window.location='/desktop/filestation.html'">
    <svg class="icon"><!-- Folder icon (blue) --></svg>
    <span>File Station</span>
  </div>
  
  <!-- Desktop icon for ForgeFileDB -->
  <div class="desktop-icon" onclick="window.location='/desktop/filedb.html'">
    <svg class="icon" style="color:var(--filedb)"><!-- Database icon --></svg>
    <span>ForgeFileDB</span>
  </div>
</div>
```

---

## 7. Why This Design?

### 7.1 Research-Based Decisions

| NAS System | Navigation Style | Lesson for ForgeOS |
|------------|------------------|----------------------|
| **Synology DSM** | Taskbar = system, Apps = Main Menu | ✅ Follow this pattern |
| **TrueNAS SCALE** | Left sidebar + top toolbar | Left sidebar works for enterprise |
| **Unraid** | Simple top bar, plugins page | Clean, uncluttered |
| **OpenMediaVault** | Left sidebar admin | Traditional, functional |

### 7.2 Why NOT Emojis?

1. **Professional appearance** - Synology, TrueNAS don't use emojis
2. **Consistency** - Emojis render differently across OS/platforms
3. **Scalability** - Icon fonts/SVG scale better
4. **Accessibility** - SVG icons have better ARIA support

### 7.3 Why ForgeFileDB NOT in Taskbar?

1. **It's an application**, not a system tool (like File Station)
2. **Synology pattern** - Apps live in Main Menu/Desktop, not taskbar
3. **Scalability** - What if user installs 10 apps? Taskbar would be cluttered
4. **User expectations** - NAS users expect apps in "Start Menu" style

---

## 8. Implementation Plan

### Phase 1: Remove Emojis (High Priority)
1. Replace all emojis in `index.html` with SVG/icons
2. Update `forge-topnav.js` to use SVG hexagon logo
3. Create icon sprite or use icon font

### Phase 2: Remove Apps from Taskbar (High Priority)
1. Remove File Station from `#tb-pins` (move to desktop icon)
2. Remove ForgeFileDB from `#tb-pins` (move to desktop icon)
3. Keep only: Dashboard, Storage, Network, Settings

### Phase 3: Create Desktop Icon System (Medium Priority)
1. Create desktop icon CSS/component
2. Add File Station icon → links to `/desktop/filestation.html`
3. Add ForgeFileDB icon → links to `/desktop/filedb.html`
4. Add Docker icon → links to `/desktop/docker.html`

### Phase 4: Start Menu (Low Priority - Future)
1. Create "Main Menu" button in taskbar
2. Show all installed applications
3. Allow pinning apps to desktop

---

## 9. Files to Modify

| File | Changes |
|------|---------|
| `web/desktop/index.html` | Remove emojis, fix taskbar structure, add desktop icons |
| `web/desktop/components/forge-topnav.js` | SVG logo, proper icon system |
| `web/desktop/css/forgeos.css` | Desktop icon styles, taskbar fixes |

---

## 10. Success Criteria

The NAS Navigation is complete when:

1. ✅ Taskbar contains ONLY: Logo, Dashboard, Storage, Network, Settings
2. ✅ NO emojis anywhere in the UI (use SVG/icons)
3. ✅ File Station accessible via desktop icon → `/desktop/filestation.html`
4. ✅ ForgeFileDB accessible via desktop icon → `/desktop/filedb.html`
5. ✅ ForgeFileDB has purple accent (`#7c4dff`) on its icon/page
6. ✅ Navigation follows Synology DSM conventions
7. ✅ Scalable - adding apps doesn't clutter taskbar

---

## 11. Anti-Patterns to Avoid

❌ **Don't use emojis** - Unprofessional, inconsistent rendering  
❌ **Don't put apps in taskbar** - Breaks NAS conventions  
❌ **Don't hardcode colors** - Use CSS variables (--accent-cyan, --filedb)  
❌ **Don't clutter the UI** - Follow "less is more" principle  

---

**End of Design Specification**
