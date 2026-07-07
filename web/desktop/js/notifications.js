/* ForgeOS — Notifications page. */
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
      return { ok: r.ok, data: d };
    } catch (e) { return { ok: false, data: null }; }
  }
  function toast(msg, kind) {
    var el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }
  function ago(epoch) {
    var s = Date.now() / 1000 - epoch;
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  function row(level, title, message, ts) {
    return '<div class="n-row"><span class="lvl ' + esc(level) + '">' + esc(level) + "</span>" +
      '<div class="n-body"><h5>' + esc(title) + "</h5>" +
      (message ? "<p>" + esc(message) + "</p>" : "") + "</div>" +
      '<span class="n-ts">' + ago(ts) + "</span></div>";
  }

  async function load() {
    var r = await api("/api/notifications");
    if (r.ok) {
      var ns = r.data.notifications || [];
      $("#n-empty").style.display = ns.length ? "none" : "";
      $("#n-list").innerHTML = ns.map(function (n) {
        return row(n.level, n.title, n.message, n.ts);
      }).join("");
    }
    var d = await api("/api/drive-alerts");
    if (d.ok) {
      var keys = Object.keys(d.data.alerts || {});
      $("#d-empty").style.display = keys.length ? "none" : "";
      $("#d-list").innerHTML = keys.map(function (dev) {
        var a = d.data.alerts[dev];
        return row(a.level, dev, a.message, a.ts);
      }).join("");
    }
  }

  $("#test").onclick = async function () {
    var r = await api("/api/notify", { method: "POST", body: JSON.stringify({
      level: "warning", title: "Test notification",
      message: "Sent from the Notifications page. Warnings also go to SMTP if configured." }) });
    if (!r.ok) { toast("Failed", "err"); return; }
    toast("Test sent — warnings also email if SMTP is on", "ok");
    load();
  };
  $("#refresh").onclick = load;
  load();
  setInterval(function () { if (!document.hidden) load(); }, 15000);
})();
