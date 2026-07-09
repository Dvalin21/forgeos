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
      var tags = '<span class="tag ' + (v.cert === 'letsencrypt' ? 'rw' : 'ro') + '">' + (v.cert === 'letsencrypt' ? 'LE cert' : 'self-signed') + '</span>' +
        '<span class="tag type">' + esc(v.upstream_scheme || 'http') + '</span>' +
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
      '<div class="fld"><label>Certificate</label><div class="seg" id="v-cert"><button data-c="local">Self-signed</button><button data-c="existing">Select certificate</button></div>' +
        '<div class="hint" id="v-cert-hint"></div></div>' +
      '<div class="fld" id="v-cert-pick-row" style="display:none"><label>Certificate</label>' +
        '<select class="wz-input" id="v-cert-pick"></select>' +
        '<div class="hint" id="v-cert-pick-hint">Pick a certificate from the Certificates list. Issue one there first (wildcards cover every subdomain).</div></div>' +
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go disabled style="opacity:.5">' + (ed ? 'Save changes' : 'Create host') + '</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var go = $('[data-go]', back);

    function setSw(k, on) { st[k] = !!on; var el = $('[data-sw="' + k + '"]', back); if (el) el.className = 'switch' + (on ? ' on' : ''); }
    $$('[data-sw]', back).forEach(function (el) { el.onclick = function () { var k = el.getAttribute('data-sw'); setSw(k, !st[k]); }; });
    function selScheme(s) { st.upstream_scheme = s; $$('#scheme button', back).forEach(function (b) { b.className = b.getAttribute('data-s') === s ? 'sel pri' : ''; }); }
    $$('#scheme button', back).forEach(function (b) { b.onclick = function () { selScheme(b.getAttribute('data-s')); }; });

    // ── certificate: self-signed, or select one from the Certificates list ──
    st.cert = 'local';
    function certCovers(covers, dom) {
      return (covers || []).some(function (n) {
        if (n === dom) return true;
        if (n.indexOf('*.') === 0) {
          var suffix = n.slice(1);
          var host = dom.slice(0, dom.length - suffix.length);
          return dom.slice(-suffix.length) === suffix && host && host.indexOf('.') < 0;
        }
        return false;
      });
    }
    function selCert(c) {
      var dom = $('#v-domain', back).value.trim().replace(/^\*\./, '');
      var hint = $('#v-cert-hint', back);
      if (c === 'existing' && !_certs.length) {
        hint.textContent = 'No certificates yet \u2014 issue or register one in the Certificates section, then select it here.';
        c = 'local';
      } else {
        hint.textContent = c === 'local'
          ? 'ForgeOS self-signed cert \u2014 fine on your LAN, browsers warn once.'
          : 'Uses a certificate from the Certificates list. Pick one that covers this hostname.';
      }
      st.cert = c;
      $$('#v-cert button', back).forEach(function (b) { b.className = b.getAttribute('data-c') === c ? 'sel pri' : ''; });
      $('#v-cert-pick-row', back).style.display = c === 'existing' ? '' : 'none';
      if (c === 'existing') fillCertPick(dom);
    }
    function fillCertPick(dom) {
      var sel = $('#v-cert-pick', back), h = $('#v-cert-pick-hint', back);
      sel.innerHTML = _certs.map(function (crt) {
        var ok = certCovers(crt.covers, dom);
        return '<option value="' + esc(crt.name) + '">' +
          esc(crt.name) + (crt.covers && crt.covers.length ? ' \u2014 covers ' + esc(crt.covers.join(', ')) : '') +
          (ok ? '' : '  (does NOT cover ' + esc(dom) + ')') + '</option>';
      }).join('');
      var match = _certs.filter(function (crt) { return certCovers(crt.covers, dom); })[0];
      if (match) { sel.value = match.name; h.textContent = 'This certificate covers ' + dom + '.'; h.style.color = ''; }
      else { h.textContent = 'Warning: no listed certificate covers ' + dom + '.'; h.style.color = 'var(--danger)'; }
    }
    $('#v-cert-pick', back) && ($('#v-cert-pick', back).onchange = function () {
      var dom = $('#v-domain', back).value.trim().replace(/^\*\./, '');
      var opt = this.options[this.selectedIndex], h = $('#v-cert-pick-hint', back);
      var nomatch = opt && opt.textContent.indexOf('does NOT cover') >= 0;
      if (nomatch) { h.textContent = 'This certificate does NOT cover ' + dom + '.'; h.style.color = 'var(--danger)'; }
      else { h.textContent = 'This certificate covers ' + dom + '.'; h.style.color = ''; }
    });
    $$('#v-cert button', back).forEach(function (b) { b.onclick = function () { selCert(b.getAttribute('data-c')); }; });
    $('#v-domain', back).addEventListener('input', function () { if (st.cert === 'existing') fillCertPick($('#v-domain', back).value.trim().replace(/^\*\./, '')); });

    function update() {
      var name = $('#v-name', back).value.trim(), dom = $('#v-domain', back).value.trim(), port = $('#v-uport', back).value.trim();
      var ok = /^[A-Za-z0-9_-]{1,80}$/.test(name) && dom.length > 0 && /^[0-9]+$/.test(port);
      go.disabled = !ok; go.style.opacity = ok ? 1 : .5;
    }
    $$('#v-name,#v-domain,#v-uport', back).forEach(function (i) { i.oninput = update; });

    // defaults
    selScheme('http'); setSw('force_ssl', true); setSw('hsts', true); setSw('http2', true);
    setSw('websocket', false); setSw('block_common_exploits', false); setSw('gzip', false);
    selCert('local');

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
      if (ed.cert_name) {
        selCert('existing');
        var ps = $('#v-cert-pick', back); if (ps) ps.value = ed.cert_name;
      } else if (ed.cert === 'letsencrypt') {
        $('#v-cert-hint', back).textContent = 'This host already has a Let\u2019s Encrypt certificate.';
      }
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
        custom_snippet: $('#v-snip', back).value,
        cert_name: st.cert === 'existing' ? ($('#v-cert-pick', back).value || '') : ''
      };
      var bsz = $('#v-body', back).value.trim(); if (bsz) body.client_max_body_size = bsz;
      var tmo = $('#v-timeout', back).value.trim(); if (tmo) body.proxy_read_timeout = parseInt(tmo, 10);
      var al = $('#v-allow', back).value.trim(); if (al) body.allow_ips = al.split(/\s+/);
      var dn = $('#v-deny', back).value.trim(); if (dn) body.deny_ips = dn.split(/\s+/);
      go.disabled = true; go.style.opacity = .5;
      var url = ed ? '/api/nginx/vhost/' + encodeURIComponent(ed.name) : '/api/nginx/vhost';
      var r = await api(url, { method: ed ? 'PUT' : 'POST', body: JSON.stringify(body) });
      if (!r.ok) {
        toast((r.data && r.data.detail) || ('Could not ' + (ed ? 'update' : 'create') + ' host'), 'err');
        go.disabled = false; go.style.opacity = 1; return;
      }
      toast(ed ? 'Host updated' : 'Host created', 'ok');
      close(); loadVhosts();
      // Cert selection is just config now (issuance lives in the Certificates
      // section). Re-render so the generator picks the selected cert file.
      if (st.cert === 'existing') { await api('/api/nginx/apply', { method: 'POST' }); loadVhosts(); }
    };
  }


  // ── ACME DNS-01 provider ──
  // Credential env keys VERIFIED against lego's provider definitions
  // (go-acme/lego providers/dns/<code>/<code>.toml) — wrong key names fail
  // auth silently, so these are source-checked, not remembered.
  var PROVIDERS = {
    cloudflare:   { title: "Cloudflare", fields: [
      { k: "CLOUDFLARE_DNS_API_TOKEN", label: "API token", secret: true,
        hint: "Create a token with Zone:Read + DNS:Edit (not the Global API Key)." }]},
    porkbun:      { title: "Porkbun", fields: [
      { k: "PORKBUN_API_KEY", label: "API key", secret: true },
      { k: "PORKBUN_SECRET_API_KEY", label: "Secret API key", secret: true,
        hint: "Enable API access per-domain in Porkbun's domain settings." }]},
    duckdns:      { title: "DuckDNS", fields: [
      { k: "DUCKDNS_TOKEN", label: "Account token", secret: true }]},
    desec:        { title: "deSEC", fields: [
      { k: "DESEC_TOKEN", label: "Domain token", secret: true }]},
    gandiv5:      { title: "Gandi (v5)", fields: [
      { k: "GANDIV5_PERSONAL_ACCESS_TOKEN", label: "Personal access token", secret: true,
        hint: "The old GANDIV5_API_KEY is deprecated — use a Personal Access Token." }]},
    namecheap:    { title: "Namecheap", fields: [
      { k: "NAMECHEAP_API_USER", label: "API user" },
      { k: "NAMECHEAP_API_KEY", label: "API key", secret: true,
        hint: "Namecheap requires whitelisting this server's public IP in their API settings." }]},
    godaddy:      { title: "GoDaddy", fields: [
      { k: "GODADDY_API_KEY", label: "API key", secret: true },
      { k: "GODADDY_API_SECRET", label: "API secret", secret: true }]},
    route53:      { title: "AWS Route 53", fields: [
      { k: "AWS_ACCESS_KEY_ID", label: "Access key ID" },
      { k: "AWS_SECRET_ACCESS_KEY", label: "Secret access key", secret: true },
      { k: "AWS_REGION", label: "Region", hint: "e.g. us-east-1" }]},
    digitalocean: { title: "DigitalOcean", fields: [
      { k: "DO_AUTH_TOKEN", label: "API token", secret: true }]},
    hetzner:      { title: "Hetzner DNS", fields: [
      { k: "HETZNER_API_TOKEN", label: "API token", secret: true }]},
    dynu:         { title: "Dynu", fields: [
      { k: "DYNU_API_KEY", label: "API key", secret: true }]},
    ovh:          { title: "OVH", fields: [
      { k: "OVH_ENDPOINT", label: "Endpoint", hint: "ovh-eu or ovh-ca" },
      { k: "OVH_APPLICATION_KEY", label: "Application key" },
      { k: "OVH_APPLICATION_SECRET", label: "Application secret", secret: true },
      { k: "OVH_CONSUMER_KEY", label: "Consumer key", secret: true }]}
  };

  function renderProviderSelect() {
    var sel = $('#dns-select');
    var opts = ['<option value="">— choose provider —</option>'];
    Object.keys(PROVIDERS).forEach(function (code) {
      opts.push('<option value="' + code + '">' + PROVIDERS[code].title + '</option>');
    });
    opts.push('<option value="__other">Other (lego code)…</option>');
    sel.innerHTML = opts.join('');
  }
  function renderFields(code) {
    var box = $('#dns-fields'), manual = $('#dns-creds'), provInput = $('#dns-provider');
    var isOther = code === '__other';
    provInput.style.display = isOther ? '' : 'none';
    manual.style.display = isOther ? '' : 'none';
    if (isOther || !PROVIDERS[code]) { box.innerHTML = ''; return; }
    var docs = 'https://go-acme.github.io/lego/dns/' + code + '/';
    box.innerHTML = PROVIDERS[code].fields.map(function (f) {
      return '<div class="fld"><label>' + esc(f.label) + ' <span style="color:var(--muted);font-weight:500">(' + esc(f.k) + ')</span></label>' +
        '<input class="wz-input dns-f" data-k="' + esc(f.k) + '" type="' + (f.secret ? 'password' : 'text') + '" autocomplete="off">' +
        (f.hint ? '<div class="hint">' + esc(f.hint) + '</div>' : '') + '</div>';
    }).join('') +
    '<div class="hint">Provider docs: <a href="' + docs + '" target="_blank" rel="noopener">' + docs + '</a></div>';
  }
  var _dnsConfigured = false;
  var _certs = [];
  async function loadCerts() {
    var r = await api('/api/nginx/certs');
    _certs = (r.ok && r.data && r.data.certs) || [];
    renderCertList();
  }
  function renderCertList() {
    var box = $('#cert-list'); if (!box) return;
    if (!_certs.length) { box.innerHTML = '<p style="color:var(--muted)">No certificates yet. Issue one (wildcards via DNS-01) or register an external cert.</p>'; return; }
    box.innerHTML = _certs.map(function (c) {
      var covers = (c.covers && c.covers.length) ? esc(c.covers.join(', ')) : '<span style="color:var(--muted)">coverage unknown</span>';
      var badge = c.source === 'external'
        ? '<span class="tag ro">external</span>'
        : '<span class="tag rw">Let\u2019s Encrypt</span>';
      var missing = c.present === false ? ' <span class="tag" style="background:var(--danger-soft);color:var(--danger)">files missing</span>' : '';
      var exp = c.expires ? '<div class="hint" style="margin:2px 0 0">expires ' + esc(c.expires) + '</div>' : '';
      return '<div class="rule-row" style="align-items:flex-start">' +
        '<div style="flex:1"><div style="font-weight:700">' + esc(c.name) + ' ' + badge + missing + '</div>' +
        '<div class="hint" style="margin:2px 0 0">covers ' + covers + '</div>' + exp + '</div>' +
        '<button class="icon-btn danger" data-cert-del="' + esc(c.name) + '" title="Delete"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7"/></svg></button>' +
        '</div>';
    }).join('');
    box.querySelectorAll('[data-cert-del]').forEach(function (b) {
      b.onclick = function () { deleteCert(b.getAttribute('data-cert-del')); };
    });
  }
  async function deleteCert(name) {
    if (!confirm('Delete certificate "' + name + '"? External certs only lose their registration (files stay). This is refused if a host still uses it.')) return;
    var r = await api('/api/nginx/certs/' + encodeURIComponent(name), { method: 'DELETE' });
    if (r.ok) { toast('Certificate removed', 'ok'); loadCerts(); await api('/api/nginx/apply', { method: 'POST' }); loadVhosts(); }
    else toast((r.data && r.data.detail) || 'Could not delete', 'err');
  }

  // ── issue-certificate modal (standalone; NOT tied to a host) ──
  function certIssueModal() {
    var back = document.createElement('div'); back.className = 'backdrop show';
    back.innerHTML =
      '<div class="modal" style="max-width:520px">' +
      '<h3>Issue a certificate</h3>' +
      '<div class="fld"><label>Domain(s)</label><input class="wz-input" id="ci-domain" placeholder="example.com" autocomplete="off">' +
        '<div class="hint">One name, e.g. <code>example.com</code>. Turn on wildcard to also cover <code>*.example.com</code>.</div></div>' +
      '<div class="opt-row"><div class="opt-text"><h5>Wildcard</h5><p>Also issue <code>*.domain</code> (covers every one-level subdomain). Requires DNS-01.</p></div><div class="switch" id="ci-wild"><i></i></div></div>' +
      '<div class="opt-row"><div class="opt-text"><h5>Also cover the apex</h5><p>Include the bare <code>domain</code> alongside the wildcard.</p></div><div class="switch" id="ci-apex"><i></i></div></div>' +
      '<div class="fld"><label>Challenge</label><div class="seg" id="ci-mode"><button data-m="dns" class="sel pri">DNS-01</button><button data-m="http">HTTP-01</button></div>' +
        '<div class="hint" id="ci-mode-hint">DNS-01 works without exposing port 80 and supports wildcards.</div></div>' +
      '<div class="fld"><label>Email (optional)</label><input class="wz-input" id="ci-email" placeholder="you@example.com" autocomplete="off"></div>' +
      '<div id="ci-out" class="raw-err" style="display:none"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
        '<button class="button ghost" id="ci-cancel">Cancel</button><button class="button" id="ci-go">Issue</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var mode = 'dns', wild = false, apex = false;
    function setMode(m) { mode = m; back.querySelectorAll('#ci-mode button').forEach(function (b) { b.className = b.getAttribute('data-m') === m ? 'sel pri' : ''; });
      $('#ci-mode-hint', back).textContent = m === 'dns' ? 'DNS-01 works without exposing port 80 and supports wildcards.' : 'HTTP-01 validates over port 80 \u2014 the host must be reachable from the internet, and cannot do wildcards.';
      if (m === 'http' && wild) { wild = false; $('#ci-wild', back).className = 'switch'; }
    }
    back.querySelectorAll('#ci-mode button').forEach(function (b) { b.onclick = function () { setMode(b.getAttribute('data-m')); }; });
    $('#ci-wild', back).onclick = function () { wild = !wild; this.className = 'switch' + (wild ? ' on' : ''); if (wild) setMode('dns'); };
    $('#ci-apex', back).onclick = function () { apex = !apex; this.className = 'switch' + (apex ? ' on' : ''); };
    $('#ci-cancel', back).onclick = function () { back.remove(); };
    $('#ci-go', back).onclick = async function () {
      var dom = $('#ci-domain', back).value.trim().replace(/^\*\./, '');
      var email = $('#ci-email', back).value.trim();
      if (!dom) { toast('Enter a domain', 'err'); return; }
      this.disabled = true; this.style.opacity = .5;
      var out = $('#ci-out', back);
      if (mode === 'dns') {
        var r = await api('/api/nginx/cert/dns', { method: 'POST',
          body: JSON.stringify({ domain: dom, email: email, wildcard: wild, apex: apex }) });
        if (!r.ok || !r.data || !r.data.task_id) { out.style.display = ''; out.textContent = (r.data && r.data.detail) || 'Request failed'; this.disabled = false; this.style.opacity = 1; return; }
        toast('Issuing \u2014 waiting for DNS propagation\u2026', 'info');
        var btn = this;
        var t = setInterval(async function () {
          if (document.hidden) return;
          var s = await api('/api/backup/tasks/' + r.data.task_id);
          var stt = s.ok && s.data && s.data.status;
          if (stt === 'running' || stt === 'pending') return;
          clearInterval(t);
          if (stt === 'done') { toast('Certificate issued', 'ok'); back.remove(); loadCerts(); }
          else { out.style.display = ''; out.textContent = (s.data && s.data.error) || 'Issuance failed'; btn.disabled = false; btn.style.opacity = 1; }
        }, 5000);
      } else {
        var r2 = await api('/api/nginx/certbot', { method: 'POST', body: JSON.stringify({ domain: dom, email: email }) });
        if (r2.ok) { toast('Certificate issued', 'ok'); back.remove(); loadCerts(); }
        else { out.style.display = ''; out.textContent = (r2.data && r2.data.detail && (r2.data.detail.output || r2.data.detail)) || 'Request failed'; this.disabled = false; this.style.opacity = 1; }
      }
    };
  }

  // ── register-external-cert modal ──
  function certRegisterModal() {
    var back = document.createElement('div'); back.className = 'backdrop show';
    back.innerHTML =
      '<div class="modal" style="max-width:520px">' +
      '<h3>Register an external certificate</h3>' +
      '<p class="hint">Point ForgeOS at PEM files an external tool maintains (e.g. a porkbun-certbot container). ForgeOS will use and select it, but will NOT renew it \u2014 the external tool owns that.</p>' +
      '<div class="fld"><label>Name</label><input class="wz-input" id="cr-name" placeholder="example.com" autocomplete="off"><div class="hint">A label, used to select this cert on a host.</div></div>' +
      '<div class="fld"><label>fullchain.pem path</label><input class="wz-input" id="cr-fc" placeholder="/etc/certs/example.com/fullchain.pem" autocomplete="off"></div>' +
      '<div class="fld"><label>privkey.pem path</label><input class="wz-input" id="cr-pk" placeholder="/etc/certs/example.com/privkey.pem" autocomplete="off"></div>' +
      '<div id="cr-out" class="raw-err" style="display:none"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
        '<button class="button ghost" id="cr-cancel">Cancel</button><button class="button" id="cr-go">Register</button></div>' +
      '</div>';
    document.body.appendChild(back);
    $('#cr-cancel', back).onclick = function () { back.remove(); };
    $('#cr-go', back).onclick = async function () {
      var name = $('#cr-name', back).value.trim(), fcp = $('#cr-fc', back).value.trim(), pk = $('#cr-pk', back).value.trim();
      if (!name || !fcp || !pk) { toast('All fields required', 'err'); return; }
      this.disabled = true; this.style.opacity = .5;
      var r = await api('/api/nginx/certs/register', { method: 'POST',
        body: JSON.stringify({ name: name, fullchain_path: fcp, privkey_path: pk }) });
      if (r.ok) { toast('Certificate registered', 'ok'); back.remove(); loadCerts(); }
      else { var o = $('#cr-out', back); o.style.display = ''; o.textContent = (r.data && r.data.detail) || 'Could not register'; this.disabled = false; this.style.opacity = 1; }
    };
  }
  async function loadDns() {
    var d = (await api('/api/nginx/acme/dns')).data;
    _dnsConfigured = !!(d && d.configured);
    var chip = $('#dns-chip');
    if (d && d.configured) {
      chip.textContent = (d.provider || '') + ' configured';
      var sel = $('#dns-select');
      if (PROVIDERS[d.provider]) { sel.value = d.provider; renderFields(d.provider); }
      else { sel.value = '__other'; renderFields('__other'); $('#dns-provider').value = d.provider || ''; }
    } else { chip.textContent = 'no DNS provider'; }
  }
  async function saveDns() {
    var code = $('#dns-select').value;
    var prov, creds = {};
    if (code && code !== '__other') {
      prov = code;
      var missing = [];
      document.querySelectorAll('.dns-f').forEach(function (el) {
        var v = el.value.trim();
        if (v) creds[el.getAttribute('data-k')] = v; else missing.push(el.getAttribute('data-k'));
      });
      // Route53 region is optional-ish; require only that SOMETHING was entered
      if (!Object.keys(creds).length) { toast('Fill in the credential fields', 'err'); return; }
    } else {
      prov = $('#dns-provider').value.trim().toLowerCase();
      if (!prov) { toast('Pick a provider or enter a lego code', 'err'); return; }
      $('#dns-creds').value.split('\n').forEach(function (ln) {
        ln = ln.trim(); if (!ln || ln.charAt(0) === '#') return;
        var i = ln.indexOf('='); if (i < 0) return;
        var k = ln.slice(0, i).trim(); if (k) creds[k] = ln.slice(i + 1).trim();
      });
      if (!Object.keys(creds).length) { toast('Add at least one credential (KEY = value)', 'err'); return; }
    }
    var btn = $('#dns-save'); btn.disabled = true;
    var r = await api('/api/nginx/acme/dns', { method: 'PUT', body: JSON.stringify({ provider: prov, credentials: creds }) });
    btn.disabled = false;
    toast(r.ok ? 'DNS provider saved' : (r.data && r.data.detail) || 'Could not save provider', r.ok ? 'ok' : 'err');
    if (r.ok) {
      $('#dns-creds').value = '';
      document.querySelectorAll('.dns-f').forEach(function (el) { el.value = ''; });
      loadDns();
    }
  }
  async function clearDns() {
    if (!confirm('Remove the DNS provider credentials?')) return;
    var r = await api('/api/nginx/acme/dns', { method: 'DELETE' });
    toast(r.ok ? 'Provider removed' : 'Could not remove', r.ok ? 'ok' : 'err');
    if (r.ok) { $('#dns-provider').value = ''; $('#dns-creds').value = ''; loadDns(); }
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
    var ci = $('#cert-issue'); if (ci) ci.onclick = certIssueModal;
    var cr = $('#cert-register'); if (cr) cr.onclick = certRegisterModal;
    var rf = $('#refresh'); if (rf) rf.onclick = function () { loadVhosts(); loadDns(); toast('Refreshed', 'info'); };
    var ds = $('#dns-save'); if (ds) ds.onclick = saveDns;
    var dc = $('#dns-clear'); if (dc) dc.onclick = clearDns;
    var rr = $('#raw-reload'); if (rr) rr.onclick = function () { loadRaw(); toast('Reloaded', 'info'); };
    var rs = $('#raw-save'); if (rs) rs.onclick = saveRaw;
    renderProviderSelect();
    var dsel = $('#dns-select'); if (dsel) dsel.onchange = function () { renderFields(this.value); };
    loadVhosts(); loadDns(); loadRaw(); loadCerts();
  });
})();
