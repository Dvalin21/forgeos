(function () {
  "use strict";

  function token(){ try { return localStorage.getItem('forgeos_token'); } catch(e){ return null; } }

  async function api(p, o){
    o = o || {};
    var h = Object.assign({}, o.headers || {});
    var t = token(); if (t) h.Authorization = 'Bearer ' + t;
    if (o.body && !h['Content-Type']) h['Content-Type'] = 'application/json';
    try {
      var r = await fetch(p, Object.assign({}, o, { headers: h }));
      var d = null; try { d = await r.json(); } catch(e){}
      return { ok: r.ok, status: r.status, data: d };
    } catch(e){ return { ok: false, status: 0, data: null }; }
  }

  function toast(msg, kind){
    var w = document.getElementById('toasts'); if (!w) return;
    var el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = msg;
    w.appendChild(el);
    setTimeout(function(){ el.remove(); }, 3200);
  }

  function esc(s){ var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function $(id){ return document.getElementById(id); }

  function fmtBytes(n){
    if (!n) return '0 B';
    var u = ['B','KB','MB','GB','TB'], i = 0;
    while (n >= 1024 && i < u.length - 1){ n /= 1024; i++; }
    return (n < 10 && i ? n.toFixed(1) : Math.round(n)) + ' ' + u[i];
  }

  // ── Interfaces ──
  var IFACES = [];

  function renderInterfaces(list){
    IFACES = list || [];
    var grid = $('if-grid');
    if (!list || !list.length){ grid.innerHTML = '<div class="empty">No interfaces detected.</div>'; return; }
    var up = list.filter(function(i){ return i.state === 'UP'; }).length;
    $('if-chip').textContent = list.length + ' adapter' + (list.length !== 1 ? 's' : '') + ' · ' + up + ' up';
    grid.innerHTML = list.map(function(i){
      var isUp = i.state === 'UP';
      var v4 = (i.ipv4 && i.ipv4.length) ? i.ipv4.join(', ') : '—';
      var v6 = (i.ipv6 && i.ipv6.length) ? i.ipv6.join(', ') : '';
      // dhcp vs static isn't knowable from the read layer alone; the badge
      // lands when the write layer records the method. Show link state honestly.
      return ''
      + '<div class="if-card"' + (isUp ? '' : ' style="opacity:.82"') + '>'
      +   '<div class="if-top">'
      +     '<div class="if-name"><span class="if-ico"' + (isUp ? '' : ' style="background:var(--surface-3);color:var(--muted)"') + '>'
      +       '<svg viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="10" rx="2"/><path d="M6 17v3M18 17v3M6 4v3M18 4v3"/></svg></span>'
      +       esc(i.name) + '</div>'
      +     '<span class="dot ' + (isUp ? 'up' : 'down') + '" title="' + (isUp ? 'Link up' : 'No link') + '"></span>'
      +   '</div>'
      +   '<dl class="kv">'
      +     '<dt>IPv4</dt><dd class="mono">' + esc(v4) + '</dd>'
      +     (v6 ? '<dt>IPv6</dt><dd class="mono">' + esc(v6) + '</dd>' : '')
      +     '<dt>MAC</dt><dd class="mono">' + esc(i.mac || '—') + '</dd>'
      +     '<dt>State</dt><dd>' + esc(i.state || '—') + '</dd>'
      +     '<dt>MTU</dt><dd>' + esc(String(i.mtu || '—')) + '</dd>'
      +   '</dl>'
      +   '<div class="mini-metric">'
      +     '<div><b>' + fmtBytes(i.rx_bytes) + '</b>received</div>'
      +     '<div><b>' + fmtBytes(i.tx_bytes) + '</b>sent</div>'
      +   '</div>'
      +   '<div class="if-foot">'
      +     '<span style="flex:1"></span>'
      +     '<button class="button ghost sm" data-cfg="' + esc(i.name) + '">Configure</button>'
      +   '</div>'
      + '</div>';
    }).join('');
  }

  // ── Global ──
  var GLOBAL = null;

  function renderGlobal(g){
    var body = $('global-body');
    if (!g){ body.innerHTML = '<div class="empty">Unavailable.</div>'; return; }
    GLOBAL = g;
    body.innerHTML = ''
      + inp('Hostname', 'g-host', g.hostname || '')
      + inp('Domain', 'g-domain', g.domain || '')
      + inp('DNS servers', 'g-dns', (g.dns || []).join(', '), '1.1.1.1, 9.9.9.9')
      + row('Default gateway', '<span class="kvval mono">' + esc(g.gateway || '—') + '</span>'
            + '<div class="hint" style="font-size:11.5px;color:var(--muted)">Set per interface</div>')
      + '<div class="err" id="g-err"></div>';
  }
  function inp(label, id, val, ph){
    return '<div class="frow"><label>' + label + '</label>'
      + '<input class="fi" id="' + id + '" value="' + esc(val) + '"'
      + (ph ? ' placeholder="' + esc(ph) + '"' : '') + '></div>';
  }

  function row(label, valHtml){
    return '<div class="frow"><label>' + label + '</label><div class="kvval">' + valHtml + '</div></div>';
  }

  // ── DDNS ──
  var DDNS = null;
  var STATUS_LABEL = { ok:'Synced', nochg:'Synced', fatal:'Error', retry:'Retrying', '':'Configured' };
  var STATUS_CHIP  = { ok:'chip ok', nochg:'chip ok', fatal:'chip warn', retry:'chip warn', '':'chip' };

  function renderDdns(d){
    DDNS = d;
    var body = $('ddns-body'), chip = $('ddns-chip');
    if (!d || !d.configured){
      chip.textContent = 'Not configured';
      chip.className = 'chip';
      body.innerHTML = '<div class="empty">No dynamic DNS provider configured yet — keep a hostname (e.g. nas.example.com) pointed at this server as your public IP changes.</div>'
        + '<div class="mfoot" style="padding:14px 0 0;border-top:1px solid var(--line);margin-top:6px">'
        + '<button class="btn-pri" id="ddns-setup" type="button">Set up</button></div>';
      return;
    }
    var st = d.last_status || '';
    chip.textContent = STATUS_LABEL[st] || 'Configured';
    chip.className = STATUS_CHIP[st] || 'chip';
    var msg = (st === 'fatal' || st === 'retry') && d.last_message
      ? '<div class="warnbox" style="margin-top:0 0 8px"><p>' + esc(d.last_message) + '</p></div>' : '';
    body.innerHTML = msg
      + row('Provider', esc(providerName(d.provider)))
      + row('Hostname', '<span class="kvval mono">' + esc(d.hostname || '—') + '</span>')
      + row('Last IP', '<span class="kvval mono">' + esc(d.last_ip || '—') + '</span>')
      + row('Last update', esc(d.last_update || 'never'))
      + row('Auto-update', d.enabled ? ('every ' + esc(String(d.interval_minutes)) + ' min') : 'off')
      + '<div class="mfoot" style="padding:14px 0 0;border-top:1px solid var(--line);margin-top:6px">'
      + '<button class="btn-ghost" id="ddns-remove" type="button">Remove</button>'
      + '<button class="btn-ghost" id="ddns-test" type="button">Test now</button>'
      + '<button class="btn-pri" id="ddns-edit" type="button">Edit</button></div>';
  }
  function providerName(p){
    return { cloudflare:'Cloudflare', noip:'No-IP', dyndns:'DynDNS',
             duckdns:'DuckDNS', custom:'Custom' }[p] || p || '—';
  }

  // ── Routes ──
  function renderRoutes(list){
    var body = $('rt-body');
    if (!list || !list.length){ body.innerHTML = '<div class="empty">No routes found.</div>'; return; }
    $('rt-chip').textContent = list.length + ' route' + (list.length !== 1 ? 's' : '');
    var rows = list.map(function(r){
      var dest = r.destination || 'default';
      return '<tr>'
      +   '<td class="mono">' + esc(dest) + '</td>'
      +   '<td class="mono">' + esc(r.gateway || '—') + '</td>'
      +   '<td>' + (r.interface ? '<span class="tag">' + esc(r.interface) + '</span>' : '—') + '</td>'
      +   '<td>' + esc(String(r.metric || 0)) + '</td>'
      +   '<td>' + (r.protocol ? '<span class="muted">' + esc(r.protocol) + '</span>' : '') + '</td>'
      + '</tr>';
    }).join('');
    body.innerHTML = '<table class="rt"><thead><tr>'
      + '<th>Destination</th><th>Gateway</th><th>Interface</th><th>Metric</th><th>Source</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  async function loadAll(){
    var status = $('net-status');
    var res = await Promise.all([
      api('/api/net/interfaces'),
      api('/api/net/global'),
      api('/api/net/ddns'),
      api('/api/net/routes')
    ]);
    var ifaces = res[0], glob = res[1], ddns = res[2], routes = res[3];

    if (ifaces.ok && ifaces.data){ renderInterfaces(ifaces.data.interfaces || []); }
    else { $('if-grid').innerHTML = '<div class="empty">Failed to load interfaces.</div>'; }

    if (glob.ok && glob.data){ renderGlobal(glob.data); } else { $('global-body').innerHTML = '<div class="empty">Failed to load.</div>'; }
    if (ddns.ok && ddns.data){ renderDdns(ddns.data); } else { $('ddns-body').innerHTML = '<div class="empty">Failed to load.</div>'; }
    if (routes.ok && routes.data){ renderRoutes(routes.data.routes || []); } else { $('rt-body').innerHTML = '<div class="empty">Failed to load routes.</div>'; }

    // top-of-page reachability chip: green if we have a default gateway
    if (glob.ok && glob.data && glob.data.gateway){
      status.textContent = 'Gateway ' + glob.data.gateway;
      status.className = 'chip ok';
    } else {
      status.textContent = 'No default gateway';
      status.className = 'chip warn';
    }
  }


  // ── interface configuration modal ──
  var editing = null;          // name of the interface being configured

  function show(id, on){ var e=$(id); if(e) e.classList[on?'add':'remove']('show'); }

  function methodOf(){
    var r = document.querySelector('input[name="ifm-method"]:checked');
    return r ? r.value : 'dhcp';
  }
  function syncMethodUI(){
    var m = methodOf();
    $('static-fields').style.display = (m === 'static') ? '' : 'none';
    $('lbl-dhcp').classList.toggle('on', m === 'dhcp');
    $('lbl-static').classList.toggle('on', m === 'static');
  }

  function openConfig(name){
    var i = IFACES.filter(function(x){ return x.name === name; })[0];
    if (!i) return;
    editing = name;
    $('ifm-title').textContent = 'Configure ' + name;
    $('ifm-sub').textContent = i.mac ? ('MAC ' + i.mac) : '';
    $('ifm-err').textContent = '';
    // The read layer can't tell dhcp from static, so don't pretend: default to
    // static prefilled with what the link currently has.
    var addr = (i.ipv4 && i.ipv4[0]) || '';
    document.querySelector('input[name="ifm-method"][value="static"]').checked = true;
    $('ifm-address').value = addr;
    $('ifm-gateway').value = (GLOBAL && GLOBAL.gateway) || '';
    $('ifm-dns').value = (GLOBAL && (GLOBAL.dns || []).join(', ')) || '';
    $('ifm-mtu').value = i.mtu || 1500;
    syncMethodUI();
    show('if-modal', true);
  }

  function splitList(v){
    return (v || '').split(',').map(function(x){ return x.trim(); }).filter(Boolean);
  }

  async function applyInterface(){
    if (!editing) return;
    var m = methodOf();
    var body = { name: editing, method: m, dns: splitList($('ifm-dns').value),
                 mtu: parseInt($('ifm-mtu').value, 10) || 1500 };
    if (m === 'static'){
      body.address = $('ifm-address').value.trim();
      body.gateway = $('ifm-gateway').value.trim();
    }
    var before = currentAddrOf(editing);
    $('ifm-apply').disabled = true;
    var r = await api('/api/net/interface/' + encodeURIComponent(editing),
                      { method: 'PUT', body: JSON.stringify(body) });
    $('ifm-apply').disabled = false;
    if (!r.ok){
      $('ifm-err').textContent = detail(r) || 'Could not apply these settings.';
      return;
    }
    show('if-modal', false);
    // a moved address means this origin is about to stop answering
    var moved = (m === 'static' && body.address && body.address !== before);
    openConfirm(r.data, moved ? body.address : null);
  }

  function currentAddrOf(name){
    var i = IFACES.filter(function(x){ return x.name === name; })[0];
    return (i && i.ipv4 && i.ipv4[0]) || '';
  }
  function detail(r){
    return (r.data && (r.data.detail || r.data.message)) || '';
  }

  // ── confirm countdown ──
  var pendingToken = null, ticker = null;

  function openConfirm(info, movedTo){
    pendingToken = (info && info.token) || null;
    $('cf-sub').textContent = (info && info.label) || '';
    $('cf-err').textContent = '';
    var link = $('cf-newaddr');
    if (movedTo){
      var host = movedTo.split('/')[0];
      link.href = location.protocol + '//' + host + '/network.html';
      link.textContent = link.href;
      link.style.display = '';
      $('cf-move').style.display = '';
    } else {
      link.style.display = 'none';
      $('cf-move').style.display = 'none';
    }
    show('cf-modal', true);
    startTicker(info && info.window_seconds);
  }

  function startTicker(secs){
    stopTicker();
    var left = typeof secs === 'number' ? secs : 120;
    var el = $('cf-count');
    function paint(){
      el.textContent = left + 's';
      el.classList.toggle('low', left <= 20);
    }
    paint();
    ticker = setInterval(function(){
      left -= 1;
      if (left <= 0){
        stopTicker();
        show('cf-modal', false);
        toast('Change rolled back — not confirmed in time', 'warn');
        loadAll();
        return;
      }
      paint();
    }, 1000);
  }
  function stopTicker(){ if (ticker){ clearInterval(ticker); ticker = null; } }

  async function keepSettings(){
    if (!pendingToken){ $('cf-err').textContent = 'No pending change to confirm.'; return; }
    $('cf-keep').disabled = true;
    var r = await api('/api/net/confirm', { method: 'POST',
                                            body: JSON.stringify({ token: pendingToken }) });
    $('cf-keep').disabled = false;
    if (!r.ok){ $('cf-err').textContent = detail(r) || 'Could not confirm.'; return; }
    stopTicker(); show('cf-modal', false); pendingToken = null;
    toast('Network settings kept', 'ok');
    loadAll();
  }

  async function revertNow(){
    $('cf-revert').disabled = true;
    var r = await api('/api/net/cancel', { method: 'POST' });
    $('cf-revert').disabled = false;
    if (!r.ok){ $('cf-err').textContent = detail(r) || 'Could not revert.'; return; }
    stopTicker(); show('cf-modal', false); pendingToken = null;
    toast('Reverted to the previous settings', 'ok');
    loadAll();
  }

  // Picks up a change applied from ANOTHER origin (the box moved, the admin
  // reconnected here and signed in) — without this the confirm is unreachable.
  async function resumePending(){
    var r = await api('/api/net/pending');
    if (r.ok && r.data && r.data.pending){
      openConfirm({ token: r.data.token, label: r.data.label,
                    window_seconds: r.data.seconds_remaining }, null);
    }
  }

  // ── DDNS configuration modal ──
  function ddnsSyncProvider(){
    var prov = $('dm-provider').value;
    document.querySelectorAll('[data-prov]').forEach(function(el){
      var provs = el.getAttribute('data-prov').split(' ');
      el.style.display = (provs.indexOf(prov) >= 0) ? '' : 'none';
    });
    var note = $('dm-creds-note');
    if (note){
      note.textContent = (DDNS && DDNS.has_credentials)
        ? 'Credentials are stored. Leave the fields blank to keep them.'
        : '';
    }
  }
  function ddnsSyncEnabled(){
    $('dm-interval-row').style.display = $('dm-enabled').checked ? '' : 'none';
  }

  function openDdns(){
    var d = DDNS || {};
    $('dm-provider').value = d.provider || 'cloudflare';
    $('dm-hostname').value = d.hostname || '';
    $('dm-enabled').checked = d.enabled !== false;
    $('dm-interval').value = String(d.interval_minutes || 5);
    // never prefilled — the server won't return them
    ['dm-cf-token','dm-cf-zone','dm-user','dm-pass','dm-duck-token','dm-url'].forEach(function(id){
      var e = $(id); if (e) e.value = '';
    });
    $('dm-err').textContent = '';
    ddnsSyncProvider(); ddnsSyncEnabled();
    show('ddns-modal', true);
  }

  function collectCreds(prov){
    var c = {};
    if (prov === 'cloudflare'){
      if ($('dm-cf-token').value) c.token = $('dm-cf-token').value;
      if ($('dm-cf-zone').value)  c.zone  = $('dm-cf-zone').value.trim();
    } else if (prov === 'noip' || prov === 'dyndns'){
      if ($('dm-user').value) c.username = $('dm-user').value;
      if ($('dm-pass').value) c.password = $('dm-pass').value;
    } else if (prov === 'duckdns'){
      if ($('dm-duck-token').value) c.token = $('dm-duck-token').value;
    } else if (prov === 'custom'){
      if ($('dm-url').value) c.url = $('dm-url').value.trim();
    }
    return c;
  }

  async function saveDdns(){
    var prov = $('dm-provider').value;
    var body = { provider: prov, hostname: $('dm-hostname').value.trim(),
                 enabled: $('dm-enabled').checked,
                 interval_minutes: parseInt($('dm-interval').value, 10) || 5 };
    var creds = collectCreds(prov);
    // Only send credentials if the user typed some — omitting them keeps the
    // stored ones. But a brand-new config with none is a mistake worth catching
    // client-side rather than saving an unusable provider.
    if (Object.keys(creds).length) body.credentials = creds;
    else if (!(DDNS && DDNS.has_credentials)){
      $('dm-err').textContent = 'Enter the credentials for this provider.';
      return;
    }
    $('dm-save').disabled = true;
    var r = await api('/api/net/ddns', { method: 'PUT', body: JSON.stringify(body) });
    $('dm-save').disabled = false;
    if (!r.ok){ $('dm-err').textContent = detail(r) || 'Could not save.'; return; }
    show('ddns-modal', false);
    toast('Dynamic DNS saved', 'ok');
    await loadAll();
  }

  async function testDdns(){
    toast('Testing…', '');
    var r = await api('/api/net/ddns/test', { method: 'POST' });
    if (!r.ok){ toast(detail(r) || 'Test failed', 'warn'); loadAll(); return; }
    var d = r.data || {};
    toast(d.success ? ('DDNS OK — ' + (d.ip || '')) : ('DDNS: ' + (d.message || d.status)),
          d.success ? 'ok' : 'warn');
    loadAll();
  }

  async function removeDdns(){
    var r = await api('/api/net/ddns', { method: 'DELETE' });
    if (!r.ok){ toast(detail(r) || 'Could not remove', 'warn'); return; }
    toast('Dynamic DNS removed', 'ok');
    loadAll();
  }

  // ── global settings ──
  async function applyGlobal(){
    var err = $('g-err'); if (err) err.textContent = '';
    var body = { hostname: ($('g-host') || {}).value || '',
                 domain: ($('g-domain') || {}).value || '',
                 dns: splitList(($('g-dns') || {}).value) };
    $('g-apply').disabled = true;
    var r = await api('/api/net/global', { method: 'PUT', body: JSON.stringify(body) });
    $('g-apply').disabled = false;
    if (!r.ok){
      if (err) err.textContent = detail(r) || 'Could not apply these settings.';
      return;
    }
    toast('Global settings applied', 'ok');
    loadAll();
  }

  function init(){
    var rb = $('refresh');
    if (rb) rb.addEventListener('click', function(){ loadAll(); toast('Refreshed', 'ok'); });

    document.addEventListener('click', function(e){
      var b = e.target.closest ? e.target.closest('[data-cfg]') : null;
      if (b) openConfig(b.getAttribute('data-cfg'));
    });
    document.querySelectorAll('input[name="ifm-method"]').forEach(function(r){
      r.addEventListener('change', syncMethodUI);
    });
    $('ifm-cancel').addEventListener('click', function(){ show('if-modal', false); });
    $('ifm-apply').addEventListener('click', applyInterface);
    $('cf-keep').addEventListener('click', keepSettings);
    $('cf-revert').addEventListener('click', revertNow);
    document.addEventListener('click', function(e){
      if (e.target.id === 'g-apply') applyGlobal();
      if (e.target.id === 'g-reset') loadAll();
      if (e.target.id === 'ddns-setup' || e.target.id === 'ddns-edit') openDdns();
      if (e.target.id === 'ddns-test') testDdns();
      if (e.target.id === 'ddns-remove') removeDdns();
    });
    $('dm-provider').addEventListener('change', ddnsSyncProvider);
    $('dm-enabled').addEventListener('change', ddnsSyncEnabled);
    $('dm-cancel').addEventListener('click', function(){ show('ddns-modal', false); });
    $('dm-save').addEventListener('click', saveDdns);

    loadAll().then(resumePending);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
