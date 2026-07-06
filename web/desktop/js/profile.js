/* ForgeOS — My Profile: password change + own 2FA lifecycle.
 * Self-service only; admin user management lives in users.html.
 */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
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
  $("#pf-user").textContent = me;
  $("#pf-role").textContent = pl.role === "admin" ? "Administrator" : "User";
  $("#pf-avatar").textContent = (me[0] || "?").toUpperCase();

  async function loadMfaState() {
    var r = await api("/api/users/me");
    if (!r.ok) { toast("Could not load your account", "err"); return; }
    render(!!r.data.totp_enabled, r.data.backup_codes_remaining);
  }
  function render(enabled, codesLeft) {
    var chip = $("#mfa-chip");
    chip.textContent = enabled ? "Enabled" : "Not enabled";
    if (enabled) chip.style.color = "var(--ok, #16a34a)";
    $("#mfa-codes-left").textContent =
      enabled && codesLeft != null ? codesLeft + " backup codes left" : "";
    $("#mfa-off").classList.toggle("hidden", enabled);
    $("#mfa-on").classList.toggle("hidden", !enabled);
  }

  // ── change password ──
  $("#cp-btn").onclick = async function () {
    var cur = $("#cp-cur").value, nw = $("#cp-new").value, nw2 = $("#cp-new2").value;
    if (!cur || !nw) { toast("Fill in all fields", "err"); return; }
    if (nw !== nw2) { toast("New passwords do not match", "err"); return; }
    var r = await api("/api/auth/change-password", { method: "POST",
      body: JSON.stringify({ current: cur, new: nw }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Change failed", "err"); return; }
    ["#cp-cur", "#cp-new", "#cp-new2"].forEach(function (s) { $(s).value = ""; });
    toast("Password changed", "ok");
  };

  // ── enroll ──
  $("#mfa-enroll-btn").onclick = async function () {
    var r = await api("/api/users/me/totp/enroll", { method: "POST" });
    if (!r.ok) { toast((r.data && r.data.detail) || "Could not start enrollment", "err"); return; }
    var d = r.data;
    if (d.qr) { $("#mfa-qr").src = d.qr; $("#mfa-qr").style.display = ""; }
    else { $("#mfa-qr").style.display = "none"; }
    $("#mfa-secret").textContent = d.secret + "  (" + d.issuer + ")";
    $("#mfa-wizard").classList.remove("hidden");
    $("#mfa-verify-code").focus();
  };
  $("#mfa-verify-btn").onclick = async function () {
    var code = $("#mfa-verify-code").value.trim();
    if (!code) { toast("Enter the code from your app", "err"); return; }
    var r = await api("/api/users/me/totp/verify", { method: "POST",
      body: JSON.stringify({ code: code }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Invalid code", "err"); return; }
    showBackupCodes(r.data.backup_codes);
    $("#mfa-wizard").classList.add("hidden");
    toast("2FA enabled", "ok");
    render(true, (r.data.backup_codes || []).length);
  };

  // ── regenerate backup codes (re-auth: current code) ──
  $("#mfa-regen-btn").onclick = async function () {
    var code = $("#mfa-reauth-code").value.trim();
    if (!code) { toast("Enter a current code first", "err"); return; }
    var r = await api("/api/users/me/totp/backup-codes", { method: "POST",
      body: JSON.stringify({ code: code }) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Failed", "err"); return; }
    $("#mfa-reauth-code").value = "";
    showBackupCodes(r.data.backup_codes);
    toast("Backup codes regenerated — old ones are dead", "ok");
    render(true, (r.data.backup_codes || []).length);
  };

  // ── disable (re-auth: code, or password fallback) ──
  $("#mfa-disable-btn").onclick = async function () {
    var body = {};
    var code = $("#mfa-reauth-code").value.trim();
    if (code) body.code = code;
    else {
      var pw = prompt("No code entered. Confirm with your password to disable 2FA:");
      if (!pw) return;
      body.password = pw;
    }
    if (!confirm("Disable two-factor authentication? Your backup codes are destroyed.")) return;
    var r = await api("/api/users/me/totp/disable", { method: "POST",
      body: JSON.stringify(body) });
    if (!r.ok) { toast((r.data && r.data.detail) || "Failed", "err"); return; }
    $("#mfa-reauth-code").value = "";
    $("#mfa-backup").classList.add("hidden");
    toast("2FA disabled", "ok");
    render(false, null);
  };

  function showBackupCodes(codes) {
    $("#mfa-backup-list").textContent = (codes || []).join("\n");
    $("#mfa-backup").classList.remove("hidden");
  }

  loadMfaState();
})();
