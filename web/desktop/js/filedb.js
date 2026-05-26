// ForgeFileDB page — CSP-compliant, data-action event delegation
(function() {
  'use strict';

  var API = '';
  var _status = {};
  var _snapshots = [];
  var _dbs = [];

  // ── Navigation ──
  document.querySelectorAll('.nav-item[data-page]').forEach(function(item) {
    item.addEventListener('click', function() {
      document.querySelectorAll('.nav-item').forEach(function(i) { i.classList.remove('active'); });
      document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
      item.classList.add('active');
      var pg = document.getElementById('page-' + item.dataset.page);
      if (pg) pg.classList.add('active');
      if (item.dataset.page === 'databases') loadDatabases();
      if (item.dataset.page === 'snapshots') loadSnapshots();
      if (item.dataset.page === 'restore') populateRestoreSelect();
      if (item.dataset.page === 'logs') loadLogs();
      if (item.dataset.page === 'settings') loadSettings();
    });
  });

  // ── Event delegation (replaces all inline onclick handlers) ──
  document.addEventListener('click', function(e) {
    var el = e.target.closest('[data-action]');
    if (!el) return;
    var action = el.dataset.action;

    if (action === 'toggle-group') {
      var target = el.nextElementSibling;
      if (target) target.style.display = target.style.display === 'none' ? '' : 'none';
    } else if (action === 'snap-dir') {
      var dir = el.dataset.dir;
      if (dir) snapDir(dir);
    } else if (action === 'prep-restore') {
      var ts = el.dataset.ts;
      var dir = el.dataset.dir;
      if (ts && dir) prepRestore(ts, dir);
    }
  });

  // ── Status update ──
  function updateStatus(data) {
    _status = data;
    var cc = data.connected_clients || 0;
    var od = data.open_databases || 0;
    var sd = data.snapshots_today || 0;
    var cf = data.total_conflicts || 0;

    document.getElementById('stat-clients').textContent = cc;
    document.getElementById('stat-dbs').textContent = od;
    document.getElementById('stat-snaps').textContent = sd;
    document.getElementById('stat-conflicts').textContent = cf;
    document.getElementById('nav-clients').textContent = cc;
    document.getElementById('nav-snaps').textContent = data.total_snapshots || 0;
    document.getElementById('big-clients').textContent = cc;
    document.getElementById('big-dbs').textContent = od;
    document.getElementById('big-snaps').textContent = sd;
    document.getElementById('big-conflicts').textContent = cf;
    renderClients(data.clients || []);
    renderLocksMin(data.lock_details || {});
  }

  function renderClients(clients) {
    var el = document.getElementById('clients-list');
    if (!clients.length) {
      el.innerHTML = '<div class="empty"><div class="empty-ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg></div>No clients connected</div>';
      return;
    }
    el.innerHTML = clients.map(function(c) {
      var files = c.files || [];
      var dur = Math.round((Date.now() / 1000 - c.connected_since) / 60);
      var hasWrite = files.some(function(f) { return f.mode === 'EXCLUSIVE'; });
      var modeClass = hasWrite ? 'rw' : (files.length ? 'ro' : 'idle');
      var modeLabel = hasWrite ? 'READ/WRITE' : (files.length ? 'READ-ONLY' : 'IDLE');
      return '<div class="ct-row">' +
        '<span class="ct-ip">' + c.ip + '</span>' +
        '<span class="ct-files">' + (files.map(function(f) { return f.name; }).join(', ') || '\u2014') + '</span>' +
        '<span class="ct-dur">' + dur + 'm</span>' +
        '<span class="ct-mode ' + modeClass + '">' + modeLabel + '</span>' +
      '</div>';
    }).join('');
  }

  function renderLocksMin(lockData) {
    var el = document.getElementById('locks-mini');
    var files = lockData.files || {};
    var entries = Object.entries(files);
    if (!entries.length) {
      el.innerHTML = '<div class="empty"><div class="empty-ico"><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div>No files locked</div>';
      return;
    }
    el.innerHTML = entries.map(function(pair) {
      var path = pair[0], info = pair[1];
      var holders = info.holders || [];
      var waiters = info.waiters || 0;
      return holders.map(function(h) {
        return '<div class="lock-item">' +
          '<div>' +
            '<div class="lock-file">' + path.split('/').pop() + '</div>' +
            '<div class="lock-dir">' + path.split('/').slice(0, -1).join('/') + '</div>' +
          '</div>' +
          '<span class="lock-client">' + h.client + '</span>' +
          '<span class="lock-type ' + (h.mode === 'EXCLUSIVE' ? 'ex' : 'sh') + '">' + h.mode + '</span>' +
          (waiters ? '<span class="lock-wait">' + waiters + ' waiting</span>' : '') +
        '</div>';
      }).join('');
    }).join('');
  }

  // ── Databases page ──
  async function loadDatabases() {
    var el = document.getElementById('db-groups');
    el.innerHTML = '<div class="empty"><div class="empty-ico"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div>Scanning...</div>';
    try {
      var r = await fetch(API + '/api/filedb/databases');
      var data = await r.json();
      _dbs = data.databases || [];
      if (!_dbs.length) {
        el.innerHTML = '<div class="empty"><div class="empty-ico"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg></div>No database files found on watched shares</div>';
        return;
      }
      el.innerHTML = _dbs.map(function(grp) {
        return '<div class="db-group">' +
          '<div class="db-group-head" data-action="toggle-group">' +
            '<svg viewBox="0 0 24 24" style="width: 16px; height: 16px; stroke: var(--text-secondary); stroke-width: 1.5; fill: none; flex-shrink: 0;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>' +
            '<span class="db-group-dir">' + grp.dir + '</span>' +
            '<span class="db-group-count">' + grp.files.length + ' file' + (grp.files.length === 1 ? '' : 's') + '</span>' +
            '<div class="btn sm" data-action="snap-dir" data-dir="' + grp.dir + '"><svg viewBox="0 0 24 24" style="width: 14px; height: 14px; stroke: currentColor; stroke-width: 2; fill: none; vertical-align: middle; margin-right: 2px;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg> Snapshot</div>' +
          '</div>' +
          '<div>' +
            grp.files.map(function(f) {
              return '<div class="db-file-row">' +
                '<span class="db-fn">' + f.name + '</span>' +
                '<span class="db-type-badge">' + f.db_type + '</span>' +
                '<span class="db-size">' + fmtSize(f.size) + '</span>' +
                '<span class="db-mtime">' + new Date(f.modified).toLocaleString() + '</span>' +
              '</div>';
            }).join('') +
          '</div>' +
        '</div>';
      }).join('');
    } catch (e) {
      el.innerHTML = '<div class="empty">Error: ' + e.message + '</div>';
    }
  }

  function fmtSize(b) {
    if (b > 1e9) return (b / 1e9).toFixed(1) + ' GB';
    if (b > 1e6) return (b / 1e6).toFixed(1) + ' MB';
    if (b > 1e3) return (b / 1e3).toFixed(1) + ' KB';
    return b + ' B';
  }

  async function snapDir(dir) {
    try {
      var r = await fetch(API + '/api/filedb/snapshots', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_dir: dir, reason: 'manual:ui' })
      });
      appendLog('SNAP', r.ok ? 'Snapshot: ' + dir : 'ERROR snapshotting ' + dir + ': HTTP ' + r.status);
    } catch (e) {
      appendLog('SNAP', 'ERROR snapshotting ' + dir + ': ' + e.message);
    }
  }

  document.getElementById('refresh-dbs') && document.getElementById('refresh-dbs').addEventListener('click', loadDatabases);
  document.getElementById('snap-all-btn') && document.getElementById('snap-all-btn').addEventListener('click', async function() {
    var ok = 0, fail = 0;
    for (var i = 0; i < _dbs.length; i++) {
      try { await snapDir(_dbs[i].dir); ok++; } catch (e) { fail++; }
    }
    appendLog('SNAP', 'Snap-all done: ' + ok + ' succeeded, ' + fail + ' failed');
  });

  // ── Snapshots page ──
  async function loadSnapshots() {
    var el = document.getElementById('snaps-list');
    try {
      var r = await fetch(API + '/api/filedb/snapshots');
      var data = await r.json();
      _snapshots = data.snapshots || [];
      document.getElementById('nav-snaps').textContent = _snapshots.length;
      if (!_snapshots.length) {
        el.innerHTML = '<div class="empty"><div class="empty-ico"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></div>No snapshots yet</div>';
        return;
      }
      el.innerHTML = _snapshots.map(function(s) {
        return '<div class="snap-row">' +
          '<span class="snap-ts">' + (s.ts || '\u2014') + '</span>' +
          '<span class="snap-dir" title="' + s.db_dir + '">' + ((s.db_dir || '').split('/').pop() || '\u2014') + '</span>' +
          '<span class="snap-method ' + s.method + '">' + (s.method || '?') + '</span>' +
          '<span class="snap-reason">' + (s.reason || '\u2014') + '</span>' +
          '<div class="snap-actions">' +
            '<div class="btn sm" data-action="prep-restore" data-ts="' + s.ts + '" data-dir="' + s.db_dir + '">Restore</div>' +
          '</div>' +
        '</div>';
      }).join('');
    } catch (e) {
      el.innerHTML = '<div class="empty">Error: ' + e.message + '</div>';
    }
  }

  function populateRestoreSelect() {
    var sel = document.getElementById('restore-snap-select');
    sel.innerHTML = '<option value="">\u2014 Select a snapshot \u2014</option>' +
      _snapshots.map(function(s) {
        return '<option value="' + s.ts + '|' + s.db_dir + '">' + s.ts + ' \u2014 ' + ((s.db_dir || '').split('/').pop() || '') + '</option>';
      }).join('');
  }

  function prepRestore(ts, dbDir) {
    document.getElementById('restore-snap-select').value = ts + '|' + dbDir;
    var el = document.querySelectorAll('.nav-item[data-page="restore"]');
    if (el[0]) el[0].click();
  }

  document.getElementById('create-snap-btn') && document.getElementById('create-snap-btn').addEventListener('click', function() {
    var el = document.querySelectorAll('.nav-item[data-page="databases"]');
    if (el[0]) el[0].click();
  });

  // ── Restore ──
  document.getElementById('restore-btn') && document.getElementById('restore-btn').addEventListener('click', function() {
    var sel = document.getElementById('restore-snap-select').value;
    if (!sel) return;
    var parts = sel.split('|');
    var ts = parts[0], dbDir = parts[1];
    var target = document.getElementById('restore-target').value.trim();
    var msg = target
      ? 'Copy snapshot <strong>' + ts + '</strong> to <code>' + target + '</code>?'
      : 'Restore snapshot <strong>' + ts + '</strong> IN PLACE to <code>' + dbDir + '</code>? A pre-restore backup will be created first.';
    document.getElementById('modal-restore-msg').innerHTML = msg;
    document.getElementById('modal-restore').classList.add('vis');

    var modalConfirm = document.getElementById('modal-confirm');
    modalConfirm.replaceWith(modalConfirm.cloneNode(false));
    document.getElementById('modal-confirm').addEventListener('click', async function() {
      document.getElementById('modal-restore').classList.remove('vis');
      document.getElementById('restore-status').textContent = 'Restoring\u2026';
      try {
        var r = await fetch(API + '/api/filedb/snapshots/restore', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ snap_ts: ts, db_dir: dbDir, target_dir: target || null })
        });
        var data = await r.json();
        document.getElementById('restore-status').textContent = data.ok
          ? '\u2713 Restored \u2014 ' + (data.restored_in_place || data.restored_to)
          : 'Error: ' + data.error;
      } catch (e) {
        document.getElementById('restore-status').textContent = 'Error: ' + e.message;
      }
    });
  });

  document.getElementById('modal-cancel') && document.getElementById('modal-cancel').addEventListener('click', function() {
    document.getElementById('modal-restore').classList.remove('vis');
  });

  // ── Settings ──
  async function loadSettings() {
    try {
      var r = await fetch(API + '/api/filedb/settings');
      var s = await r.json();
      document.getElementById('s-debounce').value = s.snapshot_debounce_sec;
      document.getElementById('s-maxsnaps').value = s.max_snapshots;
      document.getElementById('s-threshold').value = s.write_threshold;
      document.getElementById('s-watchroot').value = s.watch_root;
    } catch (e) {}
  }

  document.getElementById('save-settings') && document.getElementById('save-settings').addEventListener('click', async function() {
    var body = {
      snapshot_debounce_sec: parseInt(document.getElementById('s-debounce').value),
      max_snapshots: parseInt(document.getElementById('s-maxsnaps').value),
      write_threshold: parseInt(document.getElementById('s-threshold').value),
      watch_root: document.getElementById('s-watchroot').value,
    };
    try {
      await fetch(API + '/api/filedb/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      document.getElementById('settings-status').innerHTML = '\u2713 Saved (restart daemon to apply)';
    } catch (e) {
      document.getElementById('settings-status').textContent = 'Error: ' + e.message;
    }
  });

  // ── Logs ──
  async function loadLogs() {
    try {
      var r = await fetch(API + '/api/filedb/log?lines=200');
      var data = await r.json();
      var el = document.getElementById('log-area');
      el.innerHTML = data.lines.map(function(line) {
        var m = line.match(/\[(.+?)\] (\w+)\s+(.+)/);
        if (!m) return '<div class="log-line"><span class="ll-msg">' + line + '</span></div>';
        var cls = { SNAP: 'snap', LOCK: 'lock', WARN: 'warn', START: 'start', RESTORE: 'snap' }[m[2]] || 'start';
        return '<div class="log-line"><span class="ll-ts">' + m[1] + '</span><span class="ll-lvl-' + cls + '">' + m[2] + '</span><span class="ll-msg">' + m[3] + '</span></div>';
      }).join('');
      var auto = document.getElementById('autoscroll');
      if (auto && auto.checked) el.scrollTop = el.scrollHeight;
    } catch (e) {}
  }

  function appendLog(lvl, msg) {
    var el = document.getElementById('log-area');
    if (!el) return;
    var ts = new Date().toLocaleTimeString();
    var cls = { SNAP: 'snap', LOCK: 'lock', WARN: 'warn', START: 'start' }[lvl] || 'start';
    el.innerHTML += '<div class="log-line"><span class="ll-ts">' + ts + '</span><span class="ll-lvl-' + cls + '">' + lvl + '</span><span class="ll-msg">' + msg + '</span></div>';
    var auto = document.getElementById('autoscroll');
    if (auto && auto.checked) el.scrollTop = el.scrollHeight;
  }

  document.getElementById('clear-log') && document.getElementById('clear-log').addEventListener('click', function() {
    document.getElementById('log-area').innerHTML = '';
  });

  // ── Init ──
  fetch(API + '/api/filedb/status').then(function(r) { return r.json(); }).then(updateStatus).catch(function() {});
  fetch(API + '/api/health').then(function(r) { return r.json(); }).then(function(d) {
    document.getElementById('footer-host').textContent = d.product + ' ' + d.version;
  }).catch(function() {});

})();
