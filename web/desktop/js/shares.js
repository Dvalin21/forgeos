/* ForgeOS — Shares (SMB) page.
 *
 * Mirrors firewall.js: same $ / api / esc / toast helpers and the same
 * modal-back "wizard" pattern. Talks to /api/samba/* (shares CRUD +
 * smbstatus). Every advanced per-share option is a plain control here — no
 * "advanced" toggle — and `browseable` is OFF by default (opt-in).
 */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  function token() { try { return localStorage.getItem('forgeos_token'); } catch (e) { return null; } }
  async function api(p, o) {
    o = o || {}; var h = Object.assign({}, o.headers || {}); var t = token(); if (t) h.Authorization = 'Bearer ' + t;
    if (o.body && !h['Content-Type']) h['Content-Type'] = 'application/json';
    try { var r = await fetch(p, Object.assign({}, o, { headers: h })); var d = null; try { d = await r.json(); } catch (e) {} return { ok: r.ok, status: r.status, data: d }; }
    catch (e) { return { ok: false, data: null }; }
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function toast(m, k) {
    k = k || 'info'; var b = $('#toasts'), e = document.createElement('div'); e.className = 'toast ' + k; e.textContent = m; b.appendChild(e);
    setTimeout(function () { e.style.transition = 'opacity .2s'; e.style.opacity = 0; setTimeout(function () { e.remove(); }, 220); }, 4000);
  }

  var TYPES = [
    { id: 'standard', label: 'Standard', desc: 'Normal shared folder' },
    { id: 'timemachine', label: 'Time Machine', desc: 'macOS backup target' },
    { id: 'public-ro', label: 'Public (read-only)', desc: 'Guest access, no login' },
    { id: 'database', label: 'Database', desc: 'App / database files' }
  ];
  function typeLabel(t) { var x = TYPES.filter(function (y) { return y.id === t; })[0]; return x ? x.label : t; }

  var FOLDER_SVG = '<svg viewBox="0 0 24 24"><path d="M3.8 6.5h6.5l1.8 2h8.1v9.8c0 1.1-.9 2-2 2H5.8c-1.1 0-2-.9-2-2z"/><path d="M3.8 8.5V5.7c0-1.1.9-2 2-2h4.1l1.7 1.8h5.2c1.1 0 2 .9 2 2v1"/></svg>';
  var REFRESH_SVG = '<svg class="ico" viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4M20 12a8 8 0 0 1-13.7 5.7L4 16M4 20v-4h4"/></svg>';

  // ── share list ──
  async function loadShares() {
    var d = (await api('/api/samba/shares')).data;
    var box = $('#shares');
    if (!d) { box.innerHTML = '<p style="color:var(--muted)">Could not read shares.</p>'; $('#share-chip').textContent = '—'; return; }
    var shares = d.shares || [];
    $('#share-chip').textContent = shares.length + ' share' + (shares.length !== 1 ? 's' : '');
    if (!shares.length) {
      box.innerHTML = '<p style="color:var(--muted)">No shares yet. Tap <b>New Share</b> to share a folder over the network.</p>';
      return;
    }
    box.innerHTML = shares.map(function (s) {
      var rw = s.type === 'public-ro' ? false : !!s.writable;
      var vis = !!s.browseable;
      var tags = '<span class="tag type">' + esc(typeLabel(s.type)) + '</span>' +
        '<span class="tag ' + (rw ? 'rw' : 'ro') + '">' + (rw ? 'Read &amp; write' : 'Read-only') + '</span>' +
        '<span class="tag ' + (vis ? 'vis' : 'hid') + '">' + (vis ? 'Visible' : 'Hidden') + '</span>' +
        ((s.guest_ok || s.type === 'public-ro') ? '<span class="tag gst">Guest</span>' : '') +
        (s.recycle_bin ? '<span class="tag hid">Recycle</span>' : '');
      return '<div class="share-row">' +
        '<div class="share-ico">' + FOLDER_SVG + '</div>' +
        '<div><div class="share-name">' + esc(s.name) + '</div><div class="share-path">' + esc(s.path) + '</div></div>' +
        '<div class="share-tags">' + tags + '</div>' +
        '<button class="share-del" data-del="' + esc(s.name) + '" title="Stop sharing"><svg class="ico" viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button>' +
        '</div>';
    }).join('');
    $$('[data-del]').forEach(function (b) { b.onclick = function () { delShare(b.getAttribute('data-del')); }; });
  }

  async function loadConnections() {
    var d = (await api('/api/samba/connections')).data;
    $('#connections').textContent = (d && d.output) || 'No active connections.';
  }

  async function delShare(name) {
    if (!confirm('Stop sharing "' + name + '"?\n\nThe folder and its files are NOT deleted — only the network share is removed.')) return;
    var r = await api('/api/samba/share/' + encodeURIComponent(name), { method: 'DELETE' });
    toast(r.ok ? 'Share removed' : (r.data && r.data.detail) || 'Could not remove share', r.ok ? 'ok' : 'err');
    if (r.ok) { loadShares(); loadConnections(); }
  }

  // ── New Share modal ──
  function optRow(k, title, desc) {
    return '<div class="opt-row"><div class="opt-text"><h5>' + title + '</h5><p>' + desc + '</p></div>' +
      '<div class="switch" data-sw="' + k + '"><i></i></div></div>';
  }

  function shareModal() {
    var st = { type: 'standard', writable: true, browseable: false, guest_ok: false, recycle_bin: false, hide_dot_files: true, permissions: 'group' };
    var back = document.createElement('div'); back.className = 'modal-back';
    back.innerHTML = '<div class="modal share-modal"><h3>New share</h3>' +
      '<p class="sub">Share a folder over the network. Pick a type, choose who can reach it, fine-tune below — everything has a safe default.</p>' +
      '<div class="fld"><label>Folder type</label><div class="svc-grid" id="ty">' +
        TYPES.map(function (t) { return '<div class="svc-opt" data-type="' + t.id + '"><h5>' + esc(t.label) + '</h5><p>' + esc(t.desc) + '</p></div>'; }).join('') +
      '</div></div>' +
      '<div class="fld"><label>Share name</label><input class="wz-input" id="s-name" placeholder="e.g. Media" autocomplete="off"><div class="hint">The name people see on the network. Letters, numbers, _ and - only.</div></div>' +
      '<div class="fld"><label>Folder path</label><input class="wz-input" id="s-path" placeholder="/srv/nas/tank/media" autocomplete="off"><div class="hint">Absolute path on this NAS to share.</div></div>' +
      '<div class="fld"><label>Who can access</label><input class="wz-input" id="s-users" placeholder="@users   (or: keith lorri)" autocomplete="off"><div class="hint">Groups start with @. Space-separated. Ignored for Public shares.</div></div>' +
      '<div class="fld"><label>File permissions</label><div class="seg" id="perm">' +
        '<button data-p="private">Private</button><button data-p="group">Group</button><button data-p="public">Public</button></div>' +
        '<div class="hint">Private 0600/0700 &middot; Group 0660/0770 &middot; Public 0664/0775.</div></div>' +
      '<div class="fld"><label>Options</label>' +
        optRow('browseable', 'Show in network browse list', 'Off = hidden; reachable only by exact path. Off by default.') +
        optRow('writable', 'Read &amp; write', 'Turn off to make the share read-only.') +
        optRow('guest_ok', 'Allow guest access', 'Anyone on the network can connect without a login.') +
        optRow('recycle_bin', 'Recycle bin', 'Deleted files go to a recoverable .recycle folder.') +
        optRow('hide_dot_files', 'Hide dot-files', 'Hide files whose names start with a dot.') +
      '</div>' +
      '<div class="fld"><label>Force owner (optional)</label><div class="wz-from"><input class="wz-input" id="s-fuser" placeholder="force user"><input class="wz-input" id="s-fgroup" placeholder="force group"></div><div class="hint">All files appear owned by this user / group. Leave blank to keep real ownership.</div></div>' +
      '<div class="fld"><label>Comment (optional)</label><input class="wz-input" id="s-comment" placeholder="Family media library"></div>' +
      '<div class="summary" id="s-sum">Fill in a name and path to begin.</div>' +
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go disabled style="opacity:.5">Create share</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var go = $('[data-go]', back), sum = $('#s-sum', back);

    function setSw(k, on) { st[k] = !!on; var el = $('[data-sw="' + k + '"]', back); if (el) el.className = 'switch' + (on ? ' on' : ''); }
    $$('[data-sw]', back).forEach(function (el) {
      el.onclick = function () { var k = el.getAttribute('data-sw'); setSw(k, !st[k]); update(); };
    });

    function selType(t) {
      st.type = t;
      $$('#ty .svc-opt', back).forEach(function (o) { o.classList.toggle('sel', o.getAttribute('data-type') === t); });
      if (t === 'public-ro') { setSw('writable', false); setSw('guest_ok', true); }
      if (t === 'timemachine') { setSw('writable', true); }
      update();
    }
    $$('#ty .svc-opt', back).forEach(function (o) { o.onclick = function () { selType(o.getAttribute('data-type')); }; });

    function selPerm(p) { st.permissions = p; $$('#perm button', back).forEach(function (b) { b.className = b.getAttribute('data-p') === p ? 'sel pri' : ''; }); }
    $$('#perm button', back).forEach(function (b) { b.onclick = function () { selPerm(b.getAttribute('data-p')); }; });

    $$('#s-name,#s-path,#s-users', back).forEach(function (i) { i.oninput = update; });

    // defaults
    selType('standard'); selPerm('group');
    setSw('browseable', false); setSw('writable', true); setSw('guest_ok', false);
    setSw('recycle_bin', false); setSw('hide_dot_files', true);

    function update() {
      var name = $('#s-name', back).value.trim(), path = $('#s-path', back).value.trim();
      var nameOk = /^[A-Za-z0-9_-]{1,80}$/.test(name);
      var pathOk = path.charAt(0) === '/' && path.length > 1;
      var ok = nameOk && pathOk; go.disabled = !ok; go.style.opacity = ok ? 1 : .5;
      if (!name || !path) { sum.innerHTML = 'Fill in a name and path to begin.'; return; }
      var rw = st.type === 'public-ro' ? false : st.writable;
      var who = st.type === 'public-ro' ? 'anyone (guest)' : ($('#s-users', back).value.trim() || '@users');
      var vis = st.browseable ? 'visible in network browse' : 'hidden (exact path only)';
      sum.innerHTML = '<b>' + esc(name) + '</b> shares <b>' + esc(path) + '</b> as <b>' + esc(typeLabel(st.type)) + '</b>, ' +
        (rw ? 'read &amp; write' : 'read-only') + ' for <b>' + esc(who) + '</b> &middot; ' + vis + '.';
    }

    var close = function () { back.remove(); };
    back.addEventListener('click', function (e) { if (e.target === back || e.target.hasAttribute('data-x')) close(); });
    go.onclick = async function () {
      var users = $('#s-users', back).value.trim();
      var body = {
        name: $('#s-name', back).value.trim(),
        path: $('#s-path', back).value.trim(),
        type: st.type,
        writable: st.writable,
        browseable: st.browseable,
        guest_ok: st.guest_ok,
        recycle_bin: st.recycle_bin,
        hide_dot_files: st.hide_dot_files,
        permissions: st.permissions,
        force_user: $('#s-fuser', back).value.trim(),
        force_group: $('#s-fgroup', back).value.trim(),
        comment: $('#s-comment', back).value.trim()
      };
      if (users) body.valid_users = users.split(/\s+/);
      go.disabled = true; go.style.opacity = .5;
      var r = await api('/api/samba/share', { method: 'POST', body: JSON.stringify(body) });
      toast(r.ok ? 'Share created' : (r.data && r.data.detail) || 'Could not create share', r.ok ? 'ok' : 'err');
      if (r.ok) { close(); loadShares(); loadConnections(); }
      else { go.disabled = false; go.style.opacity = 1; }
    };
  }

  document.addEventListener('DOMContentLoaded', function () {
    var add = $('#add-share'); if (add) add.onclick = shareModal;
    var rf = $('#refresh'); if (rf) rf.onclick = function () { loadShares(); loadConnections(); toast('Refreshed', 'info'); };
    var rc = $('#refresh-conn'); if (rc) rc.onclick = function () { loadConnections(); toast('Connections refreshed', 'info'); };
    loadShares(); loadConnections();
  });
})();
