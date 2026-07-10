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
      '<div class="fld"><label>Domain</label><input class="wz-input" id="v-domain" placeholder="test.example.com" autocomplete="off"><div class="hint">The hostname nginx answers on. If it is under a domain you added, its certificate is used automatically; otherwise it is self-signed.</div></div>' +
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
      '<div class="fld"><div class="hint" id="v-cert-note" style="margin-top:4px"></div></div>' +
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go disabled style="opacity:.5">' + (ed ? 'Save changes' : 'Create host') + '</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var go = $('[data-go]', back);

    function setSw(k, on) { st[k] = !!on; var el = $('[data-sw="' + k + '"]', back); if (el) el.className = 'switch' + (on ? ' on' : ''); }
    $$('[data-sw]', back).forEach(function (el) { el.onclick = function () { var k = el.getAttribute('data-sw'); setSw(k, !st[k]); }; });
    function selScheme(s) { st.upstream_scheme = s; $$('#scheme button', back).forEach(function (b) { b.className = b.getAttribute('data-s') === s ? 'sel pri' : ''; }); }
    $$('#scheme button', back).forEach(function (b) { b.onclick = function () { selScheme(b.getAttribute('data-s')); }; });

    // ── certificate is inherited from the matching managed domain ──
    function domainFor(host) {
      var h = host.toLowerCase().replace(/^\*\./, '');
      var best = null;
      _domains.forEach(function (d) {
        if (h === d.name || h.endsWith('.' + d.name)) {
          if (!best || d.name.length > best.name.length) best = d;
        }
      });
      return best;
    }
    function updateCertNote() {
      var host = $('#v-domain', back).value.trim();
      var note = $('#v-cert-note', back);
      if (!host) { note.textContent = ''; return; }
      var d = domainFor(host);
      if (d && d.cert_present) {
        note.innerHTML = '\u2713 Uses the certificate from <b>' + esc(d.name) + '</b>' +
          (d.wildcard ? ' (wildcard)' : '') + '.'; note.style.color = 'var(--ok, #2e7d32)';
      } else if (d && !d.cert_present) {
        note.innerHTML = 'Domain <b>' + esc(d.name) + '</b> is added but its certificate has not issued yet.';
        note.style.color = 'var(--warn, #b26a00)';
      } else {
        note.textContent = 'No matching domain \u2014 this host will use a self-signed certificate. Add its domain above to get a real one.';
        note.style.color = 'var(--muted)';
      }
    }
    $('#v-domain', back).addEventListener('input', updateCertNote);

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
      updateCertNote();
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
      if (!r.ok) {
        toast((r.data && r.data.detail) || ('Could not ' + (ed ? 'update' : 'create') + ' host'), 'err');
        go.disabled = false; go.style.opacity = 1; return;
      }
      toast(ed ? 'Host updated' : 'Host created', 'ok');
      close();
      // Re-render so the generator applies the domain-matched cert.
      await api('/api/nginx/apply', { method: 'POST' });
      loadVhosts();
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

  // renderFields: draw a provider's credential inputs into `box`.
  function renderFields(code, box) {
    if (!PROVIDERS[code]) { box.innerHTML = '<div class="hint">Enter credentials as ENV = value, one per line.</div><textarea class="raw-conf dman" style="min-height:80px" spellcheck="false" placeholder="MYPROVIDER_API_TOKEN = abc123"></textarea>'; return; }
    var docs = 'https://go-acme.github.io/lego/dns/' + code + '/';
    box.innerHTML = PROVIDERS[code].fields.map(function (f) {
      return '<div class="fld"><label>' + esc(f.label) + ' <span style="color:var(--muted);font-weight:500">(' + esc(f.k) + ')</span></label>' +
        '<input class="wz-input dns-f" data-k="' + esc(f.k) + '" type="' + (f.secret ? 'password' : 'text') + '" autocomplete="off">' +
        (f.hint ? '<div class="hint">' + esc(f.hint) + '</div>' : '') + '</div>';
    }).join('') +
    '<div class="hint">Provider docs: <a href="' + docs + '" target="_blank" rel="noopener">' + docs + '</a></div>';
  }

  // ── Domains: list + add (issues cert) + delete ──
  var _domains = [];
  async function loadDomains() {
    var r = await api('/api/nginx/domains');
    _domains = (r.ok && r.data && r.data.domains) || [];
    _savedProviders = (r.ok && r.data && r.data.providers) || [];
    renderDomainList();
  }
  var _savedProviders = [];
  function renderDomainList() {
    var box = $('#domain-list'); if (!box) return;
    if (!_domains.length) { box.innerHTML = '<p style="color:var(--muted)">No domains yet. Add one to issue its certificate; hosts under it then use that certificate automatically.</p>'; return; }
    box.innerHTML = _domains.map(function (d) {
      var kind = d.wildcard ? '<span class="tag rw">wildcard</span>' : '<span class="tag ro">single</span>';
      var cert = d.cert_present
        ? '<span class="tag rw">cert ready</span>' + (d.expires ? ' <span class="hint">exp ' + esc(d.expires) + '</span>' : '')
        : '<span class="tag" style="background:var(--warn-soft,#fff3e0);color:var(--warn,#b26a00)">issuing / not ready</span>';
      var covers = (d.covers && d.covers.length) ? '<div class="hint" style="margin:2px 0 0">covers ' + esc(d.covers.join(', ')) + '</div>' : '';
      return '<div class="rule-row" style="align-items:flex-start">' +
        '<div style="flex:1"><div style="font-weight:700">' + esc(d.name) + ' ' + kind + ' ' + cert + '</div>' +
        '<div class="hint" style="margin:2px 0 0">provider: ' + esc(d.provider) + '</div>' + covers + '</div>' +
        '<button class="icon-btn danger" data-dom-del="' + esc(d.name) + '" title="Remove"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7"/></svg></button>' +
        '</div>';
    }).join('');
    box.querySelectorAll('[data-dom-del]').forEach(function (b) { b.onclick = function () { deleteDomain(b.getAttribute('data-dom-del')); }; });
  }
  async function deleteDomain(name) {
    if (!confirm('Remove domain "' + name + '" and delete its certificate? Refused if any host is under it.')) return;
    var r = await api('/api/nginx/domains/' + encodeURIComponent(name), { method: 'DELETE' });
    if (r.ok) { toast('Domain removed', 'ok'); loadDomains(); }
    else toast((r.data && r.data.detail) || 'Could not remove', 'err');
  }
  function domainAddModal() {
    var back = document.createElement('div'); back.className = 'modal-back';
    var provOpts = Object.keys(PROVIDERS).map(function (c) { return '<option value="' + c + '">' + PROVIDERS[c].title + '</option>'; }).join('') + '<option value="__other">Other (lego code)\u2026</option>';
    back.innerHTML = '<div class="modal share-modal"><h3>Add domain</h3>' +
      '<p class="sub">Issues the certificate now. The domain\u2019s A/CNAME record must already point to this server at your DNS provider.</p>' +
      '<div class="fld"><label>Domain</label><input class="wz-input" id="da-name" placeholder="example.com" autocomplete="off"><div class="hint">The base domain, e.g. <code>example.com</code>.</div></div>' +
      '<div class="fld"><label>Certificate</label><div class="seg" id="da-kind"><button data-k="wildcard" class="sel pri">Wildcard (*.domain)</button><button data-k="single">Single (domain only)</button></div>' +
        '<div class="hint" id="da-kind-hint">Wildcard covers every subdomain (mail., smtp., test., \u2026). Recommended.</div></div>' +
      '<div class="fld"><label>DNS provider</label><select class="wz-input" id="da-prov">' + provOpts + '</select>' +
        '<input class="wz-input" id="da-prov-other" placeholder="lego provider code" autocomplete="off" style="display:none;margin-top:8px"><div class="hint" id="da-prov-status"></div></div>' +
      '<div class="fld" id="da-creds-wrap"><label>Provider credentials</label><div id="da-fields"></div></div>' +
      '<div class="fld"><label>Email (optional)</label><input class="wz-input" id="da-email" placeholder="you@example.com" autocomplete="off"></div>' +
      '<div id="da-out" class="raw-err" style="display:none"></div>' +
      '<div class="row" style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" id="da-go">Add &amp; issue</button></div>' +
      '</div>';
    document.body.appendChild(back);
    var kind = 'wildcard';
    $$('#da-kind button', back).forEach(function (b) { b.onclick = function () { kind = b.getAttribute('data-k'); $$('#da-kind button', back).forEach(function (x) { x.className = x.getAttribute('data-k') === kind ? 'sel pri' : ''; }); $('#da-kind-hint', back).textContent = kind === 'wildcard' ? 'Wildcard covers every subdomain (mail., smtp., test., \u2026). Recommended.' : 'Single covers only the bare domain.'; }; });
    function refreshProvider() {
      var code = $('#da-prov', back).value;
      var other = $('#da-prov-other', back);
      other.style.display = code === '__other' ? '' : 'none';
      var actual = code === '__other' ? (other.value.trim().toLowerCase() || '') : code;
      var saved = _savedProviders.some(function (p) { return p.code === actual; });
      var status = $('#da-prov-status', back), wrap = $('#da-creds-wrap', back);
      if (saved) { status.innerHTML = '\u2713 Using saved credentials for <b>' + esc(actual) + '</b>.'; status.style.color = 'var(--ok,#2e7d32)'; wrap.style.display = 'none'; }
      else { status.textContent = ''; wrap.style.display = ''; renderFields(code === '__other' ? '__x' : code, $('#da-fields', back)); }
    }
    $('#da-prov', back).onchange = refreshProvider;
    $('#da-prov-other', back).addEventListener('input', refreshProvider);
    refreshProvider();
    back.addEventListener('click', function (e) { if (e.target === back || e.target.hasAttribute('data-x')) back.remove(); });
    $('#da-go', back).onclick = async function () {
      var name = $('#da-name', back).value.trim().toLowerCase();
      var code = $('#da-prov', back).value;
      var provider = code === '__other' ? $('#da-prov-other', back).value.trim().toLowerCase() : code;
      var email = $('#da-email', back).value.trim();
      if (!name) { toast('Enter a domain', 'err'); return; }
      if (!provider) { toast('Choose a provider', 'err'); return; }
      var creds = null;
      var wrap = $('#da-creds-wrap', back);
      if (wrap.style.display !== 'none') {
        creds = {};
        var fs = back.querySelectorAll('.dns-f');
        if (fs.length) { fs.forEach(function (el) { var v = el.value.trim(); if (v) creds[el.getAttribute('data-k')] = v; }); }
        else { var man = back.querySelector('.dman'); if (man) man.value.split('\n').forEach(function (ln) { ln = ln.trim(); var i = ln.indexOf('='); if (i > 0) creds[ln.slice(0, i).trim()] = ln.slice(i + 1).trim(); }); }
        if (!Object.keys(creds).length) { toast('Enter the provider credentials', 'err'); return; }
      }
      this.disabled = true; this.style.opacity = .5;
      var out = $('#da-out', back);
      var r = await api('/api/nginx/domains', { method: 'POST', body: JSON.stringify({ name: name, provider: provider, wildcard: kind === 'wildcard', credentials: creds, email: email }) });
      if (!r.ok || !r.data || !r.data.task_id) { out.style.display = ''; out.textContent = (r.data && r.data.detail) || 'Could not add domain'; this.disabled = false; this.style.opacity = 1; return; }
      toast('Issuing certificate \u2014 DNS propagation can take minutes\u2026', 'info');
      back.remove(); loadDomains();
      var t = setInterval(async function () {
        if (document.hidden) return;
        var s = await api('/api/backup/tasks/' + r.data.task_id);
        var stt = s.ok && s.data && s.data.status;
        if (stt === 'running' || stt === 'pending') return;
        clearInterval(t);
        if (stt === 'done') { toast('Certificate issued for ' + name, 'ok'); await api('/api/nginx/apply', { method: 'POST' }); loadDomains(); loadVhosts(); }
        else toast('Certificate failed for ' + name + ' \u2014 check the Activity Log', 'err');
      }, 5000);
    };
  }


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
    var da = $('#domain-add'); if (da) da.onclick = domainAddModal;
    var rf = $('#refresh'); if (rf) rf.onclick = function () { loadVhosts(); loadDomains(); toast('Refreshed', 'info'); };
    var rr = $('#raw-reload'); if (rr) rr.onclick = function () { loadRaw(); toast('Reloaded', 'info'); };
    var rs = $('#raw-save'); if (rs) rs.onclick = saveRaw;
    loadVhosts(); loadDomains(); loadRaw();
  });
})();
