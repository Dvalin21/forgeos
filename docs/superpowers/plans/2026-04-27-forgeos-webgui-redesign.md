# ForgeOS WebGUI Hybrid Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign ForgeOS WebGUI from orange-heavy to ZimaOS/Synology DSM hybrid with cyan/blue accents and dramatic black backgrounds

**Architecture:** Direct CSS/HTML modifications to existing WebGUI - replace color tokens, add atmospheric backgrounds, reaccent all UI elements

**Tech Stack:** HTML, CSS (inline)

---

## Files

- Modify: `/home/keith/forgeos-review/web/desktop/index.html`
- Backup: Create timestamped backup before changes

---

### Task 1: Update CSS Root Tokens

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:9-46`

- [ ] **Step 1: Replace `:root` CSS variables**

Replace the entire `:root` block with new palette:

```css
:root {
  /* ══ ACCENTS ══ */
  --accent-cyan:  #00d4ff;
  --accent-blue:  #0091D9;
  --status-ok:    #00e676;
  --status-warn:  #ffb300;
  --status-err:   #ff5252;
  --status-predict:#b388ff;

  /* ══ BACKGROUNDS ══ */
  --bg-void:  #000000;
  --bg-base:  #050505;
  --bg-shell: #0a0a0a;
  --bg-win:   #050505;
  --bg-pane:  #0f0f0f;
  --bg-item:  #141414;
  --bg-hover: #1a1a1a;
  --bg-act:   #202020;
  --border:   #1a1a1a;
  --border-hi:#2a2a2a;

  /* ══ TEXT ══ */
  --t1: #ffffff;
  --t2: #b0b0b0;
  --t3: #606060;

  /* ══ TYPOGRAPHY ══ */
  --ff-ui:   'Barlow', sans-serif;
  --ff-mono: 'IBM Plex Mono', monospace;
  --ff-head: 'Barlow Condensed', sans-serif;
  --tb-h:    44px;
  --tt-h:    30px;
  --r-win:   5px;

  /* ══ SHADOWS ══ */
  --shadow-win:  0 20px 60px rgba(0,0,0,0.8), 0 0 1px rgba(255,255,255,0.1);
  --shadow-menu: 0 8px 32px rgba(0,0,0,0.65);
}
```

- [ ] **Step 2: Commit**

```bash
git add web/desktop/index.html
git commit -m "refactor: update CSS root tokens to hybrid palette"
```

---

### Task 2: Add Dramatic Desktop Background

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:59-66`

- [ ] **Step 1: Replace desktop background with atmospheric gradient**

Replace `#desktop` block:

```css
/* ══ DESKTOP ══ */
#desktop {
  position: fixed;
  inset: 0;
  bottom: var(--tb-h);
  background: 
    radial-gradient(ellipse at 30% 20%, rgba(0,212,255,0.03) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(0,145,217,0.02) 0%, transparent 40%),
    linear-gradient(180deg, #000000 0%, #050505 100%);
  background-size: 100% 100%;
  overflow: hidden;
}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: add atmospheric desktop background gradient"
```

---

### Task 3: Redesign Taskbar

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:68-107`

- [ ] **Step 1: Update taskbar styles - replace orange with cyan**

- Logo hexagon background: `--accent-cyan`
- Open app bottom border: `--accent-cyan`

```css
.logo-hex {
  width: 22px; height: 22px;
  background: var(--accent-cyan);  /* was --forge */
  clip-path: polygon(50% 0%,93% 25%,93% 75%,50% 100%,7% 75%,7% 25%);
  flex-shrink: 0;
  transition: transform 0.2s;
}
#tb-logo:hover .logo-hex { transform: rotate(30deg); }

.tb-pin.open { border-bottom-color: var(--accent-cyan); }  /* was --forge */
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: taskbar - replace orange with cyan accent"
```

---

### Task 4: Redesign Window Chrome

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:180-231`

- [ ] **Step 1: Update window styles for new backgrounds**

```css
.win {
  position: absolute;
  background: var(--bg-win);
  border: 1px solid var(--border);
  border-radius: var(--r-win);
  box-shadow: var(--shadow-win);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 300px;
  min-height: 200px;
}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: window chrome with new border/shadow"
```

---

