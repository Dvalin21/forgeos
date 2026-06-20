(function () {
  "use strict";
  var TOKEN = "forgeos_token";
  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var setLive = function (k, v) { $$('[data-live="' + k + '"]').forEach(function (el) { el.textContent = (v == null ? "—" : v); }); };

  // ── auth-aware fetch ───────────────────────────────────────
  function token() { try { return localStorage.getItem(TOKEN); } catch (e) { return null; } }
  function setToken(t) { try { t ? localStorage.setItem(TOKEN, t) : localStorage.removeItem(TOKEN); } catch (e) {} }

  async function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers || {});
    var t = token();
    if (t) headers["Authorization"] = "Bearer " + t;
    if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    try {
      var res = await fetch(path, Object.assign({}, opts, { headers: headers }));
      if (res.status === 401) { logout(); return { status: 401, data: null }; }
      var data = null;
      try { data = await res.json(); } catch (e) {}
      return { status: res.status, ok: res.ok, data: data };
    } catch (e) { return { status: 0, ok: false, data: null }; }
  }

  // ── formatting helpers ─────────────────────────────────────
  function fmtBytes(b) {
    b = Number(b) || 0;
    if (b >= 1e12) return (b / 1e12).toFixed(1) + " TB";
    if (b >= 1e9)  return (b / 1e9).toFixed(1) + " GB";
    if (b >= 1e6)  return (b / 1e6).toFixed(1) + " MB";
    if (b >= 1e3)  return (b / 1e3).toFixed(0) + " KB";
    return b + " B";
  }
  function fmtRate(bps) {
    bps = Number(bps) || 0;
    if (bps >= 1e9) return (bps / 1e9).toFixed(2) + " Gb/s";
    if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " Mb/s";
    if (bps >= 1e3) return (bps / 1e3).toFixed(0) + " Kb/s";
    return bps.toFixed(0) + " b/s";
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = (s == null ? "" : s); return d.innerHTML; }
  function setBar(name, pct) { var el = $('[data-bar="' + name + '"]'); if (el) el.style.width = Math.max(0, Math.min(100, pct)) + "%"; }
  function barClass(node, pct) {
    var bar = node && node.closest ? node.closest(".bar") : null; if (!bar) return;
    bar.classList.remove("good", "warn", "danger");
    bar.classList.add(pct >= 90 ? "danger" : pct >= 75 ? "warn" : "good");
  }

  // ── toast ──────────────────────────────────────────────────
  function toast(msg, kind) {
    kind = kind || "info";
    var box = $("#toasts");
    var el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(function () { el.style.transition = "opacity .2s"; el.style.opacity = "0"; setTimeout(function () { el.remove(); }, 220); }, 4200);
  }

  // ── lightweight modal ──────────────────────────────────────
  function modal(opts) {
    var back = document.createElement("div");
    back.className = "modal-back";
    var fields = (opts.fields || []).map(function (f) {
      if (f.type === "select") {
        var os = f.options.map(function (o) { return '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>"; }).join("");
        return '<div class="field"><label>' + esc(f.label) + '</label><select id="mf-' + f.id + '">' + os + "</select></div>";
      }
      return '<div class="field"><label>' + esc(f.label) + '</label><input id="mf-' + f.id + '" type="' + (f.type || "text") + '" placeholder="' + esc(f.placeholder || "") + '" value="' + esc(f.value || "") + '"></div>';
    }).join("");
    back.innerHTML = '<div class="modal"><h3>' + esc(opts.title) + '</h3><p class="sub">' + esc(opts.sub || "") + "</p>" + fields +
      '<div class="row"><button class="btn-ghost" data-x>Cancel</button><button class="btn-pri" data-go>' + esc(opts.cta || "Confirm") + "</button></div></div>";
    document.body.appendChild(back);
    var close = function () { back.remove(); };
    back.addEventListener("click", function (e) { if (e.target === back || e.target.hasAttribute("data-x")) close(); });
    $("[data-go]", back).addEventListener("click", function () {
      var vals = {}; (opts.fields || []).forEach(function (f) { vals[f.id] = ($("#mf-" + f.id, back) || {}).value; });
      Promise.resolve(opts.onSubmit(vals)).then(function (ok) { if (ok !== false) close(); });
    });
    var first = back.querySelector("input,select"); if (first) first.focus();
  }

  // ── status pill class from a level string ──────────────────
  function lvl(ok) { return ok ? "ok" : "warn"; }

  // ════════════ LOADERS ════════════
  async function loadIdentity() {
    var r = await api("/api/system/info");
    if (!r.data) return;
    var d = r.data;
    setLive("hero-host", d.hostname || "forgenas");
    setLive("hero-sub", [d.os, "kernel " + (d.kernel || "?"), "ForgeOS " + (d.forgeos_ver || "?")].filter(Boolean).join("  ·  "));
    setLive("set-host", d.hostname || "—");
    setLive("set-ver", "ForgeOS " + (d.forgeos_ver || "?") + "  ·  " + (d.os || ""));
    setLive("hc-cpu", (d.cpu || "CPU") + "  ·  " + (d.cpu_cores || "?") + " threads" + (window._cpuTemp ? "  ·  " + window._cpuTemp + " °C" : ""));
    var u = ($("#profile-user")); var un = u ? u.textContent.trim() : "admin";
    var av = $("#avatar"); if (av) av.textContent = (un[0] || "A").toUpperCase();
  }

  async function loadStats() {
    var r = await api("/api/system/stats");
    if (!r.data) return;
    var s = r.data;
    // CPU
    if (s.cpu_pct != null) {
      setLive("m-cpu", s.cpu_pct.toFixed(0) + "%");
      setLive("m-cpu-t", (s.load ? "load " + s.load.join(" / ") : "—"));
      setBar("cpu", s.cpu_pct); barClass($('[data-bar="cpu"]'), s.cpu_pct);
      setLive("hc-cpu-b", s.cpu_pct < 85 ? "OK" : "BUSY");
      window._cpuTemp = s.temps && s.temps.cpu;
    }
    // Memory (API returns memory.pct — NOT percent)
    if (s.memory) {
      var m = s.memory, p = m.pct != null ? m.pct : 0;
      setLive("m-mem", p.toFixed(0) + "%");
      setLive("m-mem-t", (m.used_gb || 0).toFixed(1) + " GB of " + (m.total_gb || 0).toFixed(0) + " GB");
      setBar("mem", p); barClass($('[data-bar="mem"]'), p);
    }
    // Uptime + load in hero
    setLive("uptime", s.uptime || "—");
    if (s.load) setLive("load", s.load.map(function (x) { return x.toFixed(2); }).join("  "));
    // Network rate (delta vs previous sample)
    if (s.network) netSample(s.network.bytes_recv, s.network.bytes_sent, s.timestamp);
    // sidebar health summary roll-up
    rollUpHealth();
  }

  // network sampling → live chart
  var netHist = []; var netPrev = null;
  function netSample(rx, tx, ts) {
    if (rx == null || tx == null) return;
    var now = ts || (Date.now() / 1000);
    if (netPrev) {
      var dt = Math.max(0.5, now - netPrev.ts);
      var rxr = Math.max(0, (rx - netPrev.rx) * 8 / dt);  // bits/s
      var txr = Math.max(0, (tx - netPrev.tx) * 8 / dt);
      netHist.push({ rx: rxr, tx: txr });
      if (netHist.length > 60) netHist.shift();
      setLive("net-rx", fmtRate(rxr)); setLive("net-tx", fmtRate(txr));
      setLive("m-net", fmtRate(rxr + txr)); setLive("m-net-t", "RX " + fmtRate(rxr) + " · TX " + fmtRate(txr));
      var peak = netHist.reduce(function (a, b) { return Math.max(a, b.rx, b.tx); }, 1);
      setBar("net", Math.min(100, (rxr + txr) / peak * 60));
      drawNet(peak);
    }
    netPrev = { rx: rx, tx: tx, ts: now };
  }
  function pathFrom(key, peak) {
    var n = netHist.length; if (n < 2) return "M0 175 L680 175";
    var W = 680, H = 180, pad = 8;
    return netHist.map(function (pt, i) {
      var x = (i / (n - 1)) * W;
      var y = H - pad - (pt[key] / peak) * (H - pad * 2);
      return (i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
  }
  function drawNet(peak) {
    var rx = $("#net-rx"), tx = $("#net-tx");
    if (rx) rx.setAttribute("d", pathFrom("rx", peak));
    if (tx) tx.setAttribute("d", pathFrom("tx", peak));
  }

  async function loadStorage() {
    // capacity from df (btrfs mounts)
    var df = (await api("/api/storage/df")).data;
    var vl = $("#volume-list"); var total = 0, used = 0;
    if (Array.isArray(df) && df.length) {
      vl.innerHTML = df.map(function (v) {
        total += v.total || 0; used += v.used || 0;
        var pct = v.total ? Math.round((v.used / v.total) * 100) : 0;
        var cls = pct >= 90 ? "danger" : pct >= 75 ? "warn" : "good";
        return '<div class="volume"><div class="volume-head"><div><h4>' + esc(v.mount) + "</h4><p>btrfs · " + esc(v.source) +
          '</p></div><strong>' + fmtBytes(v.used) + " / " + fmtBytes(v.total) + '</strong></div><div class="bar ' + cls + '"><i style="width:' + pct + '%"></i></div></div>';
      }).join("");
    } else { vl.innerHTML = '<div class="vol-empty">No btrfs volumes mounted.</div>'; }
    var poolPct = total ? Math.round((used / total) * 100) : 0;
    setLive("st-pct", poolPct + "%");
    var donut = $("#st-donut"); if (donut) donut.style.setProperty("--pct", poolPct + "%");
    setLive("m-vol", poolPct + "%"); setLive("m-vol-t", fmtBytes(total - used) + " free"); setBar("vol", poolPct); barClass($('[data-bar="vol"]'), poolPct);
    setLive("protected", fmtBytes(used));
    window._stTotal = total; window._stUsed = used;

    // RAID health from pools
    var pools = (await api("/api/storage/pools")).data;
    if (pools && pools.pools) {
      var arr = pools.pools, ndrives = 0, worst = "ok";
      var order = { ok: 0, predict: 1, warn: 2, rebuilding: 2, err: 3 };
      arr.forEach(function (p) { ndrives += (p.drives || []).length; if ((order[p.health] || 0) > (order[worst] || 0)) worst = p.health; });
      var lvlName = arr.length ? (arr[0].level || "raid").toUpperCase().replace("RAID", "RAID ") : "—";
      setLive("st-chip", arr.length ? (lvlName + " · " + (worst === "ok" ? "Online" : worst)) : "No array");
      setLive("hc-pool", arr.length ? (lvlName + " · " + ndrives + " disks") : "No mdadm array");
      setLive("hc-pool-b", worst === "ok" ? "OK" : (worst === "err" ? "ERR" : worst.toUpperCase()));
      var hb = $$('[data-live="hc-pool-b"]')[0]; if (hb) hb.closest(".mini-card").classList.toggle("warning", worst !== "ok" && worst !== "err");
      window._poolHealth = worst;
    } else { setLive("st-chip", "—"); setLive("hc-pool", "Pool status unavailable"); setLive("hc-pool-b", "?"); }
  }

  async function loadShares() {
    var data = (await api("/api/samba/shares")).data;
    var rows = $("#share-rows");
    var shares = (data && data.shares) || [];
    if (shares.length) {
      rows.innerHTML = shares.map(function (s) {
        var access = s.writable ? "Read/Write" : "Read-only";
        return "<tr><td><div class='file-cell'><span class='icon-badge'><svg viewBox='0 0 24 24'><path d='M3.8 6.5h6.5l1.8 2h8.1v9.8c0 1.1-.9 2-2 2H5.8c-1.1 0-2-.9-2-2z'/></svg></span>" +
          esc(s.name) + "</div></td><td>" + esc(s.path || "—") + "</td><td>" + esc(access) + "</td><td>" + esc(s.type || "standard") +
          "</td><td class='status ok'>Active</td></tr>";
      }).join("");
    } else { rows.innerHTML = "<tr><td colspan='5' class='vol-empty'>No Samba shares configured.</td></tr>"; }
  }

  async function loadServices() {
    var svc = (await api("/api/services")).data;
    var grid = $("#app-grid");
    if (svc && svc.services) {
      var running = svc.services.filter(function (s) { return s.status === "running"; }).length;
      setLive("svc-chip", running + " / " + svc.services.length + " running");
      grid.innerHTML = svc.services.map(function (s) {
        var on = s.status === "running";
        return "<div class='app-card'><div class='icon-badge'><svg viewBox='0 0 24 24'><path d='M4 7h16v10H4z'/><path d='M8 11h8M8 14h5'/></svg></div><h4>" +
          esc(s.name) + "</h4><p>" + esc(s.desc) + "</p><div class='switch" + (on ? " on" : "") + "'><i></i></div></div>";
      }).join("");
      var fileSvc = svc.services.filter(function (s) { return /samba|nfs|nginx/i.test(s.name); });
      var upFile = fileSvc.filter(function (s) { return s.status === "running"; }).length;
      setLive("hc-svc", upFile + "/" + fileSvc.length + " file services up"); setLive("hc-svc-b", upFile === fileSvc.length ? "OK" : "CHECK");
    } else { grid.innerHTML = "<div class='vol-empty'>Service status unavailable.</div>"; }
    // running container count
    var c = (await api("/api/docker/containers")).data;
    if (c && c.containers) setLive("net-chip", "");  // noop placeholder
  }

  async function loadBackups() {
    var r = (await api("/api/backup/jobs")).data;
    var box = $("#backup-tasks");
    if (r && r.jobs && r.jobs.length) {
      setLive("bk-chip", r.jobs.length + " jobs");
      box.innerHTML = r.jobs.slice(0, 6).map(function (j) {
        var st = (j.last_status || (j.enabled ? "ready" : "paused"));
        var cls = /done|success|ok/i.test(st) ? "ok" : /fail|error/i.test(st) ? "err" : "warn";
        return "<div class='task'><div><h4>" + esc(j.name) + "</h4><p>" + esc(j.tool) + " · " + esc(j.schedule || "manual") +
          (j.last_run ? " · last " + esc(j.last_run) : "") + "</p></div><span class='status " + cls + "' data-run='" + esc(j.id) + "' style='cursor:pointer'>" + esc(st) + "</span></div>";
      }).join("");
      $$("[data-run]", box).forEach(function (el) {
        el.addEventListener("click", async function () {
          var rr = await api("/api/backup/jobs/" + el.getAttribute("data-run") + "/run", { method: "POST" });
          toast(rr.ok ? "Backup job triggered" : "Could not trigger job", rr.ok ? "ok" : "err");
        });
      });
    } else { setLive("bk-chip", "0 jobs"); box.innerHTML = "<div class='vol-empty'>No backup jobs configured.</div>"; }
  }

  async function loadActivity() {
    var r = (await api("/api/audit?limit=8")).data;
    var box = $("#activity");
    if (r && r.entries && r.entries.length) {
      box.innerHTML = r.entries.map(function (e) {
        var when = e.timestamp ? new Date((String(e.timestamp).length > 12 ? e.timestamp : e.timestamp * 1000)).toLocaleString() : "";
        return "<div class='event'><div class='icon-badge'><svg viewBox='0 0 24 24'><path d='M12 8v4l3 2'/><circle cx='12' cy='12' r='9'/></svg></div><div><h4>" +
          esc(e.action) + "</h4><p>" + esc(e.detail || (e.who + " · " + e.status)) + "</p><time>" + esc(when) + "</time></div></div>";
      }).join("");
    } else { box.innerHTML = "<div class='vol-empty'>No recent audit events.</div>"; }
  }

  async function loadSessions() {
    var r = (await api("/api/samba/connections")).data;
    var box = $("#conn-list");
    var out = (r && r.output) || "";
    var lines = out.split("\n").filter(function (l) { return /\b(connected|ipc|192\.|10\.|172\.)\b/i.test(l) && !/^\s*$/.test(l); });
    var role = ($("#profile-role").textContent || "");
    var head = "<div class='task'><div><h4>" + esc($("#profile-user").textContent) + "</h4><p>Signed-in admin · " + esc(role) + "</p></div><span class='status ok'>This session</span></div>";
    if (lines.length) {
      setLive("sess-chip", lines.length + " SMB");
      setLive("sessions", lines.length);
      box.innerHTML = head + lines.slice(0, 8).map(function (l) {
        return "<div class='task'><div><h4>SMB client</h4><p>" + esc(l.trim().slice(0, 90)) + "</p></div><span class='status ok'>Connected</span></div>";
      }).join("");
    } else {
      setLive("sess-chip", "1");
      setLive("sessions", 1);
      box.innerHTML = head + "<div class='vol-empty'>No active SMB client connections.</div>";
    }
  }

  async function loadSecurity() {
    var fw = (await api("/api/security/firewall")).data;
    if (fw) {
      var active = /Status:\s*active/i.test(fw.ufw || "");
      setLive("sec-ufw", active ? "Active" : "Inactive"); $$('[data-live="sec-ufw"]')[0].className = "status " + lvl(active);
      setLive("sec-ufw-p", active ? "Default deny inbound · " + (fw.iptables_count || "0") + " iptables rules" : "UFW not enabled");
    }
    var f2b = (await api("/api/security/fail2ban")).data;
    if (f2b) {
      var banned = (f2b.output.match(/Currently banned:\s*(\d+)/i) || [])[1];
      var jails = (f2b.output.match(/Jail list:\s*(.+)/i) || [])[1];
      var running = !/not running/i.test(f2b.output);
      setLive("sec-f2b", running ? "Active" : "Off"); $$('[data-live="sec-f2b"]')[0].className = "status " + lvl(running);
      setLive("sec-f2b-p", running ? ("Jails: " + (jails || "sshd").trim() + " · banned " + (banned || "0")) : "fail2ban not running");
    }
    var cs = (await api("/api/security/crowdsec")).data;
    if (cs) {
      var installed = !/not installed/i.test(cs.output || "");
      var decisions = (cs.output.match(/\n/g) || []).length;
      setLive("sec-cs", installed ? "Active" : "—"); $$('[data-live="sec-cs"]')[0].className = "status " + (installed ? "ok" : "warn");
      setLive("sec-cs-p", installed ? (Math.max(0, decisions - 2) + " active decisions") : "CrowdSec not installed (optional)");
    }
    setLive("sec-chip", "Hardened");
  }

  async function loadSettings() {
    var s = (await api("/api/settings")).data;
    if (!s) { setLive("set-chip", "admin only"); return; }
    setLive("set-chip", s.HIPAA_ENABLED === "1" ? "HIPAA on" : "Auto patch");
    setLive("set-domain", s.DOMAIN || "local");
    setLive("set-tz", s.TIMEZONE || "UTC");
    setLive("set-ver", "ForgeOS " + (s.FORGEOS_VERSION || "?"));
    setLive("set-ver-s", "Current");
    if (s.PRIMARY_POOL) setLive("hc-pool", (s.PRIMARY_POOL_TYPE || "btrfs") + " · " + s.PRIMARY_POOL);
  }

  function rollUpHealth() {
    var pool = window._poolHealth || "ok";
    var ok = pool === "ok";
    setLive("health", ok ? "Normal" : (pool === "err" ? "Attention" : "Watch"));
    setLive("health-chip", ok ? "Normal" : (pool === "err" ? "Degraded" : "Watch"));
    setLive("hero-state", ok ? "System healthy" : "Needs attention");
    var sf = $("#sf-detail");
    if (sf) sf.textContent = ok
      ? "All volumes mounted. Array online, SMART nominal. " + (window._stUsed != null ? fmtBytes(window._stUsed) + " protected." : "")
      : "Array health: " + pool + ". Review the Storage Manager.";
  }

  // ════════════ ACTIONS ════════════
  function doSnapshot() {
    modal({
      title: "Create Snapshot", sub: "Snapper timeline snapshot of a btrfs pool.",
      cta: "Create snapshot",
      fields: [
        { id: "pool", label: "Pool (blank = all configs)", placeholder: "main" },
        { id: "desc", label: "Description", placeholder: "manual checkpoint", value: "manual" }
      ],
      onSubmit: async function (v) {
        var r = await api("/api/storage/snapshot", { method: "POST", body: JSON.stringify({ pool: v.pool || "", description: v.desc || "manual" }) });
        toast(r.ok ? "Snapshot created" : (r.data && r.data.detail) || "Snapshot failed", r.ok ? "ok" : "err");
        if (r.ok) loadActivity();
        return r.ok;
      }
    });
  }
  function doShare() {
    modal({
      title: "Create Share", sub: "New Samba share. Path must already exist on a pool.",
      cta: "Create share",
      fields: [
        { id: "name", label: "Share name", placeholder: "clients" },
        { id: "path", label: "Path", placeholder: "/srv/nas/clients" },
        { id: "type", label: "Template", type: "select", options: [
          { value: "standard", label: "Standard" }, { value: "timemachine", label: "Time Machine" },
          { value: "elevatedb", label: "ForgeFileDB / ElevateDB" }, { value: "media", label: "Media" }, { value: "private", label: "Private" }
        ] }
      ],
      onSubmit: async function (v) {
        if (!v.name || !v.path) { toast("Name and path are required", "warn"); return false; }
        var r = await api("/api/samba/share", { method: "POST", body: JSON.stringify({ name: v.name, path: v.path, type: v.type, writable: true }) });
        toast(r.ok ? "Share created" : (r.data && r.data.detail) || "Share failed", r.ok ? "ok" : "err");
        if (r.ok) { loadShares(); loadActivity(); }
        return r.ok;
      }
    });
  }
  async function doProxyReload() {
    var r = await api("/api/nginx/reload", { method: "POST" });
    toast(r.ok ? "Proxy reloaded" : (r.data && r.data.detail) || "Reload failed", r.ok ? "ok" : "err");
  }

  // ════════════ ORCHESTRATION ════════════
  function refreshHeavy() { loadIdentity(); loadStorage(); loadShares(); loadServices(); loadBackups(); loadActivity(); loadSessions(); loadSecurity(); loadSettings(); }
  function refreshFast() { loadStats(); }
  var fastTimer, heavyTimer;
  function startPolling() {
    refreshFast(); refreshHeavy();
    clearInterval(fastTimer); clearInterval(heavyTimer);
    fastTimer = setInterval(refreshFast, 5000);
    heavyTimer = setInterval(refreshHeavy, 30000);
  }
  function stopPolling() { clearInterval(fastTimer); clearInterval(heavyTimer); }

  // ════════════ AUTH UI ════════════
  function showApp() { $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); }
  function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); var u = $("#login-user"); if (u) u.focus(); }

  async function login() {
    var u = $("#login-user").value.trim(), p = $("#login-pass").value;
    var btn = $("#login-btn"), err = $("#login-err");
    err.textContent = "";
    if (!u || !p) { err.textContent = "Enter username and password."; return; }
    btn.disabled = true; btn.textContent = "Signing in…";
    var r = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: u, password: p }) });
    btn.disabled = false; btn.textContent = "Sign in";
    if (r.ok && r.data && r.data.token) {
      setToken(r.data.token);
      $("#profile-user").textContent = r.data.username || u;
      $("#profile-role").textContent = (r.data.role || "user") === "admin" ? "Administrator" : (r.data.role || "user");
      $("#avatar").textContent = ((r.data.username || u)[0] || "A").toUpperCase();
      showApp(); startPolling();
    } else {
      err.textContent = (r.data && r.data.detail) || "Login failed.";
    }
  }
  function logout() {
    stopPolling(); setToken(null);
    api("/api/auth/logout", { method: "POST" });
    showLogin();
  }

  // ════════════ INIT ════════════
  function wire() {
    $("#login-btn").addEventListener("click", login);
    $("#login-pass").addEventListener("keydown", function (e) { if (e.key === "Enter") login(); });
    $("#logout-btn").addEventListener("click", logout);
    $("#refresh-btn").addEventListener("click", function () { refreshFast(); refreshHeavy(); toast("Refreshed", "info"); });
    [["#act-snapshot", doSnapshot], ["#qa-snap", doSnapshot], ["#act-share", doShare], ["#act-share2", doShare], ["#qa-share", doShare], ["#qa-proxy", doProxyReload],
     ["#qa-refresh", function () { refreshFast(); refreshHeavy(); }]].forEach(function (p) {
      var el = $(p[0]); if (el) el.addEventListener("click", p[1]);
    });
    // nav active-state + per-section refresh
    $$(".nav a").forEach(function (a) {
      a.addEventListener("click", function () {
        $$(".nav a").forEach(function (x) { x.classList.remove("active"); });
        a.classList.add("active");
        if (window.matchMedia("(max-width: 880px)").matches) $("#sidebar").style.transform = "translateX(-100%)";
      });
    });
    var mb = $("#menu-btn"); if (mb) mb.addEventListener("click", function () {
      var s = $("#sidebar"); s.style.transform = s.style.transform === "none" ? "translateX(-100%)" : "none";
    });
  }

  document.addEventListener("DOMContentLoaded", async function () {
    wire();
    if (token()) {
      var probe = await api("/api/system/info");
      if (probe.status === 401) { showLogin(); return; }
      showApp(); startPolling();
    } else { showLogin(); }
  });

  // expose for the preview harness
  window.__forge = { showApp: showApp, startPolling: startPolling, setToken: setToken };
})();
