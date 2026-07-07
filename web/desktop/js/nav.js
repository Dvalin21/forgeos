/* ForgeOS — shared sidebar navigation.
 *
 * Single source of truth for the left-hand menu. Every page loads this; it
 * builds the sidebar from ONE definition and injects it, so adding/reordering
 * a nav item is a one-line edit here, not a change across seven HTML files.
 *
 * Reuses the existing .sidebar/.brand/.nav-title/.nav a markup + classes that
 * already ship in the pages (and the dashboard) — this only supplies the
 * structure and wires it in; the look comes from each page's existing CSS.
 *
 * Pages that don't exist yet are listed but rendered disabled ("soon") so the
 * shell is navigable from day one and the IA is visible.
 */
(function () {
  "use strict";

  // --- icons (stroke style matches the existing `.nav svg` rules) -----------
  var ICON = {
    dashboard: '<path d="M4 13h7V4H4zM13 20h7V4h-7zM4 20h7v-5H4z"/>',
    storage:   '<path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/><path d="M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    filedb:    '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    files:     '<path d="M3.8 6.5h6.5l1.8 2h8.1v9.8c0 1.1-.9 2-2 2H5.8c-1.1 0-2-.9-2-2z"/><path d="M3.8 8.5V5.7c0-1.1.9-2 2-2h4.1l1.7 1.8h5.2c1.1 0 2 .9 2 2v1"/>',
    shares:    '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.3 10.8l7.4-3.6M8.3 13.2l7.4 3.6"/>',
    apps:      '<path d="M5 5h6v6H5zM13 5h6v6h-6zM5 13h6v6H5zM13 13h6v6h-6z"/>',
    proxy:     '<path d="M4 7h9a4 4 0 0 1 0 8H7"/><path d="M9 12l-2.5 3M9 12L6.5 9"/><circle cx="19" cy="7" r="2"/>',
    firewall:  '<path d="M12 3l7 3v5c0 4.8-2.9 8.2-7 10-4.1-1.8-7-5.2-7-10V6z"/><path d="M9.5 12l1.8 1.8 3.7-4"/>',
    vpn:       '<path d="M12 3l7 3v5c0 4.8-2.9 8.2-7 10-4.1-1.8-7-5.2-7-10V6z"/><path d="M12 9v3M12 15h.01"/>',
    users:     '<path d="M16 19c0-2.2-1.8-4-4-4s-4 1.8-4 4"/><circle cx="12" cy="9" r="3"/><path d="M18 10.5c1.7.3 3 1.8 3 3.5M6 10.5C4.3 10.8 3 12.3 3 14"/>',
    settings:  '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z"/><path d="M19.4 15a1.8 1.8 0 0 0 .4 2l.1.1-2.1 3.6-.2-.1a1.8 1.8 0 0 0-2.1.3l-.2.1h-4.2l-.2-.1a1.8 1.8 0 0 0-2.1-.3l-.2.1-2.1-3.6.1-.1a1.8 1.8 0 0 0 .4-2 8 8 0 0 1 0-6 1.8 1.8 0 0 0-.4-2l-.1-.1 2.1-3.6.2.1a1.8 1.8 0 0 0 2.1-.3l.2-.1h4.2l.2.1a1.8 1.8 0 0 0 2.1.3l.2-.1 2.1 3.6-.1.1a1.8 1.8 0 0 0-.4 2 8 8 0 0 1 0 6z"/>',
    backup:    '<path d="M12 5v8l4 2"/><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/>',
    activity:  '<path d="M4 12h3l2 5 4-12 2 7h5"/>',
    notify:    '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8z"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    imaging:   '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="12" cy="12" r="3.2"/><path d="M12 4v2M12 18v2"/>'
  };

  // --- the menu: one definition, grouped per the approved IA ----------------
  // page === null  -> not built yet, rendered disabled ("soon").
  var GROUPS = [
    { title: null, items: [
      { id: "dashboard", label: "Dashboard", icon: "dashboard", page: "index.html" }
    ]},
    { title: "Storage", items: [
      { id: "storage",  label: "Storage",       icon: "storage", page: "storage.html" },
      { id: "forgedb",  label: "ForgeFileDB",   icon: "filedb",  page: "forgedb.html" },
      { id: "files",    label: "File Manager",  icon: "files",   page: "files.html" },
      { id: "shares",   label: "Shares (SMB)",  icon: "shares",  page: "shares.html" }
    ]},
    { title: "Apps & Containers", items: [
      { id: "apps",     label: "Apps & Containers", icon: "apps", page: "apps.html" }
    ]},
    { title: "Network", items: [
      { id: "proxy",    label: "Reverse Proxy", icon: "proxy",    page: "reverse-proxy.html" },
      { id: "firewall", label: "Firewall",      icon: "firewall", page: "firewall.html" },
      { id: "vpn",      label: "VPN",           icon: "vpn",      page: "vpn.html" }
    ]},
    { title: "Access", items: [
      { id: "security", label: "Security",      icon: "firewall", page: "security.html" },
      { id: "users",    label: "Users",         icon: "users",    page: "users.html" }
    ]},
    { title: "System", items: [
      { id: "settings", label: "Settings",      icon: "settings", page: "settings.html" },
      { id: "backup",   label: "Backup & DR",   icon: "backup",   page: "backup.html" },
      { id: "activity", label: "Activity Log",  icon: "activity", page: "activity.html" },
      { id: "notify",   label: "Notifications", icon: "notify",   page: null },
      { id: "imaging",  label: "Imaging",       icon: "imaging",  page: null }
    ]}
  ];

  function svg(key) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICON[key] || "") + "</svg>";
  }

  // current page file name, e.g. "storage.html" (default to dashboard)
  function currentPage() {
    var p = (location.pathname.split("/").pop() || "").toLowerCase();
    return p && p.indexOf(".html") !== -1 ? p : "index.html";
  }

  function buildSidebar() {
    var here = currentPage();
    var aside = document.createElement("aside");
    aside.className = "sidebar";
    aside.id = "sidebar";
    aside.setAttribute("aria-label", "Primary navigation");

    var html = '' +
      '<div class="brand">' +
        '<div class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24">' +
          '<path d="M4 7.5h16v9H4z"/><path d="M7 10.5h3M14 10.5h3M7 14h10"/><path d="M9 4.5h6M9 19.5h6"/>' +
        '</svg></div>' +
        '<div><h1>ForgeNAS</h1><p>Control Center</p></div>' +
      '</div>';

    // scrollable middle: brand stays pinned on top, footer pinned at bottom
    html += '<div class="nav-scroll">';
    GROUPS.forEach(function (g) {
      if (g.title) html += '<div class="nav-title">' + g.title + "</div>";
      html += '<nav class="nav">';
      g.items.forEach(function (it) {
        var TILE = { dashboard:"t-dash", storage:"t-store", forgedb:"t-db", files:"t-files",
                 shares:"t-share", apps:"t-apps", proxy:"t-proxy", firewall:"t-fw", security:"t-fw",
                 vpn:"t-vpn", users:"t-users" };
        var icon = '<span class="tile ' + (TILE[it.id] || "t-sys") + '">' + svg(it.icon) + "</span>";
        if (it.page) {
          var active = it.page === here ? ' class="active"' : "";
          html += '<a' + active + ' href="' + it.page + '">' + icon + it.label + "</a>";
        } else {
          // not built yet: non-clickable, with a "soon" pill
          html += '<span class="nav-soon" aria-disabled="true">' + icon +
                  '<span class="nav-soon-label">' + it.label + "</span>" +
                  '<span class="soon-pill">soon</span></span>';
        }
      });
      html += "</nav>";
    });
    html += "</div>"; // close .nav-scroll
    html += '' +
      '<div class="sidebar-footer">' +
        '<strong id="sf-title">NAS Health: <span data-live="health">checking…</span></strong>' +
        '<span id="sf-detail">Reading pool state, SMART status, and snapshot replication…</span>' +
      "</div>";

    aside.innerHTML = html;
    return aside;
  }

  // a few rules the per-page CSS doesn't define: the disabled "soon" rows.
  // Uses existing theme vars (with fallbacks) so it inherits each page's look.
  function injectStyles() {
    if (document.getElementById("forgeos-nav-style")) return;
    var s = document.createElement("style");
    s.id = "forgeos-nav-style";
    s.textContent =
      ".nav .nav-soon{position:relative;display:flex;align-items:center;gap:12px;" +
        "min-height:46px;padding:10px 14px;border-radius:16px;font-size:14px;" +
        "font-weight:700;color:var(--muted,#68758b);opacity:.62;cursor:default;" +
        "user-select:none;}" +
      ".nav .nav-soon svg{width:22px;height:22px;stroke:currentColor;fill:none;" +
        "stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;}" +
      ".nav .nav-soon .nav-soon-label{flex:1;}" +
      ".nav .nav-soon .soon-pill{font-size:9.5px;font-weight:800;letter-spacing:.08em;" +
        "text-transform:uppercase;padding:3px 7px;border-radius:999px;" +
        "background:var(--primary-soft,rgba(41,98,255,.12));color:var(--primary,#2962ff);" +
        "opacity:.9;}" +
      // Sidebar as a flex column so the footer can never overlap the nav,
      // whatever the nav's height or the viewport's: brand pinned on top,
      // the nav scrolls in the middle, footer pinned at the bottom. Replaces
      // the old `position:absolute; bottom:22px` footer that collided once the
      // shared nav grew past the dashboard's short menu.
      ".sidebar{display:flex;flex-direction:column;height:100vh;overflow:hidden;}" +
      ".sidebar .brand{flex:0 0 auto;}" +
      ".sidebar .nav-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;}" +
      ".sidebar .sidebar-footer{position:static;left:auto;right:auto;bottom:auto;" +
        "flex:0 0 auto;margin-top:14px;}";
    document.head.appendChild(s);
  }

  function mount() {
    injectStyles();
    var sidebar = buildSidebar();

    var existing = document.querySelector("aside.sidebar, .sidebar");
    if (existing) {
      // dashboard already ships an inline sidebar — replace with the shared one
      existing.replaceWith(sidebar);
      return;
    }

    var app = document.querySelector(".app");
    if (app) {
      // feature pages: prepend the sidebar and undo main's full-width override
      app.insertBefore(sidebar, app.firstChild);
      var main = app.querySelector(".main") || app.querySelector("main");
      if (main) main.style.gridColumn = "";
      return;
    }

    // pages with no .app shell (older layout): wrap <main> in an .app grid
    var loneMain = document.querySelector("main.main") || document.querySelector("main");
    var wrap = document.createElement("div");
    wrap.className = "app";
    if (loneMain && loneMain.parentNode) {
      loneMain.parentNode.insertBefore(wrap, loneMain);
      wrap.appendChild(sidebar);
      wrap.appendChild(loneMain);
    } else {
      document.body.insertBefore(wrap, document.body.firstChild);
      wrap.appendChild(sidebar);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
