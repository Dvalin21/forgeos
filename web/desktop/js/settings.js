/* ForgeOS — Settings: system identity/timezone + SMTP notifications. */
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

  // ── system ──
  async function loadSys() {
    var r = await api("/api/settings");
    if (r.status === 403) { toast("Admin required for settings", "err"); return; }
    if (!r.ok) { toast("Could not load settings", "err"); return; }
    var d = r.data;
    $("#sys-info").innerHTML =
      '<div class="kv"><span class="k">Hostname</span><span>' + esc(d.effective_hostname) + "</span></div>" +
      '<div class="kv"><span class="k">Version</span><span>' + esc(d.version || "unknown") + "</span></div>";
    if (document.activeElement !== $("#s-lan")) $("#s-lan").value = d.lan_name || "";
    if (document.activeElement !== $("#s-fqdn")) $("#s-fqdn").value = d.public_fqdn || "";
    if (document.activeElement !== $("#s-tz")) $("#s-tz").value = d.timezone || "";
  }
  $("#s-save").onclick = async function () {
    var r = await api("/api/settings", { method: "PUT", body: JSON.stringify({
      lan_name: $("#s-lan").value.trim(),
      public_fqdn: $("#s-fqdn").value.trim(),
      timezone: $("#s-tz").value.trim()
    }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Save failed", "err"); return; }
    toast("System settings saved", "ok");
    loadSys();
  };

  // ── smtp ──
  var _m = { enabled: false, use_tls: true };
  function sw(id, on) { $(id).className = "switch" + (on ? " on" : ""); }
  async function loadSmtp() {
    var r = await api("/api/settings/smtp");
    if (!r.ok) return;
    var d = r.data;
    _m.enabled = !!d.enabled; _m.use_tls = !!d.use_tls;
    sw("#m-enabled", _m.enabled); sw("#m-tls", _m.use_tls);
    $("#smtp-chip").textContent = _m.enabled ? "Enabled" : "Disabled";
    $("#smtp-chip").className = "chip2" + (_m.enabled ? " ok" : "");
    $("#m-pw-state").textContent = d.password_set ? "(set)" : "(not set)";
    var map = { "#m-host": d.host, "#m-user": d.username, "#m-from": d.from_addr,
                "#m-port": d.port, "#m-to": (d.to_addrs || []).join(", ") };
    Object.keys(map).forEach(function (sel) {
      if (document.activeElement !== $(sel)) $(sel).value = map[sel] == null ? "" : map[sel];
    });
  }
  $("#m-enabled").onclick = function () { _m.enabled = !_m.enabled; sw("#m-enabled", _m.enabled); };
  $("#m-tls").onclick = function () { _m.use_tls = !_m.use_tls; sw("#m-tls", _m.use_tls); };
  $("#m-save").onclick = async function () {
    var body = {
      enabled: _m.enabled, use_tls: _m.use_tls, use_ssl: !_m.use_tls && Number($("#m-port").value) === 465,
      host: $("#m-host").value.trim(), port: Number($("#m-port").value) || 587,
      username: $("#m-user").value.trim(), from_addr: $("#m-from").value.trim(),
      to_addrs: $("#m-to").value.split(",").map(function (x) { return x.trim(); }).filter(Boolean)
    };
    var pw = $("#m-pass").value;
    if (pw) body.password = pw;
    var r = await api("/api/settings/smtp", { method: "PUT", body: JSON.stringify(body) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Save failed", "err"); return; }
    $("#m-pass").value = "";
    toast("SMTP settings saved", "ok");
    loadSmtp();
  };
  $("#m-test").onclick = async function () {
    var b = this; b.disabled = true;
    var r = await api("/api/settings/smtp/test", { method: "POST" });
    b.disabled = false;
    if (!r.ok) { toast((r.data && r.data.detail) || "Test failed", "err"); return; }
    toast("Test email sent — check the inbox", "ok");
  };

  loadSys(); loadSmtp();
})();
