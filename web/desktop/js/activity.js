/* ForgeOS — Activity Log. One backend route (/api/audit); filters and
 * pagination are passed through, never re-implemented client-side. */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function token() { try { return localStorage.getItem("forgeos_token"); } catch (e) { return null; } }
  async function api(p) {
    var h = {};
    var t = token(); if (t) h.Authorization = "Bearer " + t;
    try {
      var r = await fetch(p, { headers: h });
      var d = null; try { d = await r.json(); } catch (e) {}
      return { ok: r.ok, data: d };
    } catch (e) { return { ok: false, data: null }; }
  }
  function rel(iso) {
    var t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    var s = (Date.now() - t) / 1000;
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }

  var LIMIT = 50, _offset = 0, _total = 0;

  async function load() {
    var qs = "limit=" + LIMIT + "&offset=" + _offset;
    var who = $("#f-who").value.trim(), action = $("#f-action").value.trim();
    if (who) qs += "&who=" + encodeURIComponent(who);
    if (action) qs += "&action=" + encodeURIComponent(action);
    var r = await api("/api/audit?" + qs);
    if (!r.ok) return;
    var d = r.data;
    _total = d.total || 0;
    var rows = $("#rows");
    rows.innerHTML = "";
    $("#empty").style.display = (d.entries || []).length ? "none" : "";
    (d.entries || []).forEach(function (e) {
      var pill = e.status === "success" ? "ok" : e.status === "failure" ? "err" : "mut";
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td class="ts">' + esc((e.timestamp || "").replace("T", " ").slice(0, 19)) +
          ' <span class="rel">' + rel(e.timestamp) + "</span></td>" +
        '<td style="font-weight:700">' + esc(e.who) + "</td>" +
        '<td class="mono">' + esc(e.action) + "</td>" +
        '<td><span class="pill ' + pill + '">' + esc(e.status) + "</span></td>" +
        '<td class="detail">' + esc(e.detail) + "</td>";
      rows.appendChild(tr);
    });
    var from = _total ? _offset + 1 : 0;
    var to = Math.min(_offset + LIMIT, _total);
    $("#pageinfo").textContent = from + "\u2013" + to + " of " + _total;
    $("#prev").disabled = _offset === 0;
    $("#next").disabled = to >= _total;
  }

  $("#f-apply").onclick = function () { _offset = 0; load(); };
  $("#f-clear").onclick = function () {
    $("#f-who").value = ""; $("#f-action").value = "";
    _offset = 0; load();
  };
  ["#f-who", "#f-action"].forEach(function (s) {
    $(s).addEventListener("keydown", function (e) { if (e.key === "Enter") { _offset = 0; load(); } });
  });
  $("#prev").onclick = function () { _offset = Math.max(0, _offset - LIMIT); load(); };
  $("#next").onclick = function () { _offset += LIMIT; load(); };
  $("#refresh").onclick = load;

  load();
})();
