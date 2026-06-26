/* ForgeOS — Reverse Proxy page.
 *
 * Mirrors shares.js: same $ / api / esc / toast helpers and the same modal-back
 * "wizard" pattern. Talks to /api/nginx/* — vhost CRUD (config-DB backed), the
 * ACME DNS-01 provider, cert issuance (HTTP-01 / DNS-01), and raw nginx.conf.
 * Every per-host option is a plain control — no "advanced" toggle. The
 * forgeos-ui host is protected: its delete is disabled (the API also refuses).
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

  var UI_VHOST = 'forgeos-ui';
  var EDIT_SVG = '<svg class="ico" viewBox="0 0 24 24"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M13.5 6.5l3 3"/></svg>';
  var DEL_SVG = '<svg class="ico" viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
  var GLOBE_SVG = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"/></svg>';

  var _vhosts = [];

  // ── vhost list ──
  async function loadVhosts() {
    var d = (await api('/api/nginx/vhosts')).data;
    var box = $('#vhosts');
    if (!d) { box.innerHTML = '<p style="color:var(--muted)">Could not read hosts.</p>'; $('#vhost-chip').textContent = '\u2014'; return; }
    _vhosts = d.vhosts || [];
    $('#vhost-chip').textContent = _vhosts.length + ' host' + (_vhosts.length !== 1 ? 's' : '');
    if (!_vhosts.length) { box.innerHTML = '<p style="color:var(--muted)">No hosts yet. Tap <b>New Vhost</b> to route a domain to a service.</p>'; return; }
    box.innerHTML = _vhosts.map(function (v) {
      var prot = v.name === UI_VHOST;
      var tags = '<span class="tag type">' + esc(v.upstream_scheme || 'http') + '</span>' +
        '<span class="tag ' + (v.force_ssl ? 'rw' : 'ro') + '">' + (v.force_ssl ? 'HTTPS' : 'HTTP') + '</span>' +
        (v.websocket ? '<span class="tag vis">WebSocket</span>' : '') +
        (v.block_common_exploits ? '<span class="tag vis">Exploit-block</span>' : '') +
        ((v.allow_ips && v.allow_ips.length) ? '<span class="tag gst">IP-allow</span>' : '') +
        (prot ? '<span class="tag gst">System</span>' : '');
      var up = esc((v.upstream_host || '127.0.0.1') + ':' + v.upstream_port);
      var del = prot
        ? '<button class="share-del" disabled title="The ForgeOS UI host cannot be removed" style="opacity:.35;cursor:not-allowed">' + DEL_SVG + '</button>'
        : '<button class="share-del" data-del="' + esc(v.name) + '" title="Delete host">' + DEL_SVG + '</button>';
      return '<div class="share-row">' +
        '<div class="share-ico">' + GLOBE_SVG + '</div>' +
        '<div><div class="share-name">' + esc(v.domain) + '</div><div class="share-path">' + esc(v.name) + ' &rarr; ' + up + '</div></div>' +
        '<div class="share-tags">' + tags + '</div>' +
        '<button class="share-edit" data-edit="' + esc(v.name) + '" title="Edit host">' + EDIT_SVG + '</button>' +
        del + '</div>';
    }).join('');
    $$('[data-edit]').forEach(function (b) { b.onclick = function () { var v = _vhosts.filter(function (x) { return x.name === b.getAttribute('data-edit'); })[0]; if (v) vhostModal(v); }; });
    $$('[data-del]').forEach(function (b) { b.onclick = function () { delVhost(b.getAttribute('data-del')); }; });
  }

  async function delVhost(name) {
    if (!confirm('Delete proxy host "' + name + '"?\n\nThe upstream service is not affected — only the nginx route is removed.')) return;
    var r = await api('/api/nginx/vhost/' + encodeURIComponent(name), { method: 'DELETE' });
    toast(r.ok ? 'Host removed' : (r.data && r.data.detail) || 'Could not remove host', r.ok ? 'ok' : 'err');
    if (r.ok) loadVhosts();
  }

  // ── New / Edit vhost modal ──
  function optRow(k, title, desc) {
    return '<div class="opt-row"><div class="opt-text"><h5>' + title + '</h5><p>' + desc + '</p></div><div class="switch" data-sw="' + k + '"><i></i></div></div>';
  }
  function vhostModal(existing) {
    var ed = existing || null;
    var st = { upstream_scheme: 'http', websocket: false, force_ssl: true, hsts: true, http2: true, block_common_exploits: false, gzip: false };
    var back = document.createElement('div'); back.className = 'modal-back';
    back.innerHTML = '<div class="modal share-modal"><h3>' + (ed ? 'Edit host' : 'New host') + '</h3>' +
      '<p class="sub">' + (ed ? 'Change this host. Saving regenerates &amp; reloads nginx.' : 'Forward a domain to a service on your network. Everything has a safe default.') + '</p>' +
      '<div class="fld"><label>Domain</label><input class="wz-input" id="v-domain" placeholder="app.example.com" autocomplete="off"><div class="hint">The hostname nginx answers on (<code>server_name</code>). Wildcards allowed.</div></div>' +
      '<div class="fld"><label>Host name</label><input class="wz-input" id="v-name" placeholder="app" autocomplete="off"><div class="hint">Internal id / filename. Letters, numbers, - and _; no spaces.</div></div>' +
      '<div class="fld"><label>Upstream</label><div class="wz-from"><input class="wz-input" id="v-uhost" placeholder="127.0.0.1"><input class="wz-input" id="v-uport" type="number" min="1" max="65535" placeholder="8080" style="max-width:150px"></div><div class="hint">Where to forward requests (host + port).</div></div>' +
      '<div class="fld"><label>Upstream scheme</label><div class="seg" id="scheme"><button data-s="http">http</button><button data-s="https">https</button></div></div>' +
      '<div class="fld"><label>Options</label>' +
        optRow('force_ssl', 'Force HTTPS', 'Redirect :80 to :443. Off also serves plain :80.') +
        optRow('hsts', 'HSTS', 'Send a Strict-Transport-Security header.') +
        optRow('http2', 'HTTP/2', 'Enable HTTP/2 on the TLS listener.') +
        optRow('websocket', 'WebSocket', 'Pass Upgrade / Connection headers for WS upstreams.') +
        optRow('block_common_exploits', 'Block common exploits', 'Deny obvious malicious request patterns.') +
        optRow('gzip', 'gzip', 'Compress proxied responses.') +
      '</div>' +
      '<div class="fld"><label>Max body size</label><input class="wz-input" id="v-body" placeholder="1m" style="max-width:170px"><div class="hint"><code>client_max_body_size</code> &mdash; e.g. 1m, 50m, or 0 for unlimited.</div></div>' +
      '<div class="fld"><label>Proxy read timeout (seconds)</label><input class="wz-input" id="v-timeout" type="number" min="1" placeholder="60" style="max-width:170px"></div>' +
      '<div class="fld"><label>Allow IPs (optional)</label><input class="wz-input" id="v-allow" placeholder="10.0.0.0/24 192.168.1.5" autocomplete="off"><div class="hint">If set, ONLY these IPs / CIDRs may connect. Space-separated.</div></div>' +
      '<div class="fld"><label>Deny IPs (optional)</label><input class="wz-input" id="v-deny" placeholder="203.0.113.0/24" autocomplete="off"><div class="hint">Blocklist. Ignored when an allow-list is set above.</div></div>' +
      '<div class="fld"><label>Custom snippet (optional)</label><textarea id="v-snip" class="raw-conf" style="min-height:80px" spellcheck="false" placeholder="# raw nginx, inside server { }"></textarea><div class="hint">Advanced escape hatch &mdash; raw nginx inside the server block.</div></div>' +
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go disabled style="opacity:.5">' + (ed ? 'Save changes' : 'Create host') + '</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var go = $('[data-go]', back);

    function setSw(k, on) { st[k] = !!on; var el = $('[data-sw="' + k + '"]', back); if (el) el.className = 'switch' + (on ? ' on' : ''); }
    $$('[data-sw]', back).forEach(function (el) { el.onclick = function () { var k = el.getAttribute('data-sw'); setSw(k, !st[k]); }; });
    function selScheme(s) { st.upstream_scheme = s; $$('#scheme button', back).forEach(function (b) { b.className = b.getAttribute('data-s') === s ? 'sel pri' : ''; }); }
    $$('#scheme button', back).forEach(function (b) { b.onclick = function () { selScheme(b.getAttribute('data-s')); }; });

    function update() {
      var name = $('#v-name', back).value.trim(), dom = $('#v-domain', back).value.trim(), port = $('#v-uport', back).value.trim();
      var ok = /^[A-Za-z0-9_-]{1,80}$/.test(name) && dom.length > 0 && /^[0-9]+$/.test(port);
      go.disabled = !ok; go.style.opacity = ok ? 1 : .5;
    }
    $$('#v-name,#v-domain,#v-uport', back).forEach(function (i) { i.oninput = update; });

    // defaults
    selScheme('http'); setSw('force_ssl', true); setSw('hsts', true); setSw('http2', true);
    setSw('websocket', false); setSw('block_common_exploits', false); setSw('gzip', false);

    if (ed) {
      $('#v-domain', back).value = ed.domain || '';
      $('#v-name', back).value = ed.name || ''; $('#v-name', back).disabled = true;  // name is the key
      $('#v-uhost', back).value = ed.upstream_host || '127.0.0.1';
      $('#v-uport', back).value = ed.upstream_port || '';
      $('#v-body', back).value = ed.client_max_body_size || '';
      $('#v-timeout', back).value = ed.proxy_read_timeout || '';
      $('#v-allow', back).value = (ed.allow_ips || []).join(' ');
      $('#v-deny', back).value = (ed.deny_ips || []).join(' ');
      $('#v-snip', back).value = ed.custom_snippet || '';
      selScheme(ed.upstream_scheme || 'http');
      setSw('force_ssl', ed.force_ssl !== false); setSw('hsts', ed.hsts !== false);
      setSw('http2', ed.http2 !== false); setSw('websocket', !!ed.websocket);
      setSw('block_common_exploits', !!ed.block_common_exploits); setSw('gzip', !!ed.gzip);
      update();
    }

    var close = function () { back.remove(); };
    back.addEventListener('click', function (e) { if (e.target === back || e.target.hasAttribute('data-x')) close(); });
    go.onclick = async function () {
      var body = {
        name: $('#v-name', back).value.trim(),
        domain: $('#v-domain', back).value.trim(),
        upstream_host: $('#v-uhost', back).value.trim() || '127.0.0.1',
        upstream_port: parseInt($('#v-uport', back).value, 10),
        upstream_scheme: st.upstream_scheme,
        websocket: st.websocket, force_ssl: st.force_ssl, hsts: st.hsts, http2: st.http2,
        block_common_exploits: st.block_common_exploits, gzip: st.gzip,
        custom_snippet: $('#v-snip', back).value
      };
      var bsz = $('#v-body', back).value.trim(); if (bsz) body.client_max_body_size = bsz;
      var tmo = $('#v-timeout', back).value.trim(); if (tmo) body.proxy_read_timeout = parseInt(tmo, 10);
      var al = $('#v-allow', back).value.trim(); if (al) body.allow_ips = al.split(/\s+/);
      var dn = $('#v-deny', back).value.trim(); if (dn) body.deny_ips = dn.split(/\s+/);
      go.disabled = true; go.style.opacity = .5;
      var url = ed ? '/api/nginx/vhost/' + encodeURIComponent(ed.name) : '/api/nginx/vhost';
      var r = await api(url, { method: ed ? 'PUT' : 'POST', body: JSON.stringify(body) });
      toast(r.ok ? (ed ? 'Host updated' : 'Host created')
                 : (r.data && r.data.detail) || ('Could not ' + (ed ? 'update' : 'create') + ' host'),
            r.ok ? 'ok' : 'err');
      if (r.ok) { close(); loadVhosts(); } else { go.disabled = false; go.style.opacity = 1; }
    };
  }

  // ── ACME DNS-01 provider ──
  async function loadDns() {
    var d = (await api('/api/nginx/acme/dns')).data;
    var chip = $('#dns-chip');
    if (d && d.configured) { chip.textContent = (d.provider || '') + ' configured'; $('#dns-provider').value = d.provider || ''; }
    else { chip.textContent = 'no DNS provider'; }
  }
  async function saveDns() {
    var prov = $('#dns-provider').value.trim().toLowerCase();
    if (!prov) { toast('Enter a provider code', 'err'); return; }
    var creds = {};
    $('#dns-creds').value.split('\n').forEach(function (ln) {
      ln = ln.trim(); if (!ln || ln.charAt(0) === '#') return;
      var i = ln.indexOf('='); if (i < 0) return;
      var k = ln.slice(0, i).trim(); if (k) creds[k] = ln.slice(i + 1).trim();
    });
    if (!Object.keys(creds).length) { toast('Add at least one credential (KEY = value)', 'err'); return; }
    var btn = $('#dns-save'); btn.disabled = true;
    var r = await api('/api/nginx/acme/dns', { method: 'PUT', body: JSON.stringify({ provider: prov, credentials: creds }) });
    btn.disabled = false;
    toast(r.ok ? 'DNS provider saved' : (r.data && r.data.detail) || 'Could not save provider', r.ok ? 'ok' : 'err');
    if (r.ok) { $('#dns-creds').value = ''; loadDns(); }
  }
  async function clearDns() {
    if (!confirm('Remove the DNS provider credentials?')) return;
    var r = await api('/api/nginx/acme/dns', { method: 'DELETE' });
    toast(r.ok ? 'Provider removed' : 'Could not remove', r.ok ? 'ok' : 'err');
    if (r.ok) { $('#dns-provider').value = ''; $('#dns-creds').value = ''; loadDns(); }
  }

  // ── cert request ──
  var _certMode = 'http', _wild = false;
  function selCertMode(m) {
    _certMode = m;
    $$('#cert-mode button').forEach(function (b) { b.className = b.getAttribute('data-m') === m ? 'sel pri' : ''; });
    $('#cert-wild-row').style.display = m === 'dns' ? '' : 'none';
    $('#cert-mode-hint').innerHTML = m === 'dns'
      ? 'DNS-01 uses the provider above &mdash; works for wildcards and hosts not exposed on port 80.'
      : 'HTTP-01 validates over port 80 &mdash; the host must be reachable from the internet.';
  }
  async function certGo() {
    var domain = $('#cert-domain').value.trim(), email = $('#cert-email').value.trim();
    var out = $('#cert-out'); out.className = 'raw-err hidden';
    if (!domain) { toast('Enter a domain', 'err'); return; }
    var btn = $('#cert-go'); btn.disabled = true; toast('Requesting certificate\u2026 this can take a minute', 'info');
    var url, body;
    if (_certMode === 'dns') { url = '/api/nginx/cert/dns'; body = { domain: domain, email: email, wildcard: _wild }; }
    else { url = '/api/nginx/certbot'; body = { domain: domain, email: email }; }
    var r = await api(url, { method: 'POST', body: JSON.stringify(body) });
    btn.disabled = false;
    if (r.ok) { toast('Certificate issued for ' + domain, 'ok'); }
    else {
      var detail = r.data && r.data.detail;
      var msg = (detail && detail.output) || (typeof detail === 'string' ? detail : 'Certificate request failed');
      out.textContent = msg; out.className = 'raw-err';
      toast('Request failed \u2014 see details below', 'err');
    }
  }

  // ── raw nginx.conf ──
  async function loadRaw() {
    var ta = $('#raw-conf'); if (!ta) return;
    var d = (await api('/api/nginx/raw')).data;
    ta.value = (d && d.config) || '';
    $('#raw-err').className = 'raw-err hidden';
    $('#raw-state').textContent = ta.value.trim() ? 'loaded' : 'empty';
  }
  async function saveRaw() {
    var ta = $('#raw-conf'), err = $('#raw-err'), btn = $('#raw-save'); btn.disabled = true;
    var r = await api('/api/nginx/raw', { method: 'PUT', body: JSON.stringify({ config: ta.value }) });
    btn.disabled = false;
    if (r.ok) { err.className = 'raw-err hidden'; toast('Configuration saved & applied', 'ok'); }
    else {
      var detail = r.data && r.data.detail;
      var msg = (detail && detail.output) || (detail && detail.error) || (typeof detail === 'string' ? detail : 'Save failed');
      err.textContent = msg; err.className = 'raw-err'; toast('Config rejected \u2014 see details below', 'err');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var add = $('#add-vhost'); if (add) add.onclick = function () { vhostModal(null); };
    var rf = $('#refresh'); if (rf) rf.onclick = function () { loadVhosts(); loadDns(); toast('Refreshed', 'info'); };
    var ds = $('#dns-save'); if (ds) ds.onclick = saveDns;
    var dc = $('#dns-clear'); if (dc) dc.onclick = clearDns;
    $$('#cert-mode button').forEach(function (b) { b.onclick = function () { selCertMode(b.getAttribute('data-m')); }; });
    var cw = $('[data-sw="wildcard"]'); if (cw) cw.onclick = function () { _wild = !_wild; cw.className = 'switch' + (_wild ? ' on' : ''); };
    var cg = $('#cert-go'); if (cg) cg.onclick = certGo;
    var rr = $('#raw-reload'); if (rr) rr.onclick = function () { loadRaw(); toast('Reloaded', 'info'); };
    var rs = $('#raw-save'); if (rs) rs.onclick = saveRaw;
    selCertMode('http');
    loadVhosts(); loadDns(); loadRaw();
  });
})();
