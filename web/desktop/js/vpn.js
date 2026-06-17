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
    var w = document.getElementById('toasts');
    var el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = msg;
    w.appendChild(el);
    setTimeout(function(){ el.remove(); }, 3200);
  }

  function fmtHandshake(epoch){
    if (!epoch) return 'never';
    var secs = Math.floor(Date.now()/1000) - epoch;
    if (secs < 0) return 'just now';
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.floor(secs/60) + 'm ago';
    if (secs < 86400) return Math.floor(secs/3600) + 'h ago';
    return Math.floor(secs/86400) + 'd ago';
  }

  async function loadStatus(){
    var d = (await api('/api/vpn/status')).data;
    var orb = document.getElementById('orb');
    var title = document.getElementById('status-title');
    var desc = document.getElementById('status-desc');
    if (!d){ title.textContent = 'Could not read VPN status'; desc.textContent = 'Check that the API is reachable.'; return; }
    if (d.running){
      orb.className = 'status-orb up';
      title.textContent = 'VPN is running';
      desc.textContent = 'WireGuard interface ' + (d.interface || 'wg0') + ' is up and accepting connections.';
    } else {
      orb.className = 'status-orb down';
      title.textContent = 'VPN is stopped';
      desc.textContent = 'WireGuard is not currently running. Start it to allow remote devices.';
    }
  }

  async function loadPeers(){
    var d = (await api('/api/vpn/peers')).data;
    var rows = document.getElementById('peer-rows');
    var empty = document.getElementById('empty');
    rows.innerHTML = '';
    var peers = (d && d.peers) || [];
    document.getElementById('stat-total').textContent = peers.length;
    document.getElementById('stat-online').textContent = peers.filter(function(p){ return p.online; }).length;
    if (!peers.length){ empty.style.display = 'block'; return; }
    empty.style.display = 'none';
    peers.forEach(function(p){
      var tr = document.createElement('tr');
      var statusPill = p.online
        ? '<span class="pill online"><span class="dot"></span>Online</span>'
        : '<span class="pill offline"><span class="dot"></span>Offline</span>';
      tr.innerHTML =
        '<td class="peer-name">' + esc(p.name) + '</td>' +
        '<td class="peer-ip">' + esc(p.ip) + '</td>' +
        '<td>' + statusPill + '</td>' +
        '<td style="color:var(--muted);font-size:13px">' + fmtHandshake(p.last_handshake_epoch) + '</td>' +
        '<td><div class="row-actions">' +
          '<button class="icon-btn" title="Show QR / config" data-qr="' + esc(p.name) + '"><svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3M17 17v4h4v-4M21 14v.01"/></svg></button>' +
          '<button class="icon-btn danger" title="Remove" data-del="' + esc(p.name) + '"><svg class="ico" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></button>' +
        '</div></td>';
      rows.appendChild(tr);
    });
  }

  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

  async function refreshAll(){ await Promise.all([loadStatus(), loadPeers()]); }

  // ── Add peer modal ──
  var addBack = document.getElementById('add-backdrop');
  document.getElementById('add-peer').onclick = function(){
    document.getElementById('p-name').value = '';
    addBack.classList.add('show');
    document.getElementById('p-name').focus();
  };
  document.getElementById('add-cancel').onclick = function(){ addBack.classList.remove('show'); };
  document.getElementById('add-confirm').onclick = async function(){
    var name = document.getElementById('p-name').value.trim();
    var dns = document.getElementById('p-dns').value.trim();
    var routes = document.getElementById('p-routes').value;
    if (!name){ toast('Enter a device name', 'err'); return; }
    var btn = this; btn.disabled = true;
    var r = await api('/api/vpn/peers', { method: 'POST', body: JSON.stringify({ name: name, dns: dns, allowed_ips: routes }) });
    btn.disabled = false;
    if (!r.ok){ toast((r.data && r.data.detail) || 'Could not add device', 'err'); return; }
    addBack.classList.remove('show');
    toast('Device "' + name + '" added', 'ok');
    await loadPeers();
    showQr(name);
  };

  // ── QR modal ──
  var qrBack = document.getElementById('qr-backdrop');
  var qrCurrentName = null;
  async function showQr(name){
    qrCurrentName = name;
    document.getElementById('qr-title').textContent = 'Scan to connect — ' + name;
    var img = document.getElementById('qr-img');
    // Fetch QR PNG with auth header, render as blob URL
    var t = token();
    var resp = await fetch('/api/vpn/peers/' + encodeURIComponent(name) + '/qr', {
      headers: t ? { Authorization: 'Bearer ' + t } : {}
    });
    if (!resp.ok){ toast('Could not load QR code', 'err'); return; }
    var blob = await resp.blob();
    img.src = URL.createObjectURL(blob);
    qrBack.classList.add('show');
  }
  document.getElementById('qr-close').onclick = function(){ qrBack.classList.remove('show'); };
  document.getElementById('qr-download').onclick = async function(){
    if (!qrCurrentName) return;
    var t = token();
    var resp = await fetch('/api/vpn/peers/' + encodeURIComponent(qrCurrentName) + '/config', {
      headers: t ? { Authorization: 'Bearer ' + t } : {}
    });
    if (!resp.ok){ toast('Could not download config', 'err'); return; }
    var text = await resp.text();
    var blob = new Blob([text], { type: 'text/plain' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = qrCurrentName + '.conf';
    a.click();
  };

  // ── Row actions (event delegation) ──
  document.getElementById('peer-rows').onclick = async function(e){
    var qrBtn = e.target.closest('[data-qr]');
    var delBtn = e.target.closest('[data-del]');
    if (qrBtn){ showQr(qrBtn.getAttribute('data-qr')); return; }
    if (delBtn){
      var name = delBtn.getAttribute('data-del');
      if (!confirm('Remove VPN device "' + name + '"? Its config will stop working immediately.')) return;
      var r = await api('/api/vpn/peers/' + encodeURIComponent(name), { method: 'DELETE' });
      if (!r.ok){ toast((r.data && r.data.detail) || 'Could not remove device', 'err'); return; }
      toast('Device "' + name + '" removed', 'ok');
      await loadPeers();
    }
  };

  // ── Service control ──
  document.querySelectorAll('[data-action]').forEach(function(btn){
    btn.onclick = async function(){
      var action = btn.getAttribute('data-action');
      btn.disabled = true;
      var r = await api('/api/vpn/control/' + action, { method: 'POST' });
      btn.disabled = false;
      if (!r.ok){ toast((r.data && r.data.detail) || ('Could not ' + action), 'err'); return; }
      toast('VPN ' + action + 'ed', 'ok');
      await loadStatus();
    };
  });

  document.getElementById('refresh').onclick = function(){
    var ico = this.querySelector('.ico'); ico.classList.add('spin');
    refreshAll().then(function(){ setTimeout(function(){ ico.classList.remove('spin'); }, 400); });
  };

  // close modals on backdrop click
  [addBack, qrBack].forEach(function(b){
    b.onclick = function(e){ if (e.target === b) b.classList.remove('show'); };
  });

  refreshAll();
  setInterval(loadPeers, 15000);  // light auto-refresh of handshake status