### Task 5: Update Tabs & Sidebar Accents

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:232-302`

- [ ] **Step 1: Tab active state uses cyan**

```css
.wt { /* Tab styles */
  padding: 6px 13px;
  font-size: 11px;
  font-family: var(--ff-head);
  letter-spacing: 0.5px;
  color: var(--t3);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  transition: color 0.1s;
}
.wt:hover  { color: var(--t2); }
.wt.active { color: var(--accent-cyan); border-bottom-color: var(--accent-cyan); }  /* was --forge */
```

- [ ] **Step 2: Sidebar active item uses cyan**

```css
.sb-item.act {
  background: var(--bg-act);
  color: var(--accent-cyan);  /* was --forge */
  border-left-color: var(--accent-cyan);  /* was --forge */
}
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: tabs and sidebar - cyan accents"
```

---

### Task 6: Update Metric Cards

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:317-343`

- [ ] **Step 1: Metric card accent mappings**

```css
/* ══ METRIC CARDS ══ */
.met.cpu::after  { background: var(--accent-cyan); }  /* was --forge */
.met.ram::after { background: var(--accent-blue); }  /* was steel - blue now */
.met.net::after { background: var(--status-ok); }
.met.tmp::after { background: var(--status-warn); }

/* Value colors */
.met.cpu .m-val { color: var(--accent-cyan); }  /* was --forge */
.met.ram .m-val { color: var(--accent-blue); }  /* was steel - blue now */
.met.net .m-val { color: var(--status-ok); }
.met.tmp .m-val { color: var(--status-warn); }
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: metric cards - cyan/blue accent split"
```

---

### Task 7: Update Storage Pool Elements

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:344-424`

- [ ] **Step 1: Pool badge uses blue instead of orange**

```css
.pool-badge {
  font-family: var(--ff-mono); font-size: 9px;
  padding: 2px 7px; border-radius: 3px;
  background: rgba(0,145,217,0.1);  /* was rgba(232,93,4,0.1) */
  color: var(--accent-blue);
  border: 1px solid rgba(0,145,217,0.25);  /* was rgba(232,93,4,0.25) */
  letter-spacing: 0.5px;
}
```

- [ ] **Step 2: Pool fill bar uses blue gradient**

```css
.pool-fill { height: 100%; background: linear-gradient(90deg, var(--accent-blue), #00c3ff); border-radius: 3px; }
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: storage pools - blue accent (#0091D9)"
```

---

### Task 8: Update Buttons & Primary Actions

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:505-515`

- [ ] **Step 1: Primary button uses cyan**

```css
.btn.primary { background: var(--accent-cyan); border-color: var(--accent-cyan); color: #000; font-weight: 600; }  /* was --forge */
.btn.primary:hover { background: #00b8e6; }  /* darker cyan */
```

- [ ] **Step 2: Input focus states use cyan**

```css
.form-input:focus { border-color: var(--accent-cyan); }
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: buttons - cyan primary actions"
```

---

### Task 9: Update Fan/Sensor Cards

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:537-546`

- [ ] **Step 1: Fan RPM uses cyan**

```css
.fan-rpm { font-family: var(--ff-mono); font-size: 18px; font-weight: 600; color: var(--accent-cyan); }  /* was --forge */
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: sensor displays - cyan accents"
```

---

### Task 10: Log Line Accents

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html:446-458`

- [ ] **Step 1: Ensure log INFO uses cyan**

```css
.ll-i    { color: var(--accent-cyan); width: 36px; flex-shrink: 0; }  /* was --forge */
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: log lines - cyan INFO level"
```

---

### Task 11: Verify No Orange Remains

**Files:**
- Modify: `/home/keith/forgeos-review/web/desktop/index.html`

- [ ] **Step 1: Search for any remaining #e85d04 or --forge**

```bash
grep -n "#e85d04\|--forge" web/desktop/index.html
```

- [ ] **Step 2: If any found, replace with appropriate accent**

- [ ] **Step 3: Commit any fixes**

```bash
git commit -m "fix: remove any remaining orange tokens"
```

---

### Task 12: Final Verification

- [ ] **Step 1: Verify all acceptance criteria met**

```bash
# Check no orange
grep -c "#e85d04\|forge" web/desktop/index.html || echo "0 - PASS"

# Check cyan present
grep -c "00d4ff\|accent-cyan" web/desktop/index.html

# Check blue present  
grep -c "0091D9\|accent-blue" web/desktop/index.html
```

- [ ] **Step 2: Final commit**

```bash
git commit -m "feat: complete WebGUI hybrid redesign

- Replace orange with cyan/blue accents
- Add atmospheric black backgrounds
- Full black (#000000) with depth gradients"
```

---

## Plan Complete

**Execution approach?**

1. **Subagent-Driven (recommended)** - Fresh subagent per task, faster iteration
2. **Inline Execution** - Batch execute in this session