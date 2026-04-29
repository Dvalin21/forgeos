# ForgeOS WebGUI Redesign — ZimaOS/Synology DSM Hybrid

**Date:** 2026-04-27
**Status:** Approved
**Reference:** Hybrid of ZimaOS (full black, cyan accent) + Synology DSM (blue accent, desktop paradigm)

---

## Overview

Redesign the ForgeOS WebGUI to combine:
- ZimaOS: full-black backgrounds with cyan accents
- Synology DSM: desktop window paradigm with blue storage accents

**Eliminate all orange** — `#e85d04` and variants completely removed.

---

## Color Palette

### Primary Accents

| Token | Hex | Usage |
|-------|-----|-------|
| `--accent-cyan` | `#00d4ff` | System metrics, power, tech features, CPU temp, fans |
| `--accent-blue` | `#0091D9` | Storage pools, drives, capacity bars |

### Status Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `--status-ok` | `#00e676` | Healthy, online, OK, good |
| `--status-warn` | `#ffb300` | Warnings, spinning, checking, rebuilding, temps |
| `--status-err` | `#ff5252` | Errors, critical, failed, SMART fail |
| `--status-predict` | `#b388ff` | Predictive failure, S.M.A.R.T., smart features |

### Neutrals

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-void` | `#000000` | Desktop / outermost background |
| `--bg-base` | `#050505` | Window backgrounds |
| `--bg-shell` | `#0a0a0a` | Taskbar, sidebar |
| `--bg-pane` | `#0f0f0f` | Panels, cards |
| `--bg-item` | `#141414` | List items, inputs |
| `--bg-hover` | `#1a1a1a` | Hover states |
| `--bg-active` | `#202020` | Active/selected states |
| `--border` | `#1a1a1a` | Subtle borders |
| `--border-hi` | `#2a2a2a` | Highlighted borders |
| `--t1` | `#ffffff` | Primary text |
| `--t2` | `#b0b0b0` | Secondary text |
| `--t3` | `#606060` | Tertiary/muted text |

---

## Background Atmosphere

Do not use flat black. Create depth through:

### 1. Desktop Gradient Mesh
```css
background: radial-gradient(ellipse at 30% 20%, #0a0a0f 0%, #000000 50%, #000000 100%);
```

### 2. Subtle Grid Pattern (optional, CSS-only)
```css
background-image: 
  linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
  linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
background-size: 50px 50px;
```

### 3. Ambient Glow (accent-dependent)
```css
/* Behind active/selected items with accent-cyan */
box-shadow: 0 0 20px rgba(0,212,255,0.1);

/* Behind storage elements with accent-blue */
box-shadow: 0 0 20px rgba(0,145,217,0.1);
```

### 4. Window Float
Windows float above desktop with subtle shadow:
```css
box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 1px rgba(255,255,255,0.1);
border: 1px solid var(--border);
```

---

## Typography (Unchanged)

| Token | Font | Usage |
|-------|------|-------|
| `--ff-ui` | Barlow, sans-serif | UI text |
| `--ff-mono` | IBM Plex Mono, monospace | Values, badges |
| `--ff-head` | Barlow Condensed, sans-serif | Headers, titles |

| Token | Size |
|-------|------|
| `--tb-h` | 44px (taskbar) |
| `--tt-h` | 30px (window titlebar) |

---

## Component Design

### Taskbar
- **Background:** `#0a0a0a` with bottom border `#1a1a1a`
- **Logo:** Hexagon uses `--accent-cyan` instead of removed orange
- **Active app indicator:** Bottom border `--accent-cyan`
- **Clock:** Monospace white

### Windows
- **Background:** `#050505`
- **Titlebar:** `#0f0f0f`
- **Active title:** White `--t1`
- **Inactive title:** Gray `--t2`
- **Close button:** Red hover state

### Sidebar
- **Background:** `#0a0a0a`
- **Section headers:** Uppercase, letter-spacing 2px, `--t3`
- **Item hover:** `#1a1a1a`
- **Item active:** Background `#141414` + left border `--accent-cyan`

### Metric Cards (CPU, RAM, Network, Temp)
- **Accent bar on bottom:** Uses respective accent color
- **CPU:** `--accent-cyan`
- **RAM:** `--accent-blue` (new — was steel)
- **Network:** `--status-ok`
- **Temp:** `--status-warn`

### Storage Pools
- **Pool badge:** `--accent-blue` background/border
- **Health indicator:** Uses status colors (green/amber/red/purple)
- **Capacity bar:** Gradient from `--accent-blue` (darker to lighter)

### Drive Cards
- **Status stripe on top:** Uses status color
- **S.M.A.R.T. warning:** Purple `--status-predict` border/glow
- **Temperature:** Using status colors (green→amber→red scale)

---

## Tab System

### Window Tabs
- **Inactive:** Gray text `--t3`
- **Active:** `--accent-cyan` bottom border (system tabs) or `--accent-blue` (storage tabs)
- **Alternative:** Could differentiate by context

### Tab Panels
- Vertical sidebar + content area layout (current)
- Tabs switch panel content

---

## Specific Element Mappings

| Element | Old (Orange) | New |
|---------|--------------|-----|
| Logo hexagon | `#e85d04` | `--accent-cyan` |
| Active app indicator | `#e85d04` | `--accent-cyan` |
| Tab active underline | `#e85d04` | `--accent-cyan` / `--accent-blue` |
| CPU card accent | `#e85d04` | `--accent-cyan` |
| RAM card accent | `#4a8ab0` | `--accent-blue` |
| Pool badge bg | `rgba(232,93,4,0.1)` | `rgba(0,145,217,0.1)` |
| Pool badge border | `rgba(232,93,4,0.25)` | `rgba(0,145,217,0.25)` |
| Primary button | `#e85d04` | `--accent-cyan` |
| Capacity bar | `#e85d04` gradient | `--accent-blue` gradient |
| SMART/predictive | `#9933cc` | `--status-predict` (keep purple) |

---

## Implementation Priority

1. **CSS Variables** — Update `:root` token definitions
2. **Background Atmosphere** — Desktop gradient + optional grid
3. **Taskbar** — Replace orange with cyan
4. **Metric Cards** — Reaccent CPU (cyan), RAM (blue)
5. **Storage** — Replace pool/drive orange with blue
6. **Tabs** — Add accent differentiation
7. **Buttons/Interactions** — Cyan primary

---

## Files

- `/home/keith/forgeos-review/web/desktop/index.html` — Main WebGUI (full redesign)
- `/home/keith/forgeos-review/web/filedb.html` — FileDB interface (update similarly)

---

## Acceptance Criteria

- [ ] No `#e85d04` orange anywhere in CSS
- [ ] Background is full black `#000000` with depth
- [ ] Cyan `#00d4ff` used for system/tech elements
- [ ] Blue `#0091D9` used for storage elements  
- [ ] Status colors (green/amber/red/purple) functional
- [ ] Dramatic atmosphere — not flat black
- [ ] Desktop paradigm maintained (windows floating above)