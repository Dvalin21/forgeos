/* ForgeOS — Security Center. Consumes /api/security/{fail2ban,updates}.
 * Mirrors the shared $/api/esc/toast pattern. No firewall rules here — that's
 * its own page (linked). ponytail: reuses existing endpoints, zero new backend. */
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

  var SHIELD = '<svg viewBox="0 0 24 24" style="width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/></svg>';

  // ── fail2ban ──
  async function loadJails() {
    var d = (await api('/api/security/fail2ban')).data;
    var box = $('#jails');
    if (!d) { box.innerHTML = '<p style="color:var(--muted)">Could not read fail2ban.</p>'; $('#f2b-chip').textContent = '\u2014'; return; }
    var jl = d.jails || [];
    var on = jl.filter(function (j) { return j.enabled; });
    var banned = jl.reduce(function (n, j) { return n + (j.banned || []).length; }, 0);
    $('#f2b-chip').textContent = d.enabled ? (on.length + ' jails · ' + banned + ' banned') : 'disabled';
    if (!jl.length) { box.innerHTML = '<p style="color:var(--muted)">No jails.</p>'; }
    else {
      box.innerHTML = jl.map(function (j) {
        var bans = (j.banned || []).map(function (ip) {
          return '<span class="tag" style="cursor:default">' + esc(ip) +
            ' <a href="#" data-unban="' + esc(ip) + '" title="Unban" style="color:var(--danger);text-decoration:none;font-weight:800">&times;</a></span>';
        }).join(' ');
        var st = j.error ? '<span class="status warn">' + esc(j.error) + '</span>'
               : (j.enabled ? '<span class="status ok">Active</span>' : '<span class="status dim">Off</span>');
        return '<div class="mini-card" style="align-items:flex-start;flex-wrap:wrap">' +
          '<div class="mini-icon tile t-fw">' + SHIELD + '</div>' +
          '<div style="flex:1"><h4>' + esc(j.name) + '</h4>' +
          '<p>' + ((j.banned && j.banned.length) ? bans : (j.enabled ? 'no active bans' : 'not enabled')) + '</p></div>' +
          st + '</div>';
      }).join('');
      $$('[data-unban]').forEach(function (a) {
        a.onclick = function (e) { e.preventDefault(); unban(a.getAttribute('data-unban')); };
      });
    }
    $('#f2b-bantime').value = d.bantime || ''; $('#f2b-findtime').value = d.findtime || '';
    $('#f2b-maxretry').value = d.maxretry || '';
  }

  async function unban(ip) {
    var r = await api('/api/security/fail2ban/unban', { method: 'POST', body: JSON.stringify({ ip: ip }) });
    toast(r.ok ? ('Unbanned ' + ip) : (r.data && r.data.detail) || 'Unban failed', r.ok ? 'ok' : 'err');
    if (r.ok) loadJails();
  }

  async function saveF2b() {
    var body = { bantime: $('#f2b-bantime').value.trim(), findtime: $('#f2b-findtime').value.trim(),
                 maxretry: parseInt($('#f2b-maxretry').value, 10) };
    if (!body.bantime || !body.findtime || !(body.maxretry >= 1)) { toast('Fill bantime, findtime, maxretry', 'err'); return; }
    var btn = $('#f2b-save'); btn.disabled = true;
    var r = await api('/api/security/fail2ban', { method: 'PUT', body: JSON.stringify(body) });
    btn.disabled = false;
    toast(r.ok ? 'Applied' : (r.data && r.data.detail) || 'Save failed', r.ok ? 'ok' : 'err');
    if (r.ok) loadJails();
  }

  // ── updates ──
  var _up = { enabled: true, auto_reboot: false };
  function setSw(k, on) { _up[k] = !!on; var el = $('[data-sw="' + (k === 'enabled' ? 'up-enabled' : 'up-reboot') + '"]'); if (el) el.className = 'switch' + (on ? ' on' : ''); }
  async function loadUpdates() {
    var d = (await api('/api/security/updates')).data;
    if (!d) { $('#up-chip').textContent = '\u2014'; return; }
    _up = d; setSw('enabled', d.enabled); setSw('auto_reboot', d.auto_reboot);
    $('#up-time').value = d.reboot_time || '02:00';
    $('#up-time-row').style.display = d.auto_reboot ? '' : 'none';
    $('#up-chip').textContent = d.enabled ? 'automatic' : 'off';
  }
  async function saveUpdates() {
    var body = { enabled: _up.enabled, auto_reboot: _up.auto_reboot, reboot_time: $('#up-time').value.trim() || '02:00' };
    var btn = $('#up-save'); btn.disabled = true;
    var r = await api('/api/security/updates', { method: 'PUT', body: JSON.stringify(body) });
    btn.disabled = false;
    toast(r.ok ? 'Applied' : (r.data && r.data.detail) || 'Save failed', r.ok ? 'ok' : 'err');
    if (r.ok) loadUpdates();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var rf = $('#refresh'); if (rf) rf.onclick = function () { loadJails(); loadUpdates(); toast('Refreshed', 'info'); };
    var fs = $('#f2b-save'); if (fs) fs.onclick = saveF2b;
    $('[data-sw="up-enabled"]').onclick = function () { setSw('enabled', !_up.enabled); };
    $('[data-sw="up-reboot"]').onclick = function () { setSw('auto_reboot', !_up.auto_reboot); $('#up-time-row').style.display = _up.auto_reboot ? '' : 'none'; };
    var us = $('#up-save'); if (us) us.onclick = saveUpdates;
    loadJails(); loadUpdates();
  });
})();
