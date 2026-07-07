/* ForgeOS — Backup & DR. Jobs = existing backup_api routes; DR = GET/PUT only
 * (timer + run stay on the root CLI, boundary is stated on the page). */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function token() { try { return localStorage.getItem("forgeos_token"); } catch (e) { return null; } }
  async function api(p, o) {
    o = o || {};
    var h = Object.assign({}, o.headers || {});
    var t = token(); if (t) h.Authorization = "Bearer " + t;
    if (o.body && !h["Content-Type"]) h["Content-Type"] = "application/json";
    try {
      var r = await fetch(p, Object.assign({}, o, { headers: h }));
      var d = null; try { d = await r.json(); } catch (e) {}
      return { ok: r.ok, status: r.status, data: d };
    } catch (e) { return { ok: false, status: 0, data: null }; }
  }
  function toast(msg, kind) {
    var el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }
  function ago(iso) {
    if (!iso) return "\u2014";
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  function fmtBytes(n) {
    if (!n) return "0 B";
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (n < 10 && i ? n.toFixed(1) : Math.round(n)) + " " + u[i];
  }

  // ── tools ──
  async function loadTools() {
    var out = [];
    for (var t of ["borg", "restic", "rclone"]) {
      var r = await api("/api/backup/" + t + "/status");
      var ok = r.ok && r.data && r.data.installed;
      out.push('<span class="chip2 ' + (ok ? "ok" : "bad") + '">' + t + (ok ? "" : " missing") + "</span>");
    }
    $("#tool-chips").innerHTML = out.join("");
  }

  // ── jobs ──
  async function loadJobs() {
    var r = await api("/api/backup/jobs");
    if (!r.ok) { toast("Could not load jobs", "err"); return; }
    var jobs = (r.data && r.data.jobs) || [];
    $("#jobs-empty").style.display = jobs.length ? "none" : "";
    var rows = $("#job-rows");
    rows.innerHTML = "";
    jobs.forEach(function (j) {
      var st = j.last_status;
      var pill = st === "success" ? '<span class="pill ok">success</span>'
               : st === "failed"  ? '<span class="pill err">failed</span>'
               : st               ? '<span class="pill mut">' + esc(st) + "</span>"
                                  : '<span class="pill mut">never ran</span>';
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td style="font-weight:700">' + esc(j.name) +
          (j.enabled ? "" : ' <span class="note">(disabled)</span>') + "</td>" +
        "<td>" + esc(j.tool) + "</td>" +
        "<td>" + esc(j.schedule) + "</td>" +
        "<td>" + pill + ' <span class="note">' + ago(j.last_run) + "</span></td>" +
        '<td><div class="row-actions">' +
          '<button class="icon-btn" title="Run now" data-run="' + j.id + '">' +
            '<svg viewBox="0 0 24 24"><path d="M6 4l14 8-14 8z"/></svg></button>' +
          '<button class="icon-btn" title="' + (j.enabled ? "Disable" : "Enable") + '" data-toggle="' + j.id + '" data-en="' + j.enabled + '">' +
            '<svg viewBox="0 0 24 24"><rect x="3" y="8" width="18" height="8" rx="4"/></svg></button>' +
          '<button class="icon-btn danger" title="Delete" data-del="' + j.id + '" data-name="' + esc(j.name) + '">' +
            '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></button>' +
        "</div></td>";
      rows.appendChild(tr);
    });
  }

  $("#job-rows").onclick = async function (e) {
    var b = e.target.closest("button"); if (!b) return;
    var id, r;
    if ((id = b.getAttribute("data-run"))) {
      r = await api("/api/backup/jobs/" + id + "/run", { method: "POST" });
      if (!r.ok) { toast((r.data && r.data.detail) || "Run failed", "err"); return; }
      toast("Backup triggered", "ok");
      pollTasksWhileRunning();
    } else if ((id = b.getAttribute("data-toggle"))) {
      var next = b.getAttribute("data-en") !== "true";
      r = await api("/api/backup/jobs/" + id, { method: "PUT",
        body: JSON.stringify({ enabled: next }) });
      if (!r.ok) { toast((r.data && r.data.detail) || "Update failed", "err"); return; }
      loadJobs();
    } else if ((id = b.getAttribute("data-del"))) {
      if (!confirm('Delete job "' + b.getAttribute("data-name") + '"?')) return;
      r = await api("/api/backup/jobs/" + id, { method: "DELETE" });
      if (!r.ok) { toast((r.data && r.data.detail) || "Delete failed", "err"); return; }
      toast("Job deleted", "ok");
      loadJobs();
    }
  };

  // ── create modal ──
  var back = $("#job-backdrop");
  $("#add-job").onclick = function () {
    ["#j-name", "#j-src", "#j-dst"].forEach(function (s) { $(s).value = ""; });
    back.classList.add("show"); $("#j-name").focus();
  };
  $("#job-cancel").onclick = function () { back.classList.remove("show"); };
  $("#job-confirm").onclick = async function () {
    var src = $("#j-src").value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    var body = { name: $("#j-name").value.trim(), tool: $("#j-tool").value,
                 source: src, destination: $("#j-dst").value.trim(),
                 schedule: $("#j-sched").value };
    if (!body.name || !src.length || !body.destination) { toast("Name, source, destination required", "err"); return; }
    var r = await api("/api/backup/jobs", { method: "POST", body: JSON.stringify(body) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Create failed", "err"); return; }
    back.classList.remove("show");
    toast("Job created", "ok");
    loadJobs();
  };

  // ── DR panel ──
  var _dr = { enabled: false, cloud_sync: false };
  function drSwitch(id, on) { $(id).className = "switch" + (on ? " on" : ""); }
  async function loadDr() {
    var r = await api("/api/backup/dr");
    if (!r.ok) { toast("Could not load DR status", "err"); return; }
    var d = r.data;
    _dr.enabled = !!d.enabled; _dr.cloud_sync = !!d.cloud_sync;
    drSwitch("#dr-enabled", _dr.enabled);
    drSwitch("#dr-cloud", _dr.cloud_sync);
    $("#dr-remote-row").style.display = _dr.cloud_sync ? "" : "none";
    if (document.activeElement !== $("#dr-path")) $("#dr-path").value = d.backup_path || "";
    if (document.activeElement !== $("#dr-sched")) $("#dr-sched").value = d.schedule || "";
    if (document.activeElement !== $("#dr-remote")) $("#dr-remote").value = d.cloud_remote || "";
    var a = d.artifacts || {};
    var chips =
      chip(d.rear_installed, "rear installed", "rear missing") +
      chip(d.config_rendered, "config rendered", "config not rendered") +
      chip(d.timer_active, "timer active", "timer inactive") +
      (a.iso_bytes ? '<span class="chip2 ok">ISO ' + fmtBytes(a.iso_bytes) + "</span>" : '<span class="chip2">no ISO yet</span>') +
      (a.newest_iso_epoch ? '<span class="chip2">last: ' + ago(new Date(a.newest_iso_epoch * 1000).toISOString()) + "</span>" : "");
    $("#dr-chips").innerHTML = chips;
    // enabled-but-no-timer: surface the CLI step instead of pretending
    if (_dr.enabled && !d.timer_active) showCmd("sudo forgeos-osbackup enable");
  }
  function chip(ok, yes, no) {
    return '<span class="chip2 ' + (ok ? "ok" : "bad") + '">' + (ok ? yes : no) + "</span>";
  }
  function showCmd(cmd) {
    $("#dr-next").style.display = "";
    $("#dr-cmd").textContent = cmd;
  }
  $("#dr-enabled").onclick = function () { _dr.enabled = !_dr.enabled; drSwitch("#dr-enabled", _dr.enabled); };
  $("#dr-cloud").onclick = function () {
    _dr.cloud_sync = !_dr.cloud_sync;
    drSwitch("#dr-cloud", _dr.cloud_sync);
    $("#dr-remote-row").style.display = _dr.cloud_sync ? "" : "none";
  };
  $("#dr-save").onclick = async function () {
    var body = { enabled: _dr.enabled, backup_path: $("#dr-path").value.trim(),
                 schedule: $("#dr-sched").value.trim() || "weekly",
                 cloud_sync: _dr.cloud_sync, cloud_remote: $("#dr-remote").value.trim() };
    var r = await api("/api/backup/dr", { method: "PUT", body: JSON.stringify(body) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Save failed", "err"); return; }
    toast("DR config saved", "ok");
    if (r.data.next_command) showCmd(r.data.next_command);
    loadDr();
  };

  // ── tasks ──
  var _taskTimer = null;
  async function loadTasks() {
    var r = await api("/api/backup/tasks");
    if (!r.ok) return false;
    var tasks = ((r.data && r.data.tasks) || []).slice(0, 10);
    $("#tasks-empty").style.display = tasks.length ? "none" : "";
    var rows = $("#task-rows");
    rows.innerHTML = "";
    var running = false;
    tasks.forEach(function (t) {
      if (t.status === "running" || t.status === "pending") running = true;
      var pill = t.status === "success" ? "ok" : t.status === "failed" ? "err" : "mut";
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + esc(t.tool) + "</td><td>" + esc(t.action) + "</td>" +
        '<td><span class="pill ' + pill + '">' + esc(t.status) + "</span></td>" +
        '<td class="note">' + ago(new Date((t.started_at || 0) * 1000).toISOString()) + "</td>";
      rows.appendChild(tr);
    });
    return running;
  }
  async function pollTasksWhileRunning() {
    clearInterval(_taskTimer);
    _taskTimer = setInterval(async function () {
      if (document.hidden) return;
      var running = await loadTasks();
      if (!running) { clearInterval(_taskTimer); loadJobs(); }
    }, 4000);
  }

  $("#refresh").onclick = function () { loadTools(); loadJobs(); loadDr(); loadTasks(); };
  loadTools(); loadJobs(); loadDr();
  loadTasks().then(function (running) { if (running) pollTasksWhileRunning(); });
})();
