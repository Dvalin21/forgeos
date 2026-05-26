/* forgeos.js - Core application shell / event bus
 * Coordinates window-manager, sidebar, topbar, and other components.
 * Single point of initialization — no DOMContentLoaded conflicts.
 * Provides modal system, event bus, auth, and app lifecycle.
 */
window.forgeOS = (() => {
  const listeners = {};

  function dispatch(event, detail) {
    (listeners[event] || []).forEach(fn => fn(detail));
  }

  function listen(event, fn) {
    (listeners[event] = listeners[event] || []).push(fn);
  }

  function openWindow(appId) {
    if (typeof openAppWindow === 'function') {
      openAppWindow(appId);
    }
  }

  // ─── Auth ───

  const TOKEN_KEY = 'forgeos_token';

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  }

  function showLogin() {
    const ol = document.getElementById('login-overlay');
    const d = document.getElementById('desktop');
    if (ol) ol.classList.remove('hidden');
    if (d) d.classList.add('auth-hidden');
    document.body.classList.add('modal-open');
    const input = document.getElementById('login-user');
    if (input) setTimeout(() => input.focus(), 100);
  }

  function hideLogin() {
    const ol = document.getElementById('login-overlay');
    const d = document.getElementById('desktop');
    if (ol) ol.classList.add('hidden');
    if (d) d.classList.remove('auth-hidden');
    document.body.classList.remove('modal-open');
  }

  function showLoginError(msg) {
    const el = document.getElementById('login-error');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  }

  function hideLoginError() {
    const el = document.getElementById('login-error');
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  }

  function checkAuth() {
    const token = getToken();
    if (!token) {
      showLogin();
      return false;
    }
    return true;
  }

  async function login() {
    hideLoginError();
    const user = document.getElementById('login-user');
    const pass = document.getElementById('login-pass');
    const btn  = document.getElementById('login-btn');
    if (!user || !pass) return;

    const username = user.value.trim();
    const password = pass.value;
    if (!username || !password) {
      showLoginError('Please enter username and password');
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Signing in...';

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok || !data.token) {
        showLoginError(data.detail || 'Login failed');
        btn.disabled = false;
        btn.textContent = 'Sign In';
        return;
      }
      setToken(data.token);
      hideLogin();
      // Re-trigger initial dashboard load now that we're authenticated
      setTimeout(refreshDashboard, 500);
    } catch (e) {
      showLoginError('Network error — cannot reach server');
      btn.disabled = false;
      btn.textContent = 'Sign In';
    }
  }

  function logout() {
    setToken(null);
    showLogin();
    // Close all open windows
    const wins = document.querySelectorAll('#window-area .window');
    wins.forEach(w => w.remove());
    if (window.windowStack) window.windowStack.length = 0;
    if (window.windowCounter) window.windowCounter = 1;
  }

  // Enter key submits login
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('login-overlay') &&
        !document.getElementById('login-overlay').classList.contains('hidden')) {
      login();
    }
  });

  // ─── Modal System ───

  function showModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('hidden');
    el.classList.add('modal-visible');
    document.body.classList.add('modal-open');
    const input = el.querySelector('input:not([type="hidden"])');
    if (input) setTimeout(() => input.focus(), 100);
  }

  function hideModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('hidden');
    el.classList.remove('modal-visible');
    document.body.classList.remove('modal-open');
  }

  function setupModalDismiss() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const visible = document.querySelector('.modal-overlay.modal-visible');
        if (visible) hideModal(visible.id);
      }
    });
  }

  // ─── Event Delegation (replaces all inline onclick handlers) ───

  function setupActionDelegation() {
    document.addEventListener('click', (e) => {
      const target = e.target.closest('[data-action]');
      if (!target) {
        // Click on modal backdrop — dismiss
        const modal = e.target.closest('.modal-overlay');
        if (modal && e.target === modal) {
          hideModal(modal.id);
        }
        return;
      }

      const action = target.getAttribute('data-action');
      const modal  = target.getAttribute('data-modal');

      if (modal && (action === 'hide-modal' || action === 'cancel')) {
        hideModal(modal);
        return;
      }

      switch (action) {
        case 'login':            login(); break;
        case 'logout':           logout(); break;
        case 'toggle-sidebar':   if (typeof toggleSidebar === 'function') toggleSidebar(); break;
        case 'create-pool':      createPool(); break;
        case 'add-drive':        addDrive(); break;
        case 'create-snapshot':  createSnapshot(); break;
        case 'create-share':     createShare(); break;
        case 'create-vhost':     createVhost(); break;
        case 'run-backup':       runBackup(); break;
        case 'dismiss-toast': {
          const parent = target.closest('.toast');
          if (parent) {
            parent.classList.add('toast-out');
            setTimeout(() => { if (parent.parentNode) parent.remove(); }, 200);
          }
          break;
        }
      }
    });
  }

  // ─── Confirm Dialog ───

  let confirmCallback = null;

  function showConfirm(title, message, onConfirm) {
    const titleEl = document.getElementById('modal-confirm-title');
    const msgEl = document.getElementById('modal-confirm-msg');
    const actionEl = document.getElementById('modal-confirm-action');
    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.innerHTML = message;
    confirmCallback = onConfirm || null;
    if (actionEl) {
      const newBtn = actionEl.cloneNode(true);
      actionEl.parentNode.replaceChild(newBtn, actionEl);
      newBtn.addEventListener('click', () => {
        hideModal('modal-confirm');
        if (typeof confirmCallback === 'function') confirmCallback();
        confirmCallback = null;
      });
    }
    showModal('modal-confirm');
  }

  // ─── App Actions (placeholder) ───

  function openTerminal(name) {
    showModal('modal-terminal');
    const label = document.getElementById('terminal-container-name');
    if (label) label.textContent = name;
  }

  function closeTerminal() {
    hideModal('modal-terminal');
  }

  // ─── Modal Form Handlers ───

  function _submitAndToast(path, body, modalId, successMsg) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (res && (res.ok || res.task_id)) {
        showToast(successMsg || 'Operation completed', 'success');
        if (modalId) hideModal(modalId);
        refreshDashboard();
        return res;
      }
      showToast(res?.detail || 'Operation failed', 'error');
      return null;
    });
  }

  async function createSnapshot() {
    const nameEl = document.getElementById('snap-name');
    const srcEl  = document.getElementById('snap-source');
    const name   = nameEl ? nameEl.value.trim() : '';
    const pool   = srcEl  ? srcEl.value : '';
    if (!name) { showToast('Please enter a snapshot name.', 'warning'); return; }
    var res = await _submitAndToast('/api/storage/snapshot',
      { pool: pool, description: name }, 'modal-create-snapshot',
      'Snapshot created');
    if (res && res.task_id) pollTask(res.task_id);
  }

  async function createShare() {
    const nameEl = document.getElementById('share-name');
    const pathEl = document.getElementById('share-path');
    const typeEl = document.getElementById('share-type');
    const name   = nameEl ? nameEl.value.trim() : '';
    const path   = pathEl ? pathEl.value.trim() : '';
    const type   = typeEl ? typeEl.value : 'standard';
    if (!name || !path) { showToast('Share name and path are required.', 'warning'); return; }
    _submitAndToast('/api/samba/share',
      { name: name, path: path, type: type, writable: true },
      'modal-share', 'Share created');
  }

  async function createVhost() {
    const domainEl = document.getElementById('vhost-domain');
    const targetEl = document.getElementById('vhost-target');
    const tlsEl    = document.getElementById('vhost-tls');
    const domain   = domainEl ? domainEl.value.trim() : '';
    const target   = targetEl ? targetEl.value.trim() : '';
    const tls      = tlsEl    ? tlsEl.value : 'acme';
    if (!domain || !target) { showToast('Domain and target are required.', 'warning'); return; }
    var port = 80;
    try {
      var url = new URL(target);
      port = parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80);
    } catch (e) {
      var parts = target.split(':');
      port = parts.length > 1 ? parseInt(parts[parts.length - 1]) : 80;
      if (isNaN(port)) port = 80;
    }
    var name = domain.replace(/[^a-z0-9-]/g, '').toLowerCase().slice(0, 64);
    _submitAndToast('/api/nginx/vhost',
      { name: name, domain: domain, port: port, tls: tls, websocket: false, auth: 'none' },
      'modal-vhost', 'Virtual host created');
  }

  async function createPool() {
    const nameEl  = document.getElementById('pool-name');
    const levelEl = document.getElementById('pool-level');
    const name    = nameEl ? nameEl.value.trim() : '';
    const level   = levelEl ? parseInt(levelEl.value) : 5;
    if (!name) { showToast('Please enter a pool name.', 'warning'); return; }
    var drives = [];
    document.querySelectorAll('#modal-create-pool [data-device]:checked').forEach(function (cb) {
      drives.push(cb.getAttribute('data-device'));
    });
    if (drives.length < 2) { showToast('Select at least 2 drives.', 'warning'); return; }
    _submitAndToast('/api/storage/pool',
      { name: name, level: level, drives: drives },
      'modal-create-pool', 'Pool created');
  }

  async function addDrive() {
    var devEl  = document.getElementById('drive-device');
    var poolEl = document.getElementById('drive-pool');
    var device = devEl  ? devEl.value : '';
    var pool   = poolEl ? poolEl.value : '';
    if (!device || !pool) { showToast('Device and pool are required.', 'warning'); return; }
    _submitAndToast('/api/storage/drive',
      { device: device, pool: pool },
      'modal-add-drive', 'Drive added to pool');
  }

  async function runBackup() {
    const srcEl  = document.getElementById('backup-source');
    const dstEl  = document.getElementById('backup-dest');
    const source = srcEl ? srcEl.value : '';
    const dest   = dstEl ? dstEl.value : '';
    if (!source) { showConfirm('Validation', 'Please select a backup source.'); return; }
    const res = await api('/api/backup/borg/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'web-backup', source, destination: dest }),
    });
    if (res && res.task_id) {
      showToast('Backup started — tracking progress...', 'info', 4000);
      pollTask(res.task_id);
      hideModal('modal-backup');
    } else {
      showConfirm('Error', res?.detail || 'Backup failed to start');
    }
  }

  // ─── Toast Notifications ───

  function showToast(msg, type, duration) {
    type = type || 'info';
    duration = duration || 5000;
    const container = document.getElementById('toast-container');
    if (!container) return;
    const icons = { success: '✓', error: '✗', info: 'ⓘ', warning: '⚠' };
    const el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.innerHTML =
      '<span class="toast-icon">' + (icons[type] || 'ⓘ') + '</span>' +
      '<span class="toast-msg">' + escapeHtml(msg) + '</span>' +
      '<button class="toast-close" data-action="dismiss-toast">×</button>';
    container.appendChild(el);
    setTimeout(function () {
      el.classList.add('toast-out');
      setTimeout(function () { if (el.parentNode) el.remove(); }, 200);
    }, duration);
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ─── Async Task Poller ───

  var _taskPollers = {};

  function pollTask(taskId, onDone, onFail, interval) {
    interval = interval || 3000;
    if (_taskPollers[taskId]) return;
    var poller = setInterval(async function () {
      var res = await api('/api/backup/task/' + taskId);
      if (!res) return; // still running or 404
      clearInterval(poller);
      delete _taskPollers[taskId];
      var msg = (res.tool ? res.tool + ' ' : '') + (res.action || 'task');
      if (res.status === 'done') {
        showToast(msg + ' completed', 'success');
        if (typeof onDone === 'function') onDone(res);
      } else if (res.status === 'failed') {
        showToast(msg + ' failed: ' + (res.error || 'unknown error'), 'error');
        if (typeof onFail === 'function') onFail(res);
      }
      refreshDashboard();
    }, interval);
    _taskPollers[taskId] = poller;
  }

  // ─── API Client (Auth-Aware) ───

  async function api(path, options) {
    try {
      const token = getToken();
      const headers = options?.headers || {};
      if (token) headers['Authorization'] = 'Bearer ' + token;
      const res = await fetch(path, { ...options, headers });
      if (res.status === 401) {
        // Token expired — force re-login
        logout();
        return null;
      }
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  // ─── Dashboard Refresh ───

  async function refreshDashboard() {
    const token = getToken();
    if (!token) return;

    const stats = await api('/api/system/stats');
    if (!stats) return;

    // Update by data-stat attribute — no fragile array indexing
    const update = (stat, val, fallback) => {
      const el = document.querySelector(`[data-stat="${stat}"]`);
      if (el) el.textContent = val ?? fallback ?? '--';
    };
    const updateLabel = (stat, val) => {
      const el = document.querySelector(`[data-stat-label="${stat}"]`);
      if (el) el.textContent = val ?? '';
    };
    const updateTrend = (stat, val) => {
      const el = document.querySelector(`[data-stat-trend="${stat}"]`);
      if (el) el.textContent = val ?? '';
    };

    // CPU
    if (stats.cpu_pct != null) {
      update('cpu', stats.cpu_pct.toFixed(1) + '%');
      updateTrend('cpu', stats.cpu_pct > 80 ? 'High load' : stats.cpu_pct > 50 ? 'Moderate load' : 'Normal load');
    }

    // Fetch CPU model name from /api/system/info (async, best-effort)
    api('/api/system/info').then(info => {
      if (info && info.cpu) updateLabel('cpu', info.cpu.trim());
    });

    // Memory
    if (stats.memory) {
      const m = stats.memory;
      update('memory', (m.used_gb || 0).toFixed(1) + ' GB');
      updateLabel('memory', '/ ' + (m.total_gb || 0).toFixed(1) + ' GB (' + (m.percent || 0).toFixed(0) + '% used)');
      updateTrend('memory', 'Available: ' + ((m.total_gb || 0) - (m.used_gb || 0)).toFixed(1) + ' GB');
    }

    // Storage (fetch from /api/storage/df for live data)
    api('/api/storage/pools').then(pools => {
      if (pools && pools.pools) {
        let total = 0, used = 0;
        pools.pools.forEach(p => {
          if (p.size_bytes && p.used_bytes) {
            total += p.size_bytes;
            used += p.used_bytes;
          }
        });
        if (total > 0) {
          const freeGb = ((total - used) / 1e9).toFixed(1);
          const totalGb = (total / 1e9).toFixed(1);
          const pct = ((used / total) * 100).toFixed(0);
          update('storage', freeGb + ' TB');
          updateLabel('storage', '/ ' + totalGb + ' TB (' + pct + '% used)');
          updateTrend('storage', (total - used) / 1e12 > 0.1
            ? ((total - used) / 1e12).toFixed(1) + ' TB available'
            : ((total - used) / 1e9).toFixed(1) + ' GB available');
        }
      }
    });

    // Network
    if (stats.network) {
      const n = stats.network;
      const up = n.bytes_sent || 0;
      const down = n.bytes_recv || 0;
      const fmt = (b) => b > 1e9 ? (b/1e9).toFixed(1)+' GB' : b > 1e6 ? (b/1e6).toFixed(1)+' MB' : (b/1e3).toFixed(0)+' KB';
      update('network', fmt(down));
      updateLabel('network', 'Total transferred');
      updateTrend('network', 'Up: ' + fmt(up) + ' / Down: ' + fmt(down));
    }
  }

  // Refresh dashboard when windows are focused
  listen('window-focused', (appName) => {
    if (appName === 'dashboard') refreshDashboard();
  });

  // ─── Init ───

  function init() {
    setupActionDelegation();
    setupModalDismiss();

    // Auth gate — show login if no token
    if (!checkAuth()) return;

    // Initial dashboard load after 2s
    setTimeout(refreshDashboard, 2000);

    if (typeof ForgeSidebar === 'function') {
      const sidebar = new ForgeSidebar();
      sidebar.restore();
      window.forgeSidebar = sidebar;
    }

    if (typeof ForgeTopBar === 'function') {
      window.forgeTopBar = new ForgeTopBar();
    }

    if (typeof ForgeTaskbar === 'function') {
      window.forgeTaskbar = new ForgeTaskbar();
    }
  }

  return {
    dispatch, listen, openWindow, init,
    showModal, hideModal, showConfirm,
    openTerminal, closeTerminal,
    createSnapshot, createShare, createVhost,
    createPool, addDrive, runBackup,
    api, refreshDashboard,
    showToast, pollTask,
    login, logout, getToken, checkAuth,
  };
})();

document.addEventListener('DOMContentLoaded', () => window.forgeOS.init());
