/* icons.js - ForgeOS SVG Icon System
 * DSM-7 Refined Stroke style — 24x24 viewBox, 1.5px stroke, round caps/joins
 * Stroke/styling handled by .svg-icon CSS — SVGs are clean (no redundant inline attrs)
 * Usage: Icons.render('name') returns SVG string
 */

const Icons = {
  // ─── Navigation & Apps ───

  dashboard() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>`;
  },

  storage() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1" class="fill-accent"/><circle cx="6" cy="18" r="1" class="fill-accent"/></svg>`;
  },

  network() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="2.5"/><path d="M7 7a7 7 0 0 1 10 0M5 5a10 10 0 0 1 14 0M7 17a7 7 0 0 0 10 0M5 19a10 10 0 0 0 14 0"/></svg>`;
  },

  filestation() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M4 19.5V6a2 2 0 0 1 2-2h4.5l2 2.5H20a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M9 12h6M12 9v6"/></svg>`;
  },

  filedb() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M4 5v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2z"/><path d="M4 10h16"/><path d="M12 10v11"/><circle cx="8.5" cy="14" r=".8" class="fill-accent"/><circle cx="15.5" cy="14" r=".8" class="fill-accent"/></svg>`;
  },

  docker() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="8" cy="12" r="1.2" class="fill-accent"/><circle cx="12" cy="12" r="1.2" class="fill-accent"/><circle cx="16" cy="12" r="1.2" class="fill-accent"/></svg>`;
  },

  lxc() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="2" y="2" width="9" height="9" rx="1.5"/><rect x="13" y="2" width="9" height="9" rx="1.5"/><rect x="2" y="13" width="9" height="9" rx="1.5"/><rect x="13" y="13" width="9" height="9" rx="1.5"/></svg>`;
  },

  firewall() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 3L3 8v5c0 5.5 9 8 9 8s9-2.5 9-8V8z"/><circle cx="12" cy="12" r="1.5" class="fill-accent"/><path d="M12 9v2M12 14v.5"/></svg>`;
  },

  fail2ban() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 3L3 8v5c0 5.5 9 8 9 8s9-2.5 9-8V8z"/><path d="M9 9l6 6M15 9l-6 6"/></svg>`;
  },

  // ─── Settings Tabs ───

  settings() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M1 12h2M21 12h2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>`;
  },

  // ─── File Types ───

  file() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/></svg>`;
  },

  folder() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
  },

  image() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5" class="fill-accent"/><path d="M21 15l-5-5-6 6-3-3-4 4"/></svg>`;
  },

  archive() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M10 15h4"/></svg>`;
  },

  code() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg>`;
  },

  // ─── Actions ───

  plus() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M7 12h10"/></svg>`;
  },

  close() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="9"/><path d="M8 8l8 8M16 8l-8 8"/></svg>`;
  },

  search() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="10.5" cy="10.5" r="7"/><path d="M16 16l5 5"/></svg>`;
  },

  refresh() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 3v6h-6"/><path d="M3 12a9 9 0 0 1 15.5-5.5L21 9"/><path d="M3 21v-6h6"/><path d="M21 12a9 9 0 0 1-15.5 5.5L3 15"/></svg>`;
  },

  trash() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M4 6h16M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>`;
  },

  terminal() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M5 17l6-6-6-6M13 19h7"/></svg>`;
  },

  logs() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 7h8M8 12h8M8 17h5"/></svg>`;
  },

  inspect() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/><path d="M11 8v6M8 11h6"/></svg>`;
  },

  restart() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 3v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.5"/></svg>`;
  },

  upload() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/></svg>`;
  },

  download() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></svg>`;
  },

  // ─── Status & Alerts ───

  check() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5 5-6"/></svg>`;
  },

  warning() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 3L3 20h18z"/><path d="M12 9v4M12 17v.5"/></svg>`;
  },

  alert() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 4a8 8 0 0 0-8 8c0 5-3 7-3 7h22s-3-2-3-7a8 8 0 0 0-8-8z"/><path d="M13.5 21a1.5 1.5 0 0 1-3 0"/></svg>`;
  },

  info() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8v.5"/></svg>`;
  },

  critical() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 3L3 21h18z"/><path d="M12 9v5M12 17v.5"/></svg>`;
  },

  // ─── Database ───

  database() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/></svg>`;
  },

  lock() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/><circle cx="12" cy="16" r="1.2" class="fill-accent"/></svg>`;
  },

  unlock() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/><circle cx="12" cy="16" r="1.2" class="fill-accent"/></svg>`;
  },

  snapshot() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="3.5"/><circle cx="12" cy="13" r="1.5" class="fill-accent"/></svg>`;
  },

  stop() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;
  },

  play() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M6 4l14 8-14 8z"/></svg>`;
  },

  box() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M10 9v11"/></svg>`;
  },

  layers() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M12 3L3 8l9 5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 18l9 5 9-5"/></svg>`;
  },

  // ─── Miscellaneous ───

  globe() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 4 9 15 15 0 0 1-4 9 15 15 0 0 1-4-9 15 15 0 0 1 4-9z"/></svg>`;
  },

  backup() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 15v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3"/><path d="M7 9l5-5 5 5"/><path d="M12 4v12"/></svg>`;
  },

  cpu() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1"/><path d="M8 1v3M12 1v3M16 1v3M8 20v3M12 20v3M16 20v3M1 8h3M1 12h3M1 16h3M20 8h3M20 12h3M20 16h3"/></svg>`;
  },

  memory() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><rect x="2" y="7" width="20" height="10" rx="2"/><path d="M8 7v10M12 7v10M16 7v10"/></svg>`;
  },

  activity() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M22 12h-3l-3 9-5-18-3 9H2"/></svg>`;
  },

  chart() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M18 20V9M12 20V4M6 20v-6"/><circle cx="18" cy="9" r="1" class="fill-accent"/><circle cx="12" cy="4" r="1" class="fill-accent"/><circle cx="6" cy="14" r="1" class="fill-accent"/></svg>`;
  },

  uploadArrow() {
    return `<svg viewBox="0 0 24 24" class="svg-icon"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 9l-5-5-5 5M12 4v11"/></svg>`;
  },

  // ─── File Manager Icons (large, 48x48) ───

  fileLg() {
    return `<svg viewBox="0 0 48 48" class="svg-icon-xl"><path d="M30 6H14a4 4 0 0 0-4 4v28a4 4 0 0 0 4 4h20a4 4 0 0 0 4-4V18z"/><path d="M30 6v12h12"/></svg>`;
  },

  folderLg() {
    return `<svg viewBox="0 0 48 48" class="svg-icon-xl"><path d="M44 36a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V12a4 4 0 0 1 4-4h8l4 5h20a4 4 0 0 1 4 4z"/></svg>`;
  },

  imageLg() {
    return `<svg viewBox="0 0 48 48" class="svg-icon-xl"><rect x="6" y="6" width="36" height="36" rx="4"/><circle cx="17" cy="17" r="3" class="fill-accent"/><path d="M42 30l-8-8-10 10-6-6-8 8"/></svg>`;
  },

  archiveLg() {
    return `<svg viewBox="0 0 48 48" class="svg-icon-xl"><rect x="6" y="6" width="36" height="36" rx="4"/><path d="M6 18h36"/><path d="M20 26h8"/></svg>`;
  },

  // ─── Render helper ───

  render(name) {
    if (typeof this[name] === 'function') {
      return this[name]();
    }
    console.warn('Icon not found:', name);
    return '';
  }
};

if (typeof window !== 'undefined') {
  window.Icons = Icons;
}
