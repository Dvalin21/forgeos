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
  // ─── Auth-Aware Fetch (reads token from localStorage) ───
  function forgeosFetch(path, options) {
    var token = localStorage.getItem('forgeos_token');
    var headers = (options && options.headers) || {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(path, { ...(options || {}), headers: headers });
  }

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

    // Auto-refresh live data windows
    if (appName === 'docker') setTimeout(function() { window.ForgeOS.dockerRefresh(); }, 200);
    if (appName === 'lxc') setTimeout(function() { window.ForgeOS.lxcRefresh(); }, 200);

    // Setup dragging for new window
    setupDragForWindow(win);
  }

  // Get Window Content
  function getWindowContent(appName) {
    var contents = {
      dashboard: '<div class="widget-grid">' +
        '<div class="glass-card">' +
          '<div class="card-header"><span class="card-title">CPU Usage</span><div class="card-icon">' + (typeof Icons !== 'undefined' && Icons.cpu ? Icons.cpu() : '') + '</div></div>' +
          '<div class="card-value" data-stat="cpu">--%</div>' +
          '<div class="card-label" data-stat-label="cpu">i7-12700K</div>' +
          '<div class="card-trend up" data-stat-trend="cpu"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> <span data-stat-trend="cpu">Loading...</span></div>' +
        '</div>' +
        '<div class="glass-card">' +
          '<div class="card-header"><span class="card-title">Memory</span><div class="card-icon">' + (typeof Icons !== 'undefined' && Icons.memory ? Icons.memory() : '') + '</div></div>' +
          '<div class="card-value" data-stat="memory">-- GB</div>' +
          '<div class="card-label" data-stat-label="memory">/ -- GB (--% used)</div>' +
          '<div class="card-trend up" data-stat-trend="memory"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> <span data-stat-trend="memory">Loading...</span></div>' +
        '</div>' +
        '<div class="glass-card">' +
          '<div class="card-header"><span class="card-title">Storage</span><div class="card-icon">' + (typeof Icons !== 'undefined' && Icons.storage ? Icons.storage() : '') + '</div></div>' +
          '<div class="card-value" data-stat="storage">-- TB</div>' +
          '<div class="card-label" data-stat-label="storage">/ -- TB</div>' +
          '<div class="card-trend up" data-stat-trend="storage"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> <span data-stat-trend="storage">Loading...</span></div>' +
        '</div>' +
        '<div class="glass-card">' +
          '<div class="card-header"><span class="card-title">Network</span><div class="card-icon">' + (typeof Icons !== 'undefined' && Icons.network ? Icons.network() : '') + '</div></div>' +
          '<div class="card-value" data-stat="network">--</div>' +
          '<div class="card-label" data-stat-label="network">Total transferred</div>' +
          '<div class="card-trend up" data-stat-trend="network"><svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> <span data-stat-trend="network">Loading...</span></div>' +
        '</div>' +
      '</div>',
      storage: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Storage Manager</h3><div class="glass-card" style="padding:20px;"><div style="display:flex;flex-direction:column;gap:12px;"><div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:var(--text-primary);">Pool: Main Storage</span><span class="sidebar-badge">ONLINE</span></div><div style="height:8px;background:rgba(255,255,255,0.1);border-radius:4px;overflow:hidden;"><div style="width:35%;height:100%;background:var(--accent-primary);border-radius:4px;"></div></div><div style="display:flex;justify-content:space-between;color:var(--text-secondary);font-size:12px;"><span>2.8 TB used</span><span>5.2 TB free</span></div></div></div></div>',
      network: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Network Configuration</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Network interfaces and configuration coming soon...</p></div></div>',
      filestation: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">File Station (RustFS)</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;">Console</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;">Upload</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">RustFS S3 API: <span style="color:var(--accent-success);">Connected</span> | Port 9000 | Bucket: forgeos-main</div><div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(120px, 1fr)); gap:12px;"><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div class="file-icon-sm"><svg viewBox="0 0 32 32" style="width:32px;height:32px;stroke:var(--text-secondary);stroke-width:1.5;fill:none;"><path d="M21 4H7a2 2 0 0 0-2 2v20a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V10z"/><polyline points="21 4 21 10 27 10"/></svg></div><div style="font-size:11px; color:var(--text-secondary);">report.pdf</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div class="file-icon-sm"><svg viewBox="0 0 32 32" style="width:32px;height:32px;stroke:var(--text-secondary);stroke-width:1.5;fill:none;"><path d="M28 24a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6l3 4h11a2 2 0 0 1 2 2z"/></svg></div><div style="font-size:11px; color:var(--text-secondary);">photos/</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div class="file-icon-sm"><svg viewBox="0 0 32 32" style="width:32px;height:32px;stroke:var(--text-secondary);stroke-width:1.5;fill:none;"><line x1="24" y1="26" x2="24" y2="14"/><line x1="16" y1="26" x2="16" y2="6"/><line x1="8" y1="26" x2="8" y2="18"/></svg></div><div style="font-size:11px; color:var(--text-secondary);">data.csv</div></div><div style="padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px; text-align:center; cursor:pointer;"><div class="file-icon-sm"><svg viewBox="0 0 32 32" style="width:32px;height:32px;stroke:var(--text-secondary);stroke-width:1.5;fill:none;"><rect x="4" y="4" width="24" height="24" rx="3"/><line x1="4" y1="12" x2="28" y2="12"/><path d="M12 18h8"/></svg></div><div style="font-size:11px; color:var(--text-secondary);">backup.zip</div></div></div></div>',
      filedb: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">ForgeFileDB</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Database management interface coming soon...</p></div></div>',
       docker: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">Docker & Compose</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;" data-action="docker-refresh">↻ Refresh</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;" data-action="compose-up">Compose Up</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-danger); background:transparent; color:var(--accent-danger); cursor:pointer;" data-action="docker-prune">Prune</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">Docker API: <span style="color:var(--accent-success);">● Active</span> | Containers: <span id="docker-count">12</span> | Images: <span id="docker-images">45</span> | <a href="#" style="color:var(--accent-primary);" data-action="show-prune">Clean up</a></div><div id="docker-containers" style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">nginx-proxy-manager</span><span style="font-size:11px; color:var(--text-secondary);">v2.11.1</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="nginx-proxy-manager" data-name="stop">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="nginx-proxy-manager" data-name="restart">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="nginx-proxy-manager" data-name="update">Update</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="view-logs" data-container="nginx-proxy-manager">Logs</button></div></div><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">rustfs</span><span style="font-size:11px; color:var(--text-secondary);">latest</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="rustfs" data-name="stop">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="rustfs" data-name="restart">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="rustfs" data-name="update">Update</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="view-logs" data-container="rustfs">Logs</button></div></div></div><div style="margin-top:16px; padding:12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="font-size:12px; color:var(--text-secondary); margin-bottom:8px;">Docker Compose Projects</div><div style="display:flex; justify-content:space-between; align-items:center;"><span style="color:var(--text-primary); font-weight:500;">forgeos-stack</span><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:var(--accent-success); color:#000; cursor:pointer;" data-action="compose-action" data-project="forgeos-stack" data-name="up">Up</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="compose-action" data-project="forgeos-stack" data-name="down">Down</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="compose-action" data-project="forgeos-stack" data-name="restart">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="compose-action" data-project="forgeos-stack" data-name="pull">Pull</button></div></div></div></div>',
      settings: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Settings</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">System settings coming soon...</p></div></div>',
      firewall: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Firewall</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Firewall rules management coming soon...</p></div></div>',
      fail2ban: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Fail2ban</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Intrusion detection logs coming soon...</p></div></div>',
       lxc: '<div style="padding:20px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;"><h3 style="color:var(--text-primary);">LXC Containers</h3><div style="display:flex; gap:8px;"><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-primary); cursor:pointer;" data-action="lxc-refresh">↻ Refresh</button><button class="btn" style="padding:6px 12px; border-radius:6px; border:1px solid var(--accent-primary); background:var(--accent-primary); color:#000; cursor:pointer; font-weight:600;" data-action="lxc-create">Create Container</button></div></div><div style="margin-bottom:12px; padding:8px 12px; background:var(--glass-bg); border-radius:8px; font-size:12px; color:var(--text-secondary);">LXD/LXC: <span style="color:var(--accent-success);">● Active</span> | Containers: <span id="lxc-count">4</span> | Running: <span id="lxc-running">2</span></div><div id="lxc-containers" style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-success);">●</span><span style="color:var(--text-primary); font-weight:500;">ubuntu-web</span><span style="font-size:11px; color:var(--text-secondary);">Ubuntu 22.04</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="ubuntu-web" data-name="stop">Stop</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="ubuntu-web" data-name="restart">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:transparent; color:var(--accent-success); cursor:pointer;" data-action="open-terminal" data-type="lxc" data-container="ubuntu-web">Terminal</button></div></div><div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;"><div style="display:flex; align-items:center; gap:8px;"><span style="color:var(--accent-warning);">○</span><span style="color:var(--text-primary); font-weight:500;">debian-db</span><span style="font-size:11px; color:var(--text-secondary);">Debian 12</span></div><div style="display:flex; gap:4px;"><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:var(--accent-success); color:#000; cursor:pointer;" data-action="lxc-action" data-container="debian-db" data-name="start">Start</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="debian-db" data-name="restart">Restart</button><button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--accent-success); background:transparent; color:var(--accent-success); cursor:pointer;" data-action="open-terminal" data-type="lxc" data-container="debian-db">Terminal</button></div></div></div></div>'
    };

    return contents[appName] || '<div style="padding:20px;color:var(--text-muted);">Window content for ' + appName + ' coming soon...</div>';
  }

  // Get Window Icon — uses canonical Icons system with fallback
  function getWindowIcon(appName) {
    if (typeof Icons !== 'undefined' && typeof Icons[appName] === 'function') {
      return Icons[appName]();
    }
    return '';
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

    // Notify forgeOS
    if (window.forgeOS && window.forgeOS.dispatch) {
      window.forgeOS.dispatch('window-focused', appName);
    }
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

  // ─── Unified ForgeOS Public API ───

  function getRustFSConsole() {
    return '<div style="display:flex; flex-direction:column; height:100%;">' +
      '<div style="padding:12px 16px; background:var(--glass-bg); border-bottom:1px solid var(--glass-border); display:flex; justify-content:space-between; align-items:center;">' +
        '<span style="color:var(--text-primary); font-size:13px; font-weight:600;">RustFS Console (Embedded)</span>' +
        '<span style="color:var(--text-muted); font-size:11px;">Port 9001 → integrated into ForgeOS</span>' +
      '</div>' +
      '<div style="flex:1; display:flex; align-items:center; justify-content:center; background:var(--bg-void);">' +
        '<div style="text-align:center; color:var(--text-muted);">' +
          '<svg viewBox="0 0 48 48" style="width:48px;height:48px;stroke:var(--accent-primary);stroke-width:1.5;fill:none;margin-bottom:16px;"><path d="M12 36l-4 4M8 28l-4 4M20 40l-4 4"/><path d="M36 14c-4-4-12-8-20-4S6 24 8 28s10 2 14 6 4 12 8 14 14-4 18-12-8-16-12-20z"/></svg>' +
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

  // ─── Event delegation for window content (replaces onclick in templates) ───
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    var W = window.ForgeOS;
    if (!W) return;

    if (action === 'docker-refresh')     { W.dockerRefresh(); }
    else if (action === 'compose-up')    { W.composeUp(); }
    else if (action === 'docker-prune')  { W.dockerPrune(); }
    else if (action === 'show-prune')    { e.preventDefault(); W.dockerPrune(); }
    else if (action === 'container-action') {
      var c = btn.dataset.container, n = btn.dataset.name;
      if (c && n) W.containerAction(c, n);
    }
    else if (action === 'view-logs') {
      var c = btn.dataset.container;
      if (c) W.viewLogs(c);
    }
    else if (action === 'compose-action') {
      var p = btn.dataset.project, n = btn.dataset.name;
      if (p && n) W.composeAction(p, n);
    }
    else if (action === 'lxc-refresh')   { W.lxcRefresh(); }
    else if (action === 'lxc-create')    { W.lxcCreate(); }
    else if (action === 'lxc-action') {
      var c = btn.dataset.container, n = btn.dataset.name;
      if (c && n) W.lxcAction(c, n);
    }
    else if (action === 'open-terminal') {
      var t = btn.dataset.type, c = btn.dataset.container;
      if (t && c) W.openTerminal(t, c);
    }
  });

  window.ForgeOS = {
    // Window management
    toggleSidebar: toggleSidebar,
    focusWindow: focusWindow,
    closeWindow: closeWindow,
    createWindow: createWindow,
    getRustFSConsole: getRustFSConsole,

    // Docker Containers — live data from API
    dockerRefresh: function() {
      var countEl = document.getElementById('docker-count');
      var imagesEl = document.getElementById('docker-images');
      var listEl = document.getElementById('docker-containers');
      if (!listEl) return;

      // Show loading state
      listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Loading containers...</div>';

      Promise.all([
        forgeosFetch('/api/docker/containers').then(function(r) { return r.ok ? r.json() : { containers: [] }; }),
        forgeosFetch('/api/docker/images').then(function(r) { return r.ok ? r.json() : { images: [] }; })
      ]).then(function(results) {
        var containers = results[0].containers || [];
        var images = results[1].images || [];

        // Update counts
        if (countEl) countEl.textContent = containers.length;
        if (imagesEl) imagesEl.textContent = images.length;

        // Render container list
        if (containers.length === 0) {
          listEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:13px;">No containers found.</div>';
          return;
        }

        var html = '';
        containers.forEach(function(c) {
          var name = c.Names || c.name || 'unknown';
          var image = c.Image || c.image || '';
          var state = c.State || c.state || 'unknown';
          var running = state === 'running' || state === 'Running' || state === 'running (healthy)';
          var statusColor = running ? 'var(--accent-success)' : 'var(--text-muted)';
          var statusText = c.Status || c.status || state;

          html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;">' +
            '<div style="display:flex; align-items:center; gap:8px; min-width:0; flex:1;">' +
              '<span style="color:' + statusColor + '; font-size:10px;">●</span>' +
              '<span style="color:var(--text-primary); font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + name + '</span>' +
              (image ? '<span style="font-size:11px; color:var(--text-secondary); flex-shrink:0;">' + image + '</span>' : '') +
              (statusText ? '<span style="font-size:10px; color:var(--text-muted); flex-shrink:0;">' + statusText + '</span>' : '') +
            '</div>' +
            '<div style="display:flex; gap:4px; flex-shrink:0;">' +
              (running ?
                '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="stop">Stop</button>' +
                '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="restart">Restart</button>'
              :
                '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="container-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="start">Start</button>'
              ) +
              '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="view-logs" data-container="' + name.replace(/"/g, '&quot;') + '">Logs</button>' +
            '</div>' +
          '</div>';
        });

        listEl.innerHTML = html;
      }).catch(function(e) {
        console.error('Docker refresh error:', e);
        listEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--accent-danger);font-size:13px;">Failed to load containers.</div>';
      });
    },

    containerAction: function(container, action) {
      if (!confirm('Are you sure you want to ' + action + ' ' + container + '?')) return;
      forgeosFetch('/api/docker/containers/' + container + '/' + action, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() {
          alert('Container ' + action + ' successful');
          window.ForgeOS.dockerRefresh();
        })
        .catch(function(e) { alert('Error: ' + e); });
    },

    viewLogs: function(container) {
      // If we already have a log viewer open for this container, remove it
      var existing = document.getElementById('log-viewer-' + container);
      if (existing) { document.body.removeChild(existing); return; }

      var overlay = document.createElement('div');
      overlay.id = 'log-viewer-' + container;
      overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;';

      var panel = document.createElement('div');
      panel.style.cssText = 'background:#1a1a2e;border:1px solid #333;border-radius:8px;width:90%;height:80%;display:flex;flex-direction:column;';

      var header = document.createElement('div');
      header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #333;';

      var title = document.createElement('span');
      title.style.cssText = 'color:#e0e0e0;font-weight:600;';
      title.textContent = 'Logs: ' + container;

      var closeBtn = document.createElement('button');
      closeBtn.textContent = '×';
      closeBtn.style.cssText = 'background:none;border:none;color:#e0e0e0;font-size:24px;cursor:pointer;padding:0 4px;line-height:1;';
      closeBtn.onclick = function() { document.body.removeChild(overlay); };

      header.appendChild(title);
      header.appendChild(closeBtn);

      var pre = document.createElement('pre');
      pre.id = 'log-viewer-content';
      pre.style.cssText = 'flex:1;overflow:auto;margin:0;padding:16px;color:#c0c0c0;font-family:monospace;font-size:13px;line-height:1.4;white-space:pre-wrap;';
      pre.textContent = 'Loading logs...';

      panel.appendChild(header);
      panel.appendChild(pre);
      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      // Close on backdrop click
      overlay.onclick = function(e) {
        if (e.target === overlay) document.body.removeChild(overlay);
      };

      forgeosFetch('/api/docker/containers/' + encodeURIComponent(container) + '/logs')
        .then(function(r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(function(logs) {
          pre.textContent = logs || '(no log output)';
        })
        .catch(function(err) {
          pre.textContent = 'Failed to load logs: ' + err.message;
        });
    },

    // Docker Compose
    composeUp: function() {
      forgeosFetch('/api/docker/compose/up', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() { alert('Compose up successful'); })
        .catch(function(e) { alert('Error: ' + e); });
    },

    composeAction: function(project, action) {
      if (!confirm('Are you sure you want to ' + action + ' project ' + project + '?')) return;
      forgeosFetch('/api/docker/compose/' + action, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() {
          alert('Compose ' + action + ' successful');
          window.ForgeOS.dockerRefresh();
        })
        .catch(function(e) { alert('Error: ' + e); });
    },

    dockerPrune: function() {
      if (!confirm('This will remove all stopped containers, unused networks, and dangling images. Continue?')) return;
      forgeosFetch('/api/docker/prune', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) { alert('Prune complete. Removed: ' + JSON.stringify(data)); })
        .catch(function(e) { alert('Error: ' + e); });
    },

    showPrune: function() {
      window.ForgeOS.dockerPrune();
      return false;
    },

    // LXC Containers — live data from API
    lxcRefresh: function() {
      var countEl = document.getElementById('lxc-count');
      var runningEl = document.getElementById('lxc-running');
      var listEl = document.getElementById('lxc-containers');
      if (!listEl) return;

      // Show loading state
      listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Loading containers...</div>';

      forgeosFetch('/api/docker/lxc/containers')
        .then(function(r) { return r.ok ? r.json() : { containers: [] }; })
        .then(function(data) {
          var containers = data.containers || [];
          var running = 0;

          if (countEl) countEl.textContent = containers.length;

          // Render container list
          if (containers.length === 0) {
            if (runningEl) runningEl.textContent = '0';
            listEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:13px;">No containers found.</div>';
            return;
          }

          var html = '';
          containers.forEach(function(c) {
            var name = c.name || 'unknown';
            var state = c.status || c.state || 'unknown';
            var isRunning = state === 'Running' || state === 'running';
            if (isRunning) running++;
            var ipv4 = c.ipv4 || c.addresses || '';

            html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:8px;">' +
              '<div style="display:flex; align-items:center; gap:8px; min-width:0; flex:1;">' +
                '<span style="color:' + (isRunning ? 'var(--accent-success)' : 'var(--text-muted)') + '; font-size:10px;">●</span>' +
                '<span style="color:var(--text-primary); font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + name + '</span>' +
                '<span style="font-size:11px; color:var(--text-secondary); flex-shrink:0;">' + state + '</span>' +
                (ipv4 ? '<span style="font-size:10px; color:var(--text-muted); flex-shrink:0;">' + ipv4 + '</span>' : '') +
              '</div>' +
              '<div style="display:flex; gap:4px; flex-shrink:0;">' +
                (isRunning ?
                  '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="stop">Stop</button>' +
                  '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="restart">Restart</button>'
                :
                  '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="lxc-action" data-container="' + name.replace(/"/g, '&quot;') + '" data-name="start">Start</button>'
                ) +
                '<button class="btn" style="padding:4px 8px; font-size:11px; border-radius:4px; border:1px solid var(--glass-border); background:var(--glass-bg); color:var(--text-secondary); cursor:pointer;" data-action="open-terminal" data-type="lxc" data-container="' + name.replace(/"/g, '&quot;') + '">Terminal</button>' +
              '</div>' +
            '</div>';
          });

          if (runningEl) runningEl.textContent = running;
          listEl.innerHTML = html;
        })
        .catch(function(e) {
          console.error('LXC refresh error:', e);
          listEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--accent-danger);font-size:13px;">Failed to load containers.</div>';
        });
    },

    lxcAction: function(container, action) {
      if (!confirm('Are you sure you want to ' + action + ' LXC container ' + container + '?')) return;
      forgeosFetch('/api/docker/lxc/containers/' + container + '/' + action, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() {
          alert('LXC container ' + action + ' successful');
          window.ForgeOS.lxcRefresh();
        })
        .catch(function(e) { alert('Error: ' + e); });
    },

    lxcCreate: function() {
      var name = prompt('Container name:');
      var image = prompt('Image (e.g., ubuntu:22.04):', 'ubuntu:22.04');
      if (!name || !image) return;
      forgeosFetch('/api/docker/lxc/containers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, image: image })
      })
        .then(function(r) { return r.json(); })
        .then(function() {
          alert('Container created');
          window.ForgeOS.lxcRefresh();
        })
        .catch(function(e) { alert('Error: ' + e); });
    },

    lxcExec: function(container) {
      alert('Opening console for ' + container + ' (WebSocket terminal coming soon)');
    },

    // Terminal access for Docker/LXC containers
    openTerminal: function(type, container) {
      var token = localStorage.getItem('forgeos_token') || '';
      var wsUrl = 'ws://' + window.location.host + '/ws/' + type + '/exec/' + container;

      var w = window.open('', 'Terminal: ' + container, 'width=800,height=600,scrollbars=yes');
      w.document.write([
        '<!DOCTYPE html><html><head><title>Terminal: ', container, '</title>',
        '<style>',
          'body{margin:0;padding:0;background:#000;font-family:monospace}',
          '#terminal{width:100%;height:calc(100vh - 40px);background:#000;color:#0f0;padding:10px;box-sizing:border-box;overflow:auto;white-space:pre-wrap}',
          '#input-line{display:flex;align-items:center;padding:5px 10px}',
          '#prompt{color:#0f0;margin-right:5px}',
          '#cmd{background:transparent;border:none;color:#0f0;font-family:monospace;font-size:14px;flex:1;outline:none}',
        '</style></head><body>',
        '<div id="terminal"></div>',
        '<div id="input-line"><span id="prompt">', container, ' :~$ </span><input type="text" id="cmd" autofocus/></div>',
        '<script>',
          'var ws=new WebSocket("', wsUrl, '",["forgeos","', token, '"]);',
          'var term=document.getElementById("terminal");',
          'var cmdInput=document.getElementById("cmd");',
          'var history=[];var historyIdx=-1;',
          'ws.onopen=function(){term.innerHTML+="Connected to ', container, '...\\n";cmdInput.focus()};',
          'ws.onmessage=function(e){term.innerHTML+=e.data;term.scrollTop=term.scrollHeight};',
          'ws.onclose=function(){term.innerHTML+="\\n--- Connection closed ---\\n"};',
          'cmdInput.addEventListener("keydown",function(e){',
            'if(e.key==="Enter"){',
              'var cmd=cmdInput.value;',
              'term.innerHTML+="', container, ' :~$ "+cmd+"\\n";',
              'ws.send(cmd+"\\n");history.push(cmd);historyIdx=history.length;cmdInput.value="";',
              'term.scrollTop=term.scrollHeight',
            '}else if(e.key==="ArrowUp"){',
              'if(historyIdx>0){historyIdx--;cmdInput.value=history[historyIdx]}',
              'e.preventDefault()',
            '}else if(e.key==="ArrowDown"){',
              'if(historyIdx<history.length-1){historyIdx++;cmdInput.value=history[historyIdx]}',
              'else{historyIdx=history.length;cmdInput.value=""}',
              'e.preventDefault()',
            '}',
          '});',
        '<\/script></body></html>'
      ].join(''));
      w.document.close();
    }
  };

})();
