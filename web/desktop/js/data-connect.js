(function () {
  "use strict";
  function $(s, r) { return (r || document).querySelector(s); }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function toast(m, k) {
    var t = document.createElement('div');
    t.className = 'toast ' + (k || 'info'); t.textContent = m;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add('show'); }, 10);
    setTimeout(function () { t.classList.remove('show'); setTimeout(function () { t.remove(); }, 300); }, 3200);
  }
  async function api(p, o) {
    o = o || {};
    o.headers = Object.assign({ 'Content-Type': 'application/json' }, o.headers || {});
    var tok = localStorage.getItem('forgeos_token');
    if (tok) o.headers['Authorization'] = 'Bearer ' + tok;
    try {
      var r = await fetch(p, o);
      var data = null; try { data = await r.json(); } catch (e) {}
      if (r.status === 401) { localStorage.removeItem('forgeos_token'); location.href = '/index.html'; }
      return { ok: r.ok, status: r.status, data: data };
    } catch (e) { return { ok: false, status: 0, data: null }; }
  }

  function kindBadge(kind) {
    if (kind === 'postgres') return '<span class="tag rw">PostgreSQL</span>';
    if (kind === 'mysql') return '<span class="tag rw">MySQL</span>';
    return '<span class="tag ro">file-based</span>';
  }

  var _dc = { broadcast: true, databases: [] };

  async function load() {
    var r = await api('/api/data-connect');
    if (!r.ok || !r.data) { $('#db-list').innerHTML = '<p style="color:var(--danger)">Could not load databases.</p>'; return; }
    _dc = r.data;
    var sw = $('#dc-broadcast'); if (sw) sw.className = 'switch' + (_dc.broadcast ? ' on' : '');
    var chip = $('#db-chip'); if (chip) chip.textContent = (_dc.databases.length || 0) + ' database' + (_dc.databases.length === 1 ? '' : 's');
    renderList();
  }

  function renderList() {
    var box = $('#db-list'); if (!box) return;
    if (!_dc.databases.length) {
      box.innerHTML = '<p style="color:var(--muted)">No databases yet. Import a file-based database directory to track and protect it.</p>';
      return;
    }
    box.innerHTML = '<div class="dc-grid">' + _dc.databases.map(function (d) {
      var missing = d.exists === false ? ' <span class="tag" style="background:var(--danger-soft);color:var(--danger)">path missing</span>' : '';
      var prot = d.protected
        ? '<span class="tag" style="background:var(--ok-soft,rgba(0,160,90,.12));color:var(--ok,#0a8a52)" title="SMB share modes: oplocks off, strict locking, write-through">protected</span>'
        : '<span class="tag" style="background:var(--danger-soft);color:var(--danger)" title="Samba is disabled — no share, no protection">UNPROTECTED</span>';
      var app = d.app ? '<span class="tag">' + esc(d.app) + '</span>' : '<span class="tag" style="color:var(--muted)">unassigned</span>';
      var typ = d.db_type ? '<span class="hint">' + esc(d.db_type) + '</span>' : '';
      var portLine = d.port ? '<div class="hint" style="margin:2px 0 0">port ' + d.port + '</div>' : '';
      return '<div class="dc-card">' +
        '<div class="dc-card-top"><div class="dc-name">' + esc(d.name) + ' ' + kindBadge(d.kind) + '</div>' +
        '<button class="icon-btn danger" data-del="' + esc(d.name) + '" title="Stop tracking this database"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7"/></svg></button></div>' +
        '<div class="dc-tags">' + app + ' ' + typ + ' ' + prot + missing + '</div>' +
        '<div class="hint" style="margin:8px 0 0;word-break:break-all">path: <code>' + esc(d.data_path) + '</code></div>' + portLine +
        (d.comment ? '<div class="hint" style="margin:4px 0 0">' + esc(d.comment) + '</div>' : '') +
        '</div>';
    }).join('') + '</div>';
    box.querySelectorAll('[data-del]').forEach(function (b) {
      b.onclick = function () { removeDb(b.getAttribute('data-del')); };
    });
  }

  async function removeDb(name) {
    if (!confirm('Stop tracking "' + name + '"? Files on disk are left untouched.')) return;
    var r = await api('/api/data-connect/' + encodeURIComponent(name), { method: 'DELETE' });
    if (r.ok) { toast('Removed', 'ok'); load(); }
    else toast((r.data && r.data.detail) || 'Could not remove', 'err');
  }

  function importModal() {
    var back = document.createElement('div'); back.className = 'modal-back';
    back.innerHTML =
      '<div class="modal" style="max-width:520px">' +
      '<h3>Import a database</h3>' +
      '<p class="hint">Track an existing file-based database directory. Data Connect auto-detects the database family; you tag which app owns it.</p>' +
      '<div class="fld"><label>Name</label><input class="wz-input" id="i-name" placeholder="pos-main" autocomplete="off"></div>' +
      '<div class="fld"><label>Directory / data path</label><input class="wz-input" id="i-path" placeholder="/srv/nas/tank/databases/pos" autocomplete="off">' +
        '<div class="hint" id="i-detect"></div></div>' +
      '<div class="fld"><label>App (owner)</label><input class="wz-input" id="i-app" placeholder="Atrex, QuickBooks, ..." autocomplete="off"></div>' +
      '<div class="fld"><label>Comment (optional)</label><input class="wz-input" id="i-comment" autocomplete="off"></div>' +
      '<div id="i-out" class="raw-err" style="display:none"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
        '<button class="button ghost" id="i-cancel">Cancel</button><button class="button" id="i-go">Import</button></div>' +
      '</div>';
    document.body.appendChild(back);
    $('#i-cancel', back).onclick = function () { back.remove(); };
    // live detect on path blur
    $('#i-path', back).addEventListener('blur', async function () {
      var p = this.value.trim(); if (!p) return;
      var r = await api('/api/data-connect/detect?path=' + encodeURIComponent(p));
      var h = $('#i-detect', back);
      if (r.ok && r.data) h.textContent = r.data.db_type ? 'Detected: ' + r.data.db_type : 'No known database files detected (you can still import).';
      else h.textContent = '';
    });
    $('#i-go', back).onclick = async function () {
      var name = $('#i-name', back).value.trim();
      var path = $('#i-path', back).value.trim();
      if (!name || !path) { toast('Name and path required', 'err'); return; }
      this.disabled = true; this.style.opacity = .5;
      var r = await api('/api/data-connect/import', { method: 'POST', body: JSON.stringify({
        name: name, data_path: path, app: $('#i-app', back).value.trim(),
        comment: $('#i-comment', back).value.trim() }) });
      if (r.ok) { toast('Imported' + (r.data && r.data.db_type ? ' (' + r.data.db_type + ')' : ''), 'ok'); back.remove(); load(); }
      else { var o = $('#i-out', back); o.style.display = ''; o.textContent = (r.data && r.data.detail) || 'Could not import'; this.disabled = false; this.style.opacity = 1; }
    };
  }

  function serverModal() {
    var back = document.createElement('div'); back.className = 'modal-back';
    back.innerHTML =
      '<div class="modal" style="max-width:520px">' +
      '<h3>Add a server database</h3>' +
      '<p class="hint">Run PostgreSQL or MariaDB on this NAS. Clients connect over the native port; the data directory stays local (never on a share). ForgeOS pins durability settings and schedules weekly integrity checks.</p>' +
      '<div class="fld"><label>Engine</label><select class="wz-input" id="s-engine"><option value="postgres">PostgreSQL (port 5432)</option><option value="mysql">MariaDB (port 3306)</option></select></div>' +
      '<div class="fld"><label>Name</label><input class="wz-input" id="s-name" placeholder="main-db" autocomplete="off"></div>' +
      '<div class="fld"><label>App (owner)</label><input class="wz-input" id="s-app" autocomplete="off"></div>' +
      '<div class="fld"><label style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="s-install"> Install the engine if missing</label></div>' +
      '<div id="s-out" class="raw-err" style="display:none"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
        '<button class="button ghost" id="s-cancel">Cancel</button><button class="button" id="s-go">Add</button></div>' +
      '</div>';
    document.body.appendChild(back);
    $('#s-cancel', back).onclick = function () { back.remove(); };
    $('#s-go', back).onclick = async function () {
      var name = $('#s-name', back).value.trim();
      if (!name) { toast('Name required', 'err'); return; }
      var btn = this;
      btn.disabled = true; btn.style.opacity = .5; btn.textContent = 'Working…';
      var payload = { name: name, engine: $('#s-engine', back).value,
                      app: $('#s-app', back).value.trim(),
                      install: $('#s-install', back).checked };
      var attempt = 0;
      async function go() {
        var r = await api('/api/data-connect/register-server', { method: 'POST', body: JSON.stringify(payload) });
        // 202 FIRST: fetch's Response.ok is true for ANY 2xx, so checking
        // r.ok first would treat "still installing" as success (bug: modal
        // closed, polling never started, registration never completed).
        if (r.status === 202 && attempt++ < 120) {
          btn.textContent = 'Installing engine…';
          setTimeout(go, 5000); return;
        }
        if (r.ok) { toast('Server database added', 'ok'); back.remove(); load(); return; }
        var o = $('#s-out', back); o.style.display = '';
        o.textContent = (r.data && r.data.detail) || 'Could not add';
        btn.disabled = false; btn.style.opacity = 1; btn.textContent = 'Add';
      }
      go();
    };
  }

  document.addEventListener('DOMContentLoaded', function () {
    var imp = $('#db-import'); if (imp) imp.onclick = importModal;
    var srv = $('#db-server'); if (srv) srv.onclick = serverModal;
    var rf = $('#refresh'); if (rf) rf.onclick = function () { load(); toast('Refreshed', 'info'); };
    var sw = $('#dc-broadcast'); if (sw) sw.onclick = async function () {
      var next = !(_dc.broadcast);
      var r = await api('/api/data-connect/broadcast', { method: 'POST', body: JSON.stringify({ broadcast: next }) });
      if (r.ok) { _dc.broadcast = r.data.broadcast; this.className = 'switch' + (_dc.broadcast ? ' on' : ''); toast('Broadcast ' + (_dc.broadcast ? 'on' : 'off'), 'ok'); }
      else toast('Could not change broadcast', 'err');
    };
    load();
  });
})();
