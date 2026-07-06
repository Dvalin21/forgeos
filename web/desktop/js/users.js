/* ForgeOS — Users (admin): CRUD, roles, password reset, 2FA reset, auth policy.
 * Self-service (own password/2FA) lives in profile.html. The API enforces
 * last-admin and self-delete guards; this UI just surfaces its answers.
 */
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
  function payload() {
    try { return JSON.parse(atob(token().split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); }
    catch (e) { return null; }
  }

  var pl = payload();
  if (!pl || !pl.sub) { location.href = "/index.html"; return; }
  var me = pl.sub;

  // ── list ──
  async function load() {
    var r = await api("/api/users");
    if (r.status === 403) {
      document.querySelector("main").innerHTML =
        '<section class="panel pad"><h3>Admin only</h3>' +
        '<p style="color:var(--muted)">User management requires an administrator account. ' +
        'Your own password and 2FA are on <a href="/profile.html">your profile</a>.</p></section>';
      return;
    }
    if (!r.ok) { toast("Could not load users", "err"); return; }
    var rows = $("#user-rows");
    rows.innerHTML = "";
    (r.data.users || []).forEach(function (u) {
      var tr = document.createElement("tr");
      var mfa = u.totp_enabled
        ? '<span class="pill on">Enabled</span>'
        : (u.totp_required ? '<span class="pill off">Enrollment pending</span>'
                           : '<span class="pill off">Off</span>');
      tr.innerHTML =
        '<td style="font-weight:700">' + esc(u.username) + (u.username === me ? ' <span class="note">(you)</span>' : "") + "</td>" +
        '<td>' + (u.role === "admin" ? "Administrator" : "User") + "</td>" +
        "<td>" + mfa + "</td>" +
        '<td class="note">' + (u.totp_enabled ? u.backup_codes_remaining + " left" : "\u2014") + "</td>" +
        '<td><div class="row-actions">' +
          '<button class="icon-btn" title="' + (u.role === "admin" ? "Demote to user" : "Promote to admin") + '" data-role="' + esc(u.username) + '" data-cur="' + esc(u.role) + '">' +
            '<svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.8-2.9 8.2-7 10-4.1-1.8-7-5.2-7-10V6z"/></svg></button>' +
          '<button class="icon-btn" title="Reset password" data-pw="' + esc(u.username) + '">' +
            '<svg viewBox="0 0 24 24"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></button>' +
          '<button class="icon-btn" title="Reset 2FA (lost device)" data-totp="' + esc(u.username) + '">' +
            '<svg viewBox="0 0 24 24"><path d="M12 5v3M12 16h.01"/><circle cx="12" cy="12" r="9"/></svg></button>' +
          '<button class="icon-btn danger" title="Delete" data-del="' + esc(u.username) + '">' +
            '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></button>' +
        "</div></td>";
      rows.appendChild(tr);
    });
  }

  // ── policy switch (existing .switch component pattern) ──
  var _policy = false;
  function renderPolicy() { $("#policy-2fa").className = "switch" + (_policy ? " on" : ""); }
  async function loadPolicy() {
    var r = await api("/api/auth/policy");
    if (r.ok) { _policy = !!r.data.require_totp_new_users; renderPolicy(); }
  }
  $("#policy-2fa").onclick = async function () {
    var next = !_policy;
    var r = await api("/api/auth/policy", { method: "PUT",
      body: JSON.stringify({ require_totp_new_users: next }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Could not save policy", "err"); return; }
    _policy = next; renderPolicy();
    toast(next ? "New accounts must enroll 2FA" : "2FA optional for new accounts", "ok");
  };

  // ── create ──
  var addBack = $("#add-backdrop");
  $("#add-user").onclick = function () {
    ["#u-name", "#u-pass"].forEach(function (s) { $(s).value = ""; });
    $("#u-role").value = "user";
    addBack.classList.add("show");
    $("#u-name").focus();
  };
  $("#add-cancel").onclick = function () { addBack.classList.remove("show"); };
  $("#add-confirm").onclick = async function () {
    var body = { username: $("#u-name").value.trim(), password: $("#u-pass").value, role: $("#u-role").value };
    if (!body.username || !body.password) { toast("Username and password required", "err"); return; }
    var r = await api("/api/users", { method: "POST", body: JSON.stringify(body) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Create failed", "err"); return; }
    addBack.classList.remove("show");
    toast('User "' + body.username + '" created', "ok");
    load();
  };

  // ── password reset modal ──
  var pwBack = $("#pw-backdrop"), pwUser = null;
  function openPw(name) {
    pwUser = name;
    $("#pw-title").textContent = 'Reset password — ' + name;
    $("#pw-new").value = "";
    pwBack.classList.add("show");
    $("#pw-new").focus();
  }
  $("#pw-cancel").onclick = function () { pwBack.classList.remove("show"); };
  $("#pw-confirm").onclick = async function () {
    var pw = $("#pw-new").value;
    if (!pw) { toast("Enter a new password", "err"); return; }
    var r = await api("/api/users/" + encodeURIComponent(pwUser) + "/password",
      { method: "POST", body: JSON.stringify({ password: pw }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Reset failed", "err"); return; }
    pwBack.classList.remove("show");
    toast("Password reset for " + pwUser, "ok");
  };

  // ── row actions ──
  $("#user-rows").onclick = async function (e) {
    var b = e.target.closest("button"); if (!b) return;
    var name, r;
    if ((name = b.getAttribute("data-role"))) {
      var next = b.getAttribute("data-cur") === "admin" ? "user" : "admin";
      if (!confirm('Change role of "' + name + '" to ' + next + "?")) return;
      r = await api("/api/users/" + encodeURIComponent(name) + "/role",
        { method: "PUT", body: JSON.stringify({ role: next }) });
      if (!r.ok) { toast((r.data && r.data.detail) || "Role change failed", "err"); return; }
      toast(name + " is now " + next, "ok"); load();
    } else if ((name = b.getAttribute("data-pw"))) {
      openPw(name);
    } else if ((name = b.getAttribute("data-totp"))) {
      if (!confirm('Reset 2FA for "' + name + '"? They can sign in with password only until they re-enroll.')) return;
      r = await api("/api/users/" + encodeURIComponent(name) + "/totp", { method: "DELETE" });
      if (!r.ok) { toast((r.data && r.data.detail) || "2FA reset failed", "err"); return; }
      toast("2FA reset for " + name, "ok"); load();
    } else if ((name = b.getAttribute("data-del"))) {
      if (!confirm('Delete user "' + name + '"? This cannot be undone.')) return;
      r = await api("/api/users/" + encodeURIComponent(name), { method: "DELETE" });
      if (!r.ok) { toast((r.data && r.data.detail) || "Delete failed", "err"); return; }
      toast('User "' + name + '" deleted', "ok"); load();
    }
  };

  load(); loadPolicy();
})();
