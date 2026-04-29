// ForgeOS Window Manager - DSM-7 Style
// Professional window management with proper stacking, focus, and state

(function() {
  'use strict';

  // Window stack for Z-index management
  var windowStack = [];
  var windowCounter = 0;

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function init() {
    setupSidebar();
    setupTaskbar();
    setupWindowControls();
    updateClock();
    setInterval(updateClock, 1000);
  }

  // Clock Update
  function updateClock() {
    var now = new Date();
    var time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    var date = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    var timeEl = document.getElementById('clk-time');
    var dateEl = document.getElementById('clk-date');
    if (timeEl) timeEl.textContent = time;
    if (dateEl) dateEl.textContent = date;
  }

  // Sidebar Navigation
  function setupSidebar() {
    document.querySelectorAll('.sidebar-item').forEach(function(item) {
      item.addEventListener('click', function() {
        var app = this.dataset.app;
        if (!app) return;

        // Update active state
        document.querySelectorAll('.sidebar-item').forEach(function(i) { i.classList.remove('active'); });
        this.classList.add('active');

        // Toggle window
        toggleWindow(app);
      });
    });
  }

  // Taskbar Management
  function setupTaskbar() {
    document.querySelectorAll('.taskbar-item').forEach(function(item) {
      item.addEventListener('click', function() {
        var app = this.dataset.app;
        if (!app) return;

        // Update active state
        document.querySelectorAll('.taskbar-item').forEach(function(i) { i.classList.remove('active'); });
        this.classList.add('active');

        // Focus window
        focusWindow(app);
      });
    });

    // Start button - toggle sidebar
    var startBtn = document.querySelector('.taskbar-start');
    if (startBtn) {
      startBtn.addEventListener('click', toggleSidebar);
    }
  }

  // Window Controls (minimize, maximize, close)
  function setupWindowControls() {
    // Use event delegation for dynamic windows
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('.window-btn');
      if (!btn) return;

      var win = btn.closest('.window');
      if (!win) return;

      if (btn.classList.contains('close')) {
        closeWindow(win);
      } else if (btn.classList.contains('minimize')) {
        minimizeWindow(win);
      } else if (btn.classList.contains('maximize')) {
        toggleMaximizeWindow(win);
      }
    });

    // Setup dragging for existing windows
    document.querySelectorAll('.window').forEach(function(win) {
      setupDragForWindow(win);
    });
  }

  // Toggle Window (open if closed, focus if open)
  function toggleWindow(appName) {
    var win = getWindowByApp(appName);

    if (win) {
      if (win.style.display === 'none') {
        win.style.display = '';
        focusWindow(appName);
      } else {
        focusWindow(appName);
      }
    } else {
      createWindow(appName);
    }
  }

  // Create New Window
  function createWindow(appName) {
    var windowArea = document.getElementById('window-area');
    if (!windowArea) return;

    var win = document.createElement('div');
    win.className = 'window';
    win.dataset.window = appName;
    win.style.left = (40 + windowCounter * 30) + 'px';
    win.style.top = (20 + windowCounter * 30) + 'px';
    win.style.width = '900px';
    win.style.height = '600px';
    win.style.zIndex = 100 + windowStack.length;

    // Window content based on app
    var content = getWindowContent(appName);
    win.innerHTML = '<div class="window-titlebar">' +
      '<div class="window-title">' +
        getWindowIcon(appName) +
        ' ' + getWindowTitle(appName) +
      '</div>' +
      '<div class="window-controls">' +
        '<button class="window-btn minimize" title="Minimize"><svg viewBox="0 0 24 24"><line x1="4" y1="12" x2="20" y2="12"/></svg></button>' +
        '<button class="window-btn maximize" title="Maximize"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/></svg></button>' +
        '<button class="window-btn close" title="Close"><svg viewBox="0 0 24 24"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg></button>' +
      '</div>' +
    '</div>' +
    '<div class="window-content">' +
      content +
    '</div>';

    windowArea.appendChild(win);
    windowStack.push(appName);
    windowCounter++;
    focusWindow(appName);

    // Setup dragging for new window
    setupDragForWindow(win);
  }

  // Get Window Content
  function getWindowContent(appName) {
    var contents = {
      dashboard: '<div class="widget-grid">' +
        '<div class="glass-card"><div class="card-header"><span class="card-title">CPU Usage</span><div class="card-icon"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3M12 1v3M15 1v3M9 20v3M12 20v3M15 20v3M20 9h3M20 12h3M20 15h3M1 9h3M1 12h3M1 15h3"/></svg></div></div><div class="card-value">23%</div><div class="card-label">Intel i7-12700K</div><div class="card-trend up"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Normal load</div></div>' +
        '<div class="glass-card"><div class="card-header"><span class="card-title">Memory</span><div class="card-icon"><svg viewBox="0 0 24 24"><path d="M6 19v-8a6 6 0 0 1 12 0v8"/><rect x="4" y="19" width="16" height="3" rx="1"/><circle cx="12" cy="12" r="2"/></svg></div></div><div class="card-value">12.4 GB</div><div class="card-label">/ 32 GB (38% used)</div><div class="card-trend up"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Available: 19.6 GB</div></div>' +
        '<div class="glass-card"><div class="card-header"><span class="card-title">Storage</span><div class="card-icon"><svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div></div><div class="card-value">2.8 TB</div><div class="card-label">/ 8 TB (35% used)</div><div class="card-trend up"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> 5.2 TB available</div></div>' +
        '<div class="glass-card"><div class="card-header"><span class="card-title">Network</span><div class="card-icon"><svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div></div><div class="card-value">1.2 Gbps</div><div class="card-label">2.5G Ethernet (active)</div><div class="card-trend up"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Up: 340 Mbps / Down: 860 Mbps</div></div>' +
      '</div>',
      storage: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Storage Manager</h3><div class="glass-card" style="padding:20px;"><div style="display:flex;flex-direction:column;gap:12px;"><div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:var(--text-primary);">Pool: Main Storage</span><span class="sidebar-badge">ONLINE</span></div><div style="height:8px;background:rgba(255,255,255,0.1);border-radius:4px;overflow:hidden;"><div style="width:35%;height:100%;background:var(--accent-primary);border-radius:4px;"></div></div><div style="display:flex;justify-content:space-between;color:var(--text-secondary);font-size:12px;"><span>2.8 TB used</span><span>5.2 TB free</span></div></div></div></div>',
      network: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Network Configuration</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Network interfaces and configuration coming soon...</p></div></div>',
      filestation: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">File Station (RustFS)</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;">Console</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;">Upload</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">RustFS S3 API: <span style="color:var(--accent-success);">Connected</span> | Port 9000 | Bucket: forgeos-main</div><div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(120px, 1fr)); gap:12px;"><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div style="font-size:32px; margin-bottom:6px;">📁</div><div style="font-size:11px; color:var(--text-secondary);">report.pdf</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div style="font-size:32px; margin-bottom:6px;">📂</div><div style="font-size:11px; color:var(--text-secondary);">photos/</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div style="font-size:32px; margin-bottom:6px;">📊</div><div style="font-size:11px; color:var(--text-secondary);">data.csv</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div style="font-size:32px; margin-bottom:6px;">🗜️</div><div style="font-size:11px; color:var(--text-secondary);">backup.zip</div></div></div></div>',
      filedb: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">ForgeFileDB</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Database management interface coming soon...</p></div></div>',
       docker: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">Docker & Compose</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;" onclick="ForgeOS.dockerRefresh()">↻ Refresh</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;" onclick="ForgeOS.composeUp()">Compose Up</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-danger); background:transparent; color:var(--accent-danger); cursor:pointer;" onclick="ForgeOS.dockerPrune()">Prune</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">Docker API: <span style="color:var(--accent-success);">● Active</span> | Containers: <span id="docker-count">12</span> | Images: <span id="docker-images">45</span> | <a href="#" style="color:var(--accent-primary);" onclick="ForgeOS.showPrune(); return false;">Clean up</a></div><div id="docker-containers" style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">nginx-proxy-manager</span><span style="font-size:11px; color:var(--text-secondary);">v2.11.1</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'nginx-proxy-manager\', \'stop\')">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'nginx-proxy-manager\', \'restart\')">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'nginx-proxy-manager\', \'update\')">Update</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.viewLogs(\'nginx-proxy-manager\')">Logs</button></div></div><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">rustfs</span><span style="font-size:11px; color:var(--text-secondary);">latest</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'rustfs\', \'stop\')">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'rustfs\', \'restart\')">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.containerAction(\'rustfs\', \'update\')">Update</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.viewLogs(\'rustfs\')">Logs</button></div></div></div><div style="margin-top:16px; padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="font-size:12px; color:var(--text-secondary); margin-bottom:8px;">Docker Compose Projects</div><div style="display:flex; justify-content:space-between; align-items:center;"><span style="color:var(--text-primary); font-weight:500;">forgeos-stack</span><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:var(--accent-success); color:#000; cursor:pointer;" onclick="ForgeOS.composeAction(\'forgeos-stack\', \'up\')">Up</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.composeAction(\'forgeos-stack\', \'down\')">Down</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.composeAction(\'forgeos-stack\', \'restart\')">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.composeAction(\'forgeos-stack\', \'pull\')">Pull</button></div></div></div></div>',
      settings: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Settings</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">System settings coming soon...</p></div></div>',
      firewall: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Firewall</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Firewall rules management coming soon...</p></div></div>',
      fail2ban: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Fail2ban</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Intrusion detection logs coming soon...</p></div></div>',
       lxc: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">LXC Containers</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;" onclick="ForgeOS.lxcRefresh()">↻ Refresh</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;" onclick="ForgeOS.lxcCreate()">Create Container</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">LXD/LXC: <span style="color:var(--accent-success);">● Active</span> | Containers: <span id="lxc-count">4</span> | Running: <span id="lxc-running">2</span></div><div id="lxc-containers" style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">ubuntu-web</span><span style="font-size:11px; color:var(--text-secondary);">Ubuntu 22.04</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.lxcAction(\'ubuntu-web\', \'stop\')">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.lxcAction(\'ubuntu-web\', \'restart\')">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.lxcExec(\'ubuntu-web\')">Console</button></div></div><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-warning);">○</span><span style="color:var(--text-primary); font-weight:500;">debian-db</span><span style="font-size:11px; color:var(--text-secondary);">Debian 12</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:var(--accent-success); color:#000; cursor:pointer;" onclick="ForgeOS.lxcAction(\'debian-db\', \'start\')">Start</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.lxcAction(\'debian-db\', \'restart\')">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" onclick="ForgeOS.lxcExec(\'debian-db\')">Console</button></div></div></div></div>'
    };

    return contents[appName] || '<div style="padding:20px;color:var(--text-muted);">Window content for ' + appName + ' coming soon...</div>';
  }

  // Get Window Icon
  function getWindowIcon(appName) {
    var icons = {
      dashboard: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
      storage: '<svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
      network: '<svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
      filestation: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 12h16"/><path d="M12 4v16"/></svg>',
      filedb: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
      docker: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="8" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="16" cy="12" r="1.5" fill="currentColor"/></svg>',
      settings: '<svg viewBox="0 0 24 24"><path d="M12 2L2 22h20z"/><circle cx="12" cy="14" r="2"/></svg>',
      firewall: '<svg viewBox="0 0 24 24"><path d="M12 2L2 22h20z"/><circle cx="12" cy="14" r="2"/></svg>',
      fail2ban: '<svg viewBox="0 0 24 24" style="color:var(--accent-danger);"><path d="M12 2L2 22h20z"/><line x1="8" y1="8" x2="16" y2="16"/><line x1="16" y1="8" x2="8" y2="16"/></svg>',
       lxc: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
    };
    return icons[appName] || '';
  }

  // Get Window Title
  function getWindowTitle(appName) {
    var titles = {
      dashboard: 'Dashboard',
      storage: 'Storage Manager',
      network: 'Network',
      filestation: 'File Station',
      filedb: 'ForgeFileDB',
      docker: 'Docker',
      settings: 'Settings',
      firewall: 'Firewall',
      fail2ban: 'Fail2ban',
       lxc: 'LXC'
    };
    return titles[appName] || appName;
  }

  // Focus Window
  function focusWindow(appName) {
    var win = getWindowByApp(appName);
    if (!win) return;

    // Remove focused class from all windows
    document.querySelectorAll('.window').forEach(function(w) { w.classList.remove('focused'); });

    // Add focused class
    win.classList.add('focused');

    // Bring to front
    var maxZ = 100;
    document.querySelectorAll('.window').forEach(function(w) {
      var z = parseInt(w.style.zIndex) || 0;
      if (z > maxZ) maxZ = z;
    });
    win.style.zIndex = maxZ + 1;
  }

  // Close Window
  function closeWindow(win) {
    if (win && win.parentNode) {
      var app = win.dataset.window;
      win.parentNode.removeChild(win);

      // Remove from stack
      var index = windowStack.indexOf(app);
      if (index > -1) {
        windowStack.splice(index, 1);
      }
    }
  }

  // Minimize Window
  function minimizeWindow(win) {
    if (win) {
      win.style.display = 'none';
    }
  }

  // Toggle Maximize Window
  function toggleMaximizeWindow(win) {
    if (!win) return;

    if (win.style.width === '100%') {
      // Restore
      win.style.width = '900px';
      win.style.height = '600px';
      win.style.left = '40px';
      win.style.top = '20px';
    } else {
      // Maximize
      win.style.width = '100%';
      win.style.height = '100%';
      win.style.left = '0';
      win.style.top = '0';
    }
  }

  // Get Window by App Name
  function getWindowByApp(appName) {
    return document.querySelector('.window[data-window="' + appName + '"]');
  }

  // Toggle Sidebar (Mobile)
  function toggleSidebar() {
    var sidebar = document.getElementById('sidebar');
    if (sidebar) {
      sidebar.classList.toggle('open');
    }
  }

  // Window Dragging
  function setupDragForWindow(win) {
    var titlebar = win.querySelector('.window-titlebar');
    if (!titlebar) return;

    var isDragging = false;
    var currentX;
    var currentY;
    var initialX;
    var initialY;

    titlebar.addEventListener('mousedown', function(e) {
      if (e.target.closest('.window-btn')) return;

      isDragging = true;
      initialX = e.clientX - win.offsetLeft;
      initialY = e.clientY - win.offsetTop;

      // Bring to front
      document.querySelectorAll('.window').forEach(function(w) { w.classList.remove('focused'); });
      win.classList.add('focused');
      var maxZ = 100;
      document.querySelectorAll('.window').forEach(function(w) {
        var z = parseInt(w.style.zIndex) || 0;
        if (z > maxZ) maxZ = z;
      });
      win.style.zIndex = maxZ + 1;
    });

    document.addEventListener('mousemove', function(e) {
      if (!isDragging) return;
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      win.style.left = currentX + 'px';
      win.style.top = currentY + 'px';
    });

    document.addEventListener('mouseup', function() {
      isDragging = false;
    });
  }

  // Public API
  window.ForgeOS = {
    toggleSidebar: toggleSidebar,
    focusWindow: focusWindow,
    closeWindow: closeWindow,
    createWindow: createWindow,
    getRustFSConsole: getRustFSConsole
  };

  // RustFS Console Content
  function getRustFSConsole() {
    return '<div style="display:flex; flex-direction:column; height:100%;">' +
      '<div style="padding:12px 16px; background:var(--glass-bg); border-bottom:1px solid var(--glass-border); display:flex; justify-content:space-between; align-items:center;">' +
        '<span style="color:var(--text-primary); font-size:13px; font-weight:600;">RustFS Console (Embedded)</span>' +
        '<span style="color:var(--text-muted); font-size:11px;">Port 9001 → integrated into ForgeOS</span>' +
      '</div>' +
      '<div style="flex:1; display:flex; align-items:center; justify-content:center; background:var(--bg-void);">' +
        '<div style="text-align:center; color:var(--text-muted);">' +
          '<div style="font-size:48px; margin-bottom:16px;">🚀</div>' +
          '<div style="font-size:14px; margin-bottom:8px; color:var(--text-primary);">RustFS Management Console</div>' +
          '<div style="font-size:12px; margin-bottom:16px;">The full RustFS web console is embedded below in production</div>' +
          '<div style="display:flex; gap:8px; justify-content:center;">' +
            '<button style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;">Open Console</button>' +
            '<button style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;">S3 API Docs</button>' +
          '</div>' +
          '<div style="margin-top:20px; font-size:11px; color:var(--text-muted);">S3 API: localhost:9000 | Admin API: localhost:9000/admin/ | License: Apache 2.0</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // ForgeOS Docker/LXC Management Functions
  window.ForgeOS = {
    // Docker Containers
    dockerRefresh: function() {
      fetch('/api/docker/containers')
        .then(r => r.json())
        .then(data => {
          console.log('Docker containers:', data);
          // Update UI with real data
        })
        .catch(e => console.error('Failed to refresh Docker:', e));
    },

    containerAction: function(container, action) {
      if (!confirm('Are you sure you want to ' + action + ' ' + container + '?')) return;
      fetch('/api/docker/containers/' + container + '/' + action, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert('Container ' + action + ' successful');
          ForgeOS.dockerRefresh();
        })
        .catch(e => alert('Error: ' + e));
    },

    viewLogs: function(container) {
      fetch('/api/docker/containers/' + container + '/logs')
        .then(r => r.text())
        .then(logs => {
          var win = window.open('', 'Logs: ' + container, 'width=800,height=600');
          win.document.write('<pre>' + logs + '</pre>');
        });
    },

    // Docker Compose
    composeUp: function() {
      fetch('/api/docker/compose/forgeos-stack/up', { method: 'POST' })
        .then(r => r.json())
        .then(data => alert('Compose up successful'))
        .catch(e => alert('Error: ' + e));
    },

    composeAction: function(project, action) {
      if (!confirm('Are you sure you want to ' + action + ' project ' + project + '?')) return;
      fetch('/api/docker/compose/' + project + '/' + action, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert('Compose ' + action + ' successful');
          ForgeOS.dockerRefresh();
        })
        .catch(e => alert('Error: ' + e));
    },

    dockerPrune: function() {
      if (!confirm('This will remove all stopped containers, unused networks, and dangling images. Continue?')) return;
      fetch('/api/docker/prune', { method: 'POST' })
        .then(r => r.json())
        .then(data => alert('Prune complete. Removed: ' + JSON.stringify(data)))
        .catch(e => alert('Error: ' + e));
    },

    showPrune: function() {
      ForgeOS.dockerPrune();
      return false;
    },

    // LXC Containers
    lxcRefresh: function() {
      fetch('/api/lxc/containers')
        .then(r => r.json())
        .then(data => {
          console.log('LXC containers:', data);
          // Update UI with real data
        })
        .catch(e => console.error('Failed to refresh LXC:', e));
    },

    lxcAction: function(container, action) {
      if (!confirm('Are you sure you want to ' + action + ' LXC container ' + container + '?')) return;
      fetch('/api/lxc/containers/' + container + '/' + action, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert('LXC container ' + action + ' successful');
          ForgeOS.lxcRefresh();
        })
        .catch(e => alert('Error: ' + e));
    },

    lxcCreate: function() {
      var name = prompt('Container name:');
      var image = prompt('Image (e.g., ubuntu:22.04):', 'ubuntu:22.04');
      if (!name || !image) return;
      fetch('/api/lxc/containers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, image: image })
      })
        .then(r => r.json())
        .then(data => {
          alert('Container created');
          ForgeOS.lxcRefresh();
        })
        .catch(e => alert('Error: ' + e));
    },

    lxcExec: function(container) {
      alert('Opening console for ' + container + ' (WebSocket terminal coming soon)');
      // TODO: Implement WebSocket terminal connection
    }
  };

})();
