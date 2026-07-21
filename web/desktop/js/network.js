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
  function renderInterfaces(list){
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
      + '</div>';
    }).join('');
  }

  // ── Global ──
  function renderGlobal(g){
    var body = $('global-body');
    if (!g){ body.innerHTML = '<div class="empty">Unavailable.</div>'; return; }
    var dns = (g.dns && g.dns.length) ? g.dns.join(', ') : '—';
    body.innerHTML = ''
      + row('Hostname', esc(g.hostname || '—'))
      + row('Domain', esc(g.domain || '—'))
      + row('DNS servers', '<span class="mono">' + esc(dns) + '</span>')
      + row('Default gateway', '<span class="mono">' + esc(g.gateway || '—') + '</span>')
      + row('HTTP proxy', esc(g.proxy || '—'));
  }
  function row(label, valHtml){
    return '<div class="frow"><label>' + label + '</label><div class="kvval">' + valHtml + '</div></div>';
  }

  // ── DDNS ──
  function renderDdns(d){
    var body = $('ddns-body'), chip = $('ddns-chip');
    if (!d || !d.configured){
      chip.textContent = 'Not configured';
      chip.className = 'chip';
      body.innerHTML = '<div class="empty">No dynamic DNS provider configured yet. This is where you\u2019ll point a hostname (e.g. nas.example.com) at this server and keep it updated as your public IP changes.</div>';
      return;
    }
    chip.textContent = 'Configured';
    chip.className = 'chip ok';
    body.innerHTML = ''
      + row('Provider', esc(d.provider || '—'))
      + row('Hostname', '<span class="mono">' + esc(d.hostname || '—') + '</span>')
      + row('Last IP', '<span class="mono">' + esc(d.last_ip || '—') + '</span>')
      + row('Last update', esc(d.last_update || '—'));
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

  function init(){
    var rb = $('refresh');
    if (rb) rb.addEventListener('click', function(){ loadAll(); toast('Refreshed', 'ok'); });
    loadAll();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
