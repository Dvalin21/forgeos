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
  // ════════════ RENDER HELPERS ════════════
  var C = 2 * Math.PI * 26;
  function setRing(name, pct, txt, cap) {
    var el = $('[data-ring="' + name + '"] .rval'); if (!el) return;
    pct = Math.max(0, Math.min(100, pct));
    // SVG geometry must be set as ATTRIBUTES — el.style.strokeDasharray is not
    // reliably honored on an SVG <circle> across browsers (Firefox/WebKit drop
    // it), which is why the arcs never drew while the sparkline's setAttribute
    // path worked fine.
    el.setAttribute("stroke-dasharray", C);
    el.setAttribute("stroke-dashoffset", C * (1 - Math.max(pct, 2) / 100));
    el.classList.remove("g", "w", "b");
    el.classList.add(pct < 70 ? "g" : pct < 90 ? "w" : "b");
    setLive("r-" + name, txt); if (cap != null) setLive("r-" + name + "-c", cap);
  }
  var ICONS = {
    drive: '<path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/><path d="M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M9 15.5l2 2 4-4.5"/>',
    pool:  '<path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/><path d="M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    files: '<path d="M3.8 6.5h6.5l1.8 2h8.1v9.8c0 1.1-.9 2-2 2H5.8c-1.1 0-2-.9-2-2z"/>',
    shield:'<path d="M12 3l7 3v5c0 4.8-2.9 8.2-7 10-4.1-1.8-7-5.2-7-10V6z"/><path d="M9.5 12l1.8 1.8 3.7-4"/>',
    clock: '<path d="M12 8v4l3 2"/><circle cx="12" cy="12" r="8.5"/>'
  };
  var HEALTH = {};                          // row-id -> {title, desc, state, icon}
  function setHealth(id, icon, title, desc, state) {
    HEALTH[id] = { icon: icon, title: title, desc: desc, state: state };
  }
  function paintHealth() {
    var order = ["drives", "pool", "files", "protect", "backup"];
    var box = $("#health-rows"); if (!box) return;
    box.innerHTML = order.filter(function (k) { return HEALTH[k]; }).map(function (k) {
      var h = HEALTH[k];
      var cls = h.state === "ok" ? "ok" : h.state === "bad" ? "bad" : "warn";
      var lbl = h.state === "ok" ? "OK" : h.state === "bad" ? "Problem" : h.state === "setup" ? "Set up" : "Check";
      return "<div class='hrow'><div class='hico'><svg viewBox='0 0 24 24'>" + ICONS[h.icon] + "</svg></div>" +
        "<div class='grow'><h4>" + esc(h.title) + "</h4><p>" + esc(h.desc) + "</p></div>" +
        "<span class='hst " + cls + "'>" + lbl + "</span></div>";
    }).join("");
    rollUp();
  }
  function rollUp() {
    var vals = Object.keys(HEALTH).map(function (k) { return HEALTH[k].state; });
    var bad = vals.indexOf("bad") >= 0, warn = vals.indexOf("warn") >= 0 || vals.indexOf("setup") >= 0;
    setLive("hero-state", bad ? "Something needs attention" : warn ? "Mostly fine — one thing to look at" : "Everything is running normally");
    setLive("health-chip", bad ? "Problem" : warn ? "Attention" : "All good");
    var dot = $('[data-live-dot="hero"]'); if (dot) dot.className = bad || warn ? "warn" : "";
  }

  // ════════════ LOADERS ════════════
  async function loadIdentity() {
    var d = (await api("/api/system/info")).data; if (!d) return;
    setLive("hero-host", (d.hostname || "forgeos").split(".")[0]);
    // uptime arrives as `uptime -p` text ("3 weeks, 5 days, ..."): the first
    // segment is the honest human summary; the rest is noise on a dashboard.
    var up = (d.uptime || "").split(",")[0].trim();
    setLive("hero-sub", (up ? "Up " + up : "") + "  \u00b7  ForgeOS " + (d.forgeos_ver || "1.0"));
  }

  var netHist = [], netPrev = null;
  async function loadStats() {
    var s = (await api("/api/system/stats")).data; if (!s) return;
    if (s.cpu_pct != null) {
      var c = Math.round(s.cpu_pct);
      setRing("cpu", c, c + "%", c < 25 ? "Very light use" : c < 60 ? "Normal use" : c < 90 ? "Working hard" : "Maxed out");
    }
    if (s.memory && s.memory.total_gb) {
      var mp = Math.round(s.memory.pct != null ? s.memory.pct : 100 * s.memory.used_gb / s.memory.total_gb);
      setRing("mem", mp, mp + "%", s.memory.used_gb + " GB of " + s.memory.total_gb + " GB");
    }
    // network arrives as cumulative byte COUNTERS — rate is the delta
    if (s.network && s.network.bytes_recv != null) {
      var now = s.timestamp || (Date.now() / 1000);
      if (netPrev && now > netPrev.ts) {
        var dt = now - netPrev.ts;
        var rx = Math.max(0, (s.network.bytes_recv - netPrev.recv) / dt) * 8;   // bits/s
        var tx = Math.max(0, (s.network.bytes_sent - netPrev.sent) / dt) * 8;
        netHist.push({ rx: rx, tx: tx });
        if (netHist.length > 24) netHist.shift();
        setLive("net-cap", "\u2193 " + fmtRate(rx) + "   \u2191 " + fmtRate(tx));
        var peak = netHist.reduce(function (a, b) { return Math.max(a, b.rx, b.tx); }, 1);
        ["rx", "tx"].forEach(function (k) {
          var d = netHist.map(function (pt, i) {
            return (i ? "L" : "M") + (i * (200 / Math.max(netHist.length - 1, 1))) + " " + (42 - (pt[k] / peak) * 38);
          }).join(" ");
          var el = $("#sp-" + k); if (el) el.setAttribute("d", d);
        });
      }
      netPrev = { recv: s.network.bytes_recv, sent: s.network.bytes_sent, ts: now };
    }
  }

  async function loadStorage() {
    // fire all three concurrently — serial awaits queued behind the browser's
    // ~6-socket cap and made this card the last to populate on refresh
    var res = await Promise.all([
      api("/api/storage/df"), api("/api/storage/pools"), api("/api/storage/drives")]);
    var dfr = res[0].data;
    var df = Array.isArray(dfr) ? dfr : (dfr && dfr.volumes) || [];
    var pools = (res[1].data || {}).pools || [];
    var drv = (res[2].data || {}).drives || [];
    var vl = $("#vol-list");
    if (df.length) {
      var totUsed = 0, totSize = 0;
      vl.innerHTML = df.map(function (v) {
        totUsed += v.used || 0; totSize += v.total || 0;
        var pct = v.total ? Math.round(100 * v.used / v.total) : 0;
        var nm = (v.mount || "").split("/").pop() || v.mount || "volume";
        return "<div class='vrow'><div class='top'><b>" + esc(nm.charAt(0).toUpperCase() + nm.slice(1)) +
          "</b><span>" + fmtBytes(v.used) + " used of " + fmtBytes(v.total) + "</span></div>" +
          "<div class='vbar'><i style='width:" + Math.max(pct, 2) + "%'></i></div></div>";
      }).join("");
      var tp = totSize ? Math.round(100 * totUsed / totSize) : 0;
      setRing("disk", tp, tp < 1 ? "<1%" : tp + "%", fmtBytes(totSize - totUsed) + " free");
    } else { vl.innerHTML = "<div class='vol-empty'>No storage pools yet.</div>"; }
    if (pools.length) {
      var p = pools[0];
      var bad = pools.some(function (x) { return x.health && x.health !== "ok"; });
      var nd = (p.devices || []).length;
      var raid = (p.raid_level || "").toUpperCase();
      setLive("st-sub", raid === "RAID1" ? "Mirrored across " + nd + " disks"
                       : raid ? raid + " across " + nd + " disks" : "Single-disk pool");
      setLive("st-chip", bad ? "Attention" : "Online");
      setHealth("pool", "pool", "Storage pool",
        (raid ? raid + " \u00b7 " : "") + nd + " disk" + (nd === 1 ? "" : "s") +
        (bad ? " \u2014 " + p.health : " online"),
        bad ? "bad" : "ok");
    } else { setLive("st-sub", "No pool configured"); setLive("st-chip", "—"); }
    if (drv.length) {
      var pass = drv.filter(function (x) { return x.health >= 90; }).length;
      setHealth("drives", "drive", "Drives",
        pass === drv.length ? "All " + drv.length + " drives passed their health checks"
                            : pass + " of " + drv.length + " drives healthy — check Storage",
        pass === drv.length ? "ok" : "bad");
    }
    paintHealth();
  }

  async function loadHealthMisc() {
    var res = await Promise.all([
      api("/api/services"), api("/api/samba/connections"), api("/api/security/firewall"),
      api("/api/security/fail2ban"), api("/api/security/updates"), api("/api/backup/jobs")]);
    var svc = res[0].data;
    var conns = res[1].data || {};
    if (svc && svc.services) {
      var fs = svc.services.filter(function (x) { return /samba|smbd|nfs/i.test(x.name); });
      var up = fs.filter(function (x) { return x.status === "running"; }).length;
      var n = conns.count || 0;
      setHealth("files", "files", "File sharing",
        up === fs.length ? ("Working · " + n + " device" + (n === 1 ? "" : "s") + " connected right now")
                         : "Some file services are stopped — check Shares",
        up === fs.length ? "ok" : "bad");
    }
    var fw = res[2].data || {};
    var f2b = res[3].data || {};
    var up2 = res[4].data || {};
    var fwOn = /Status:\s*active/i.test(fw.ufw || "");
    var f2bOn = !!f2b.enabled && (f2b.jails || []).some(function (j) { return j.enabled; });
    var all = fwOn && f2bOn && !!up2.enabled;
    var bits = [fwOn ? "firewall on" : "firewall OFF", f2bOn ? "intrusion guard on" : "intrusion guard OFF",
                up2.enabled ? "security updates automatic" : "auto-updates OFF"];
    setHealth("protect", "shield", "Protection",
      bits.join(" \u00b7 ").replace(/^./, function (c) { return c.toUpperCase(); }),
      all ? "ok" : "warn");
    var jobs = (res[5].data || {}).jobs || [];
    var ran = jobs.filter(function (j) { return j.last_run; })
                  .sort(function (a, b) { return String(b.last_run).localeCompare(String(a.last_run)); })[0];
    if (ran) {
      var okRun = /done|success|ok/i.test(ran.last_status || "");
      setHealth("backup", "clock", "Last backup",
        "\u201c" + ran.name + "\u201d " + (okRun ? "completed" : "had a problem") + " \u00b7 " + ran.last_run,
        okRun ? "ok" : "bad");
    } else if (jobs.length) {
      setHealth("backup", "clock", "Last backup", jobs.length + " job(s) configured \u2014 none has run yet", "warn");
    } else {
      setHealth("backup", "clock", "Last backup", "No backup has run yet \u2014 set one up to protect your data", "setup");
    }
    paintHealth();
  }

  function parseLabels(raw) {
    if (!raw) return {}; if (typeof raw === "object") return raw;
    var o = {}; String(raw).split(",").forEach(function (kv) {
      var i = kv.indexOf("="); if (i > 0) o[kv.slice(0, i)] = kv.slice(i + 1); });
    return o;
  }
  async function loadApps() {
    var r = (await api("/api/docker/containers?all=true")).data || {};
    var grid = $("#apps-grid");
    var addTile = "<a class='appt add' href='/apps.html'><svg viewBox='0 0 24 24'><path d='M12 5v14M5 12h14'/></svg><span>Add app</span></a>";
    if (r.available === false) {
      grid.innerHTML = addTile; return;
    }
    var tiles = (r.containers || []).map(function (c) {
      var labels = parseLabels(c.Labels || c.labels);
      var name = (c.Names || "").replace(/^\//, "");
      var cat = labels["forgeos.catalog"];
      var running = /running|up/i.test(c.State || "");
      var m = /(?:0\.0\.0\.0|\[::\]|):(\d+)->/.exec(c.Ports || "");
      var href = running && m ? "http://" + location.hostname + ":" + m[1] : "/apps.html";
      var icon = cat
        ? "<img src='/img/apps/" + esc(cat) + ".png' alt='' onerror=\"this.outerHTML='<svg viewBox=&quot;0 0 24 24&quot;><rect x=&quot;3&quot; y=&quot;6&quot; width=&quot;18&quot; height=&quot;12&quot; rx=&quot;2&quot;/></svg>'\">"
        : "<svg viewBox='0 0 24 24'><rect x='3' y='6' width='18' height='12' rx='2'/><path d='M7 10h2M11 10h2'/></svg>";
      return "<a class='appt" + (running ? "" : " off") + "' href='" + href + "'" +
        (running && m ? " target='_blank' rel='noopener'" : "") + "><i></i>" + icon +
        "<span>" + esc(cat ? cat.replace(/-/g, " ").replace(/\b\w/g, function (x) { return x.toUpperCase(); }) : name) + "</span></a>";
    });
    grid.innerHTML = tiles.join("") + addTile;
  }

  var VERB = { "docker.run": "created container", "docker.rm": "removed container",
    "docker.wipe": "wiped app", "docker.update": "updated", "docker.compose_down": "stopped compose stack",
    "samba.share.create": "created share", "samba.share.delete": "removed share",
    "data_connect.import": "imported database", "data_connect.register_server": "added server database",
    "auth.login": "signed in", "storage.snapshot": "created snapshot", "docker.settings": "changed app folder" };
  async function loadActivity() {
    var r = (await api("/api/audit?limit=8")).data;
    var box = $("#activity");
    if (r && r.entries && r.entries.length) {
      box.innerHTML = r.entries.map(function (e) {
        var t = e.timestamp ? new Date((String(e.timestamp).length > 12 ? e.timestamp : e.timestamp * 1000)) : null;
        var when = t ? t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
        var verb = VERB[e.action] || (e.action || "").replace(/[._]/g, " ");
        return "<div class='actrow'><time>" + esc(when) + "</time><div><b>" + esc(e.who || "system") +
          "</b> " + esc(verb) + (e.detail ? " \u2014 " + esc(String(e.detail).slice(0, 80)) : "") + "</div></div>";
      }).join("");
    } else { box.innerHTML = "<div class='vol-empty'>Nothing has happened yet.</div>"; }
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
          { value: "data-connect", label: "Data Connect (database share)" }, { value: "media", label: "Media" }, { value: "private", label: "Private" }
        ] }
      ],
      onSubmit: async function (v) {
        if (!v.name || !v.path) { toast("Name and path are required", "warn"); return false; }
        var r = await api("/api/samba/share", { method: "POST", body: JSON.stringify({ name: v.name, path: v.path, type: v.type, writable: true }) });
        toast(r.ok ? "Share created" : (r.data && r.data.detail) || "Share failed", r.ok ? "ok" : "err");
        if (r.ok) { refreshHeavy(); }
        return r.ok;
      }
    });
  }
  async function doProxyReload() {} // retired with the Quick Actions panel

  // ════════════ ORCHESTRATION ════════════
  function refreshHeavy() { loadIdentity(); loadStorage(); loadHealthMisc(); loadApps(); loadActivity(); }
  function refreshFast() { loadStats(); }
  var fastTimer, heavyTimer;
  function startPolling() {
    // seed the network baseline instantly so the sparkline has a delta on the
    // NEXT tick instead of blanking for a full interval after every refresh
    api("/api/system/stats").then(function (r) {
      var s = r.data; if (s && s.network) {
        netPrev = { recv: s.network.bytes_recv, sent: s.network.bytes_sent,
                    ts: s.timestamp || (Date.now() / 1000) };
      }
    });
    refreshFast(); refreshHeavy();
    clearInterval(fastTimer); clearInterval(heavyTimer);
    fastTimer = setInterval(refreshFast, 5000);
    heavyTimer = setInterval(refreshHeavy, 30000);
  }
  function stopPolling() { clearInterval(fastTimer); clearInterval(heavyTimer); }

  function tokenPayload() {
    try {
      var t = token(); if (!t) return null;
      return JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    } catch (e) { return null; }
  }
  function setIdentity(username, role) {
    var r = role === "admin" ? "Administrator" : "User";
    $("#profile-user").textContent = username;
    $("#profile-role").textContent = r;
    var amU = $("#am-user"), amR = $("#am-role");
    if (amU) amU.textContent = username;
    if (amR) amR.textContent = r;
    $("#avatar").textContent = (username[0] || "A").toUpperCase();
  }

  // ════════════ AUTH UI ════════════
  function showApp() { $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); }
  function showLogin() {
    try {
      if (sessionStorage.getItem("forge_session_expired")) {
        sessionStorage.removeItem("forge_session_expired");
        var e = document.getElementById("login-err");
        if (e) e.textContent = "Your session expired \u2014 please sign in again.";
      }
    } catch (x) {} $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); var u = $("#login-user"); if (u) u.focus(); }

  async function login() {
    var u = $("#login-user").value.trim(), p = $("#login-pass").value;
    var btn = $("#login-btn"), err = $("#login-err");
    err.textContent = "";
    if (!u || !p) { err.textContent = "Enter username and password."; return; }
    btn.disabled = true; btn.textContent = "Signing in…";
    var r = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: u, password: p }) });
    btn.disabled = false; btn.textContent = "Sign in";
    var d = r.data || {};
    if (r.ok && d.token) {
      setToken(d.token);
      setIdentity(d.username || u, d.role || "user");
      showApp(); startPolling();
    } else if (r.ok && d.mfa_required) {
      _mfaToken = d.mfa_token;
      loginStep("mfa");
      $("#mfa-code").focus();
    } else if (r.ok && d.enrollment_required) {
      _enrollToken = d.enroll_token;
      loginStep("enroll");
      startEnroll();
    } else {
      err.textContent = d.detail || "Login failed.";
    }
  }

  // ── 2FA login + forced enrollment ──
  var _mfaToken = null, _enrollToken = null;
  function loginStep(step) {
    // step: "creds" | "mfa" | "enroll"
    var creds = step === "creds";
    ["login-user", "login-pass"].forEach(function (id) {
      $("#" + id).closest(".field").classList.toggle("hidden", !creds);
    });
    $("#login-btn").classList.toggle("hidden", !creds);
    $("#login-mfa").classList.toggle("hidden", step !== "mfa");
    $("#login-enroll").classList.toggle("hidden", step !== "enroll");
  }
  async function mfaLogin() {
    var err = $("#login-err"); err.textContent = "";
    var code = $("#mfa-code").value.trim();
    if (!code) { err.textContent = "Enter a code."; return; }
    var r = await api("/api/auth/login/totp", { method: "POST",
      body: JSON.stringify({ mfa_token: _mfaToken, code: code }) });
    var d = r.data || {};
    if (r.ok && d.token) {
      _mfaToken = null; $("#mfa-code").value = "";
      setToken(d.token);
      setIdentity(d.username || $("#login-user").value.trim(), d.role || "user");
      loginStep("creds"); showApp(); startPolling();
    } else {
      err.textContent = d.detail || "Invalid code.";
    }
  }
  async function startEnroll() {
    var err = $("#login-err"); err.textContent = "";
    var r = await api("/api/users/me/totp/enroll", { method: "POST",
      headers: { Authorization: "Bearer " + _enrollToken } });
    var d = r.data || {};
    if (!r.ok) { err.textContent = d.detail || "Could not start enrollment."; return; }
    if (d.qr) { $("#enroll-qr").src = d.qr; $("#enroll-qr").style.display = ""; }
    else { $("#enroll-qr").style.display = "none"; }
    $("#enroll-secret").textContent = d.secret + "  (" + d.issuer + ")";
  }
  async function verifyEnroll() {
    var err = $("#login-err"); err.textContent = "";
    var code = $("#enroll-code").value.trim();
    if (!code) { err.textContent = "Enter the code from your app."; return; }
    var r = await api("/api/users/me/totp/verify", { method: "POST",
      headers: { Authorization: "Bearer " + _enrollToken },
      body: JSON.stringify({ code: code }) });
    var d = r.data || {};
    if (!r.ok) { err.textContent = d.detail || "Invalid code."; return; }
    _enrollToken = null;
    $("#enroll-codes").textContent = (d.backup_codes || []).join("\n");
    $("#enroll-done").classList.remove("hidden");
    $("#enroll-btn").classList.add("hidden");
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
    $("#mfa-btn").addEventListener("click", mfaLogin);
    $("#mfa-code").addEventListener("keydown", function (e) { if (e.key === "Enter") mfaLogin(); });
    $("#mfa-back").addEventListener("click", function () { _mfaToken = null; loginStep("creds"); });
    $("#enroll-btn").addEventListener("click", verifyEnroll);
    $("#enroll-relogin").addEventListener("click", function () {
      loginStep("creds");
      ["enroll-code", "login-pass"].forEach(function (id) { $("#" + id).value = ""; });
      $("#enroll-done").classList.add("hidden"); $("#enroll-btn").classList.remove("hidden");
      $("#login-err").textContent = "2FA enabled — sign in again with your code.";
    });
    var pl = tokenPayload();
    if (pl && pl.sub) setIdentity(pl.sub, pl.role || "user");
    $("#logout-btn").addEventListener("click", logout);
    [["#act-snapshot", doSnapshot], ["#act-share", doShare]].forEach(function (p) {
      var el = $(p[0]); if (el) el.addEventListener("click", p[1]);
    });
    // avatar menu (moved here from the deleted widgets.js)
    var pb = $("#profile-btn"), menu = $("#avatar-menu");
    if (pb && menu) {
      var setOpen = function (open) { menu.classList.toggle("open", open); pb.setAttribute("aria-expanded", String(open)); };
      pb.onclick = function (e) { if (e.target.closest("#logout-btn")) return; setOpen(!menu.classList.contains("open")); };
      pb.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(true); } if (e.key === "Escape") setOpen(false); };
      document.addEventListener("click", function (e) { if (!pb.contains(e.target)) setOpen(false); });
    }
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
