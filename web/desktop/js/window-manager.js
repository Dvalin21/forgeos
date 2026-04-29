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
      filestation: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">File Station</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">File browser interface coming soon...</p></div></div>',
      filedb: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">ForgeFileDB</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Database management interface coming soon...</p></div></div>',
      docker: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Docker Containers</h3><div class="glass-card" style="padding:20px;"><div style="display:flex;flex-direction:column;gap:8px;"><div style="display:flex;justify-content:space-between;align-items:center;padding:8px;border-radius:6px;background:var(--glass-bg);"><span style="color:var(--text-primary);">nginx-proxy-manager</span><span class="sidebar-badge success">RUNNING</span></div><div style="display:flex;justify-content:space-between;align-items:center;padding:8px;border-radius:6px;background:var(--glass-bg);"><span style="color:var(--text-primary);">portainer</span><span class="sidebar-badge success">RUNNING</span></div></div></div></div>',
      settings: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Settings</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">System settings coming soon...</p></div></div>',
      firewall: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Firewall</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Firewall rules management coming soon...</p></div></div>',
      fail2ban: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Fail2ban</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Intrusion detection logs coming soon...</p></div></div>',
      incus: '<div style="padding:20px;"><h3 style="margin-bottom:16px;color:var(--text-primary);">Incus Containers</h3><div class="glass-card" style="padding:20px;"><p style="color:var(--text-secondary);">Container management coming soon...</p></div></div>'
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
      incus: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
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
      incus: 'Incus'
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
    createWindow: createWindow
  };

})();
