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
    var r = await api("/api/imaging");
    var d = (r.ok && r.data) || {};
    var chip = $("#state-chip");
    if (d.installed) {
      chip.textContent = d.running ? "Running · v" + d.version : "Installed, not running";
      chip.className = "chip2 " + (d.running ? "ok" : "");
      $("#open-ui").href = d.url;
      $("#installed-card").style.display = "";
    } else {
      chip.textContent = "Not installed";
      chip.className = "chip2";
      $("#absent-card").style.display = "";
    }
  }
  load();
})();
