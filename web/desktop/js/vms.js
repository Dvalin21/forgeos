/* ForgeOS — Virtual Machines page (Incus virtual-machine instances).
 *
 * Same shape as containers.js with type=virtual-machine. Split out rather
 * than parameterised because the copy, the sizing defaults and the create
 * payload genuinely differ - a shared file would carry two sets of
 * conditionals for no benefit.
 *
 * Two behaviours worth stating, because both were explicitly asked for:
 *   1. Hardware fields are EDITABLE. A preset only fills the inputs; it never
 *      locks them, and the API takes whatever is in them. No create-stop-
 *      edit-start dance to change a size.
 *   2. The API is the only source of truth. Nothing is clamped client-side,
 *      and a rejection from Incus is shown verbatim rather than reworded into
 *      something that hides what actually went wrong.
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
    k = k || 'info'; var b = $('#toasts'); if (!b) return;
    var e = document.createElement('div'); e.className = 'toast ' + k; e.textContent = m; b.appendChild(e);
    setTimeout(function () { e.style.transition = 'opacity .2s'; e.style.opacity = 0; setTimeout(function () { e.remove(); }, 220); }, 4500);
  }
  function human(n) {
    n = Number(n) || 0; if (!n) return '0 B';
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : n) + ' ' + u[i];
  }

  var TYPE = 'virtual-machine';
  var STATE = { installed: false, instances: [] };

  async function load() {
    var st = await api('/api/incus/status');
    STATE.installed = !!(st.ok && st.data && st.data.installed && st.data.initialised);
    if (!STATE.installed) {
      $('#gate-install').style.display = '';
      $('#panel-list').style.display = 'none';
      $('#panel-create').style.display = 'none';
      var why = $('#gate-err');
      if (why) why.textContent = st.ok && st.data && st.data.installed ? 'not initialised yet' : 'incus is not installed';
      return;
    }
    $('#gate-install').style.display = 'none';
    $('#panel-list').style.display = '';
    var r = await api('/api/incus/instances');
    STATE.instances = (r.data && r.data.instances) || [];
    render();
  }

  function render() {
    var list = STATE.instances;
    $('#s-total').textContent = list.length;
    $('#s-running').textContent = list.filter(function (i) { return i.status === 'Running'; }).length;
    $('#s-mem').textContent = human(list.reduce(function (a, i) { return a + (Number(i.memory_bytes) || 0); }, 0));
    $('#s-disk').textContent = list.reduce(function (a, i) { return a + (Number(i.disk_bytes) || 0); }, 0) ? human(list.reduce(function (a, i) { return a + (Number(i.disk_bytes) || 0); }, 0)) : '—';
    $('#list-sub').textContent = list.length ? 'Start and stop them freely — the NAS is unaffected either way.' : '';

    var box = $('#rows');
    if (!list.length) {
      box.innerHTML = '<p class="empty-state">No containers yet. Create one above.</p>';
      return;
    }
    box.innerHTML = list.map(function (i) {
      var running = i.status === 'Running';
      var meta = [
        i.image || '—',
        i.ipv4 || 'no address',
        i.cpu_limit ? i.cpu_limit + ' core' + (i.cpu_limit === '1' ? '' : 's') : 'unlimited CPU',
        i.memory_limit || 'unlimited RAM',
        i.disk_display === 'unlimited' ? 'unlimited disk' : i.disk_display + ' disk'
      ].join(' · ');
      return '<div class="mrow">' +
        '<div class="share-ico"><svg viewBox="0 0 24 24"><path d="M12 2 4 7v10l8 5 8-5V7z"/></svg></div>' +
        '<div style="min-width:0"><b>' + esc(i.name) + '</b><div class="sub">' + esc(meta) + '</div></div>' +
        '<div style="display:flex;gap:8px;align-items:center">' +
          '<span class="chip ' + (running ? 'ok' : '') + '">' + (running ? 'Running' : esc(i.status)) + '</span>' +
          '<button class="btn-' + (running ? '' : 'pri') + '" data-act="' + (running ? 'stop' : 'start') + '" data-n="' + esc(i.name) + '">' + (running ? 'Stop' : 'Start') + '</button>' +
        '</div></div>';
    }).join('');
    $$('[data-act]').forEach(function (b) {
      b.onclick = function () { act(b.getAttribute('data-act'), b.getAttribute('data-n')); };
    });
  }

  async function act(a, name) {
    var r = await api('/api/incus/instances/' + encodeURIComponent(name) + '/' + a, { method: 'POST' });
    if (!r.ok) { toast((r.data && r.data.detail) || 'That did not work', 'err'); return; }
    toast(a === 'stop' ? 'Stopped' : 'Started', 'ok');
    load();
  }

  // Presets fill the inputs. They are not a mode — once filled the fields are
  // the user's, and the API receives exactly what is in them.
  function bindPresets() {
    $$('[data-preset]').forEach(function (b) {
      b.onclick = function () {
        var p = b.getAttribute('data-preset').split('|');
        $('#f-cpu').value = p[0];
        $('#f-disk').value = p[1] + 'GiB';
        if (!$('#f-mem').value) $('#f-mem').value = p[0] + 'GiB';
      };
    });
  }

  async function create() {
    var name = ($('#f-name').value || '').trim();
    var body = {
      name: name,
      image: $('#f-image').value,
      type: TYPE,
      cpu_limit: ($('#f-cpu').value || '').trim(),
      memory: ($('#f-mem').value || '').trim(),
      disk: ($('#f-disk').value || '').trim()
    };
    var btn = $('#create'); btn.disabled = true;
    btn.textContent = 'Creating…';
    var r = await api('/api/incus/instances', { method: 'POST', body: JSON.stringify(body) });
    btn.disabled = false; btn.textContent = 'Create';
    if (!r.ok) { toast((r.data && r.data.detail) || 'Could not create the virtual machine', 'err'); return; }
    toast('Virtual machine created', 'ok');
    $('#f-name').value = ''; $('#f-cpu').value = ''; $('#f-mem').value = ''; $('#f-disk').value = '';
    $('#panel-create').style.display = 'none';
    load();
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindPresets();
    var nb = $('#new-vm');
    if (nb) nb.onclick = function () {
      var p = $('#panel-create');
      p.style.display = p.style.display === 'none' ? '' : 'none';
    };
    var c = $('#cancel'); if (c) c.onclick = function () { $('#panel-create').style.display = 'none'; };
    var cr = $('#create'); if (cr) cr.onclick = create;
    var rf = $('#refresh'); if (rf) rf.onclick = function () { load(); toast('Refreshed', 'info'); };
    var nb2 = $('#new-vm');
    if (nb2) nb2.onclick = nb2.onclick || function () {};
    var ib = $('#install-btn');
    if (ib) ib.onclick = function () { toast('Installing Incus is not wired up yet', 'warn'); };
    load();
  });
})();