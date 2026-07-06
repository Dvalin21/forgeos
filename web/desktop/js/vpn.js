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

  function fmtBytes(n){
    if (!n) return '0 B';
    var u = ['B','KB','MB','GB','TB'], i = 0;
    while (n >= 1024 && i < u.length - 1){ n /= 1024; i++; }
    return (n < 10 && i ? n.toFixed(1) : Math.round(n)) + ' ' + u[i];
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
    // diagnostics strip
    var set = function(id, txt, cls){ var el = document.getElementById(id); el.textContent = txt; el.className = 'dv' + (cls ? ' ' + cls : ''); };
    set('dg-if', d.running ? (d.interface || 'wg0') + ' up' : 'down', d.running ? 'ok' : 'bad');
    set('dg-port', d.listen_port + '/udp');
    set('dg-ep', d.endpoint || 'not set', d.endpoint ? 'ok' : 'bad');
    set('dg-fwd', d.ip_forward === null ? 'unknown' : (d.ip_forward ? 'on' : 'off'),
        d.ip_forward === null ? '' : (d.ip_forward ? 'ok' : 'bad'));
    // prefill endpoint field once (don't clobber while user types)
    var ep = document.getElementById('ep-input');
    if (!ep.dataset.touched && !ep.value && d.endpoint) ep.value = d.endpoint;
    var note = document.getElementById('ep-note');
    if (!d.endpoint){ note.textContent = 'Required before devices can be added.'; note.className = 'ep-note warn'; }
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
        '<td class="peer-ip">' + esc(p.address) + '</td>' +
        '<td>' + statusPill + '</td>' +
        '<td style="color:var(--muted);font-size:13px">' + fmtHandshake(p.last_handshake_epoch) + '</td>' +
        '<td class="peer-xfer">↓ ' + fmtBytes(p.rx_bytes) + ' · ↑ ' + fmtBytes(p.tx_bytes) + '</td>' +
        '<td class="peer-xfer">' + esc(p.remote || '—') + '</td>' +
        '<td><div class="row-actions">' +
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
    showConfigOnce(r.data);   // return-once: this is the only time the key is shown
  };

  // ── Config-once modal (return-once: server never stores the client key) ──
  var qrBack = document.getElementById('qr-backdrop');
  function showConfigOnce(data){
    if (!data) return;
    document.getElementById('qr-title').textContent = 'Add this device — ' + data.name;
    var img = document.getElementById('qr-img');
    if (data.qr){ img.src = data.qr; img.style.display = ''; } else { img.style.display = 'none'; }
    var box = document.getElementById('qr-conf');
    if (box){ box.textContent = data.config || ''; }
    var warn = document.getElementById('qr-warn');
    if (warn){ warn.textContent = data.warning || ''; }
    window._lastConf = { name: data.name, config: data.config || '' };
    qrBack.classList.add('show');
  }
  document.getElementById('qr-close').onclick = function(){ qrBack.classList.remove('show'); };
  document.getElementById('qr-download').onclick = function(){
    var c = window._lastConf; if (!c) return;
    var blob = new Blob([c.config], { type: 'text/plain' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = c.name + '.conf';
    a.click();
  };

  // ── Row actions (event delegation) ──
  document.getElementById('peer-rows').onclick = async function(e){
    var delBtn = e.target.closest('[data-del]');
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

  // ── Server endpoint ──
  var epInput = document.getElementById('ep-input');
  epInput.oninput = function(){ epInput.dataset.touched = '1'; };
  document.getElementById('ep-save').onclick = async function(){
    var r = await api('/api/vpn/settings', { method: 'PUT', body: JSON.stringify({ endpoint: epInput.value.trim() }) });
    if (!r.ok){ toast((r.data && r.data.detail) || 'Could not save endpoint', 'err'); return; }
    toast('Endpoint saved', 'ok');
    var note = document.getElementById('ep-note'); note.textContent = ''; note.className = 'ep-note';
    await loadStatus();
  };
  document.getElementById('ep-detect').onclick = async function(){
    var btn = this; btn.disabled = true;
    var r = await api('/api/vpn/detect-endpoint');
    btn.disabled = false;
    var d = r.data || {};
    if (!r.ok || (!d.public_ip && !d.lan_ip)){ toast('Detection failed — enter it manually', 'err'); return; }
    epInput.value = d.public_ip || d.lan_ip;
    epInput.dataset.touched = '1';
    var note = document.getElementById('ep-note');
    note.className = 'ep-note';
    note.textContent = d.public_ip
      ? 'Public IP ' + d.public_ip + (d.lan_ip ? ' (LAN: ' + d.lan_ip + ')' : '') + ' — remote devices also need UDP port-forwarding on your router.'
      : 'Only the LAN IP was found (' + d.lan_ip + ') — works on your network only.';
  };

  refreshAll();
  setInterval(function(){                    // live view: 5s, only while visible
    if (!document.hidden) refreshAll();
  }, 5000);
