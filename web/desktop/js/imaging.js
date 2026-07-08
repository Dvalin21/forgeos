/* ForgeOS — Imaging: UrBackup app state + pointers. All real operations live
 * in UrBackup's own UI; ForgeOS only runs and links it. */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function token() { try { return localStorage.getItem("forgeos_token"); } catch (e) { return null; } }
  async function api(p) {
    var h = {};
    var t = token(); if (t) h.Authorization = "Bearer " + t;
    try {
      var r = await fetch(p, { headers: h });
      return { ok: r.ok, data: await r.json() };
    } catch (e) { return { ok: false, data: null }; }
  }
  async function load() {
    var r = await api("/api/apps");
    var app = r.ok ? (r.data.apps || []).find(function (a) { return a.id === "urbackup"; }) : null;
    var chip = $("#state-chip");
    if (app) {
      chip.textContent = "Installed" + (app.enabled ? "" : " (disabled)");
      chip.className = "chip2 ok";
      $("#open-ui").href = app.url;
      $("#installed-card").style.display = "";
    } else {
      chip.textContent = "Not installed";
      chip.className = "chip2";
      $("#absent-card").style.display = "";
    }
  }
  load();
})();
