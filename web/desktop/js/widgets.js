/* ForgeOS — dashboard widgets + avatar menu.
 * Show/hide + per-column reorder of dashboard sections ([data-widget]),
 * persisted to localStorage. Lean defaults: overview widgets on, the
 * tables that duplicate dedicated pages off.
 * ponytail: per-browser localStorage; server-side per-user prefs only if asked.
 * ponytail: reorder is within a widget's own column (CSS order) — cross-column
 * moves need markup surgery, not worth it.
 */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };

  var REG = [
    { id: "hero",     label: "System status (hero)",  on: true  },
    { id: "health",   label: "Health Center",         on: true  },
    { id: "metrics",  label: "Metric cards",          on: true  },
    { id: "storage",  label: "Storage Manager",       on: true  },
    { id: "files",    label: "File Station (shares)", on: false },
    { id: "services", label: "Apps & Services",       on: false },
    { id: "quick",    label: "Quick Actions",         on: false },
    { id: "backup",   label: "Backup Jobs",           on: false },
    { id: "activity", label: "Activity Log",          on: false }
  ];
  var KEY = "forgeos_widgets";

  function load() {
    try { var s = JSON.parse(localStorage.getItem(KEY)); if (s && s.off && s.order) return s; } catch (e) {}
    return { off: REG.filter(function (w) { return !w.on; }).map(function (w) { return w.id; }), order: {} };
  }
  function save(st) { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} }

  function apply(st) {
    REG.forEach(function (w, i) {
      var el = $('[data-widget="' + w.id + '"]');
      if (!el) return;
      el.classList.toggle("w-off", st.off.indexOf(w.id) !== -1);
      el.style.order = st.order[w.id] != null ? st.order[w.id] : i;
      var col = el.parentElement;
      if (col && !col.style.display) { col.style.display = "flex"; col.style.flexDirection = "column"; }
    });
  }

  var EYE = '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/></svg>';
  var UP = '<svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  var DOWN = '<svg viewBox="0 0 24 24"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>';

  function siblings(id) {
    // widget ids sharing the same DOM column, in registry order
    var el = $('[data-widget="' + id + '"]'); if (!el) return [id];
    return REG.map(function (w) { return w.id; }).filter(function (wid) {
      var e = $('[data-widget="' + wid + '"]');
      return e && e.parentElement === el.parentElement;
    });
  }

  function customize() {
    var st = load();
    var back = document.createElement("div"); back.className = "modal-back";
    back.innerHTML = '<div class="modal"><h3>Customize dashboard</h3>' +
      '<p class="sub">Choose which widgets show and their order. Hidden data stays one click away on its own page.</p>' +
      '<div id="w-list"></div>' +
      '<div style="display:flex;gap:10px;justify-content:space-between;margin-top:16px">' +
      '<button class="btn-ghost" data-reset>Reset to defaults</button>' +
      '<button class="btn-pri" data-x>Done</button></div></div>';
    document.body.appendChild(back);

    function orderOf(id) { var i = REG.findIndex(function (w) { return w.id === id; }); return st.order[id] != null ? st.order[id] : i; }
    function render() {
      $("#w-list", back).innerHTML = REG.slice().sort(function (a, b) { return orderOf(a.id) - orderOf(b.id); })
        .map(function (w) {
          var on = st.off.indexOf(w.id) === -1;
          return '<div class="wz-widget-row" data-wrow="' + w.id + '">' +
            '<button class="w-eye' + (on ? " on" : "") + '" data-weye="' + w.id + '" title="' + (on ? "Hide" : "Show") + '" aria-pressed="' + on + '">' + EYE + '</button>' +
            '<h5>' + w.label + '</h5>' +
            '<div class="w-arrows"><button data-wup="' + w.id + '" title="Move up">' + UP + '</button>' +
            '<button data-wdn="' + w.id + '" title="Move down">' + DOWN + '</button></div></div>';
        }).join("");
      $$("[data-weye]", back).forEach(function (b) {
        b.onclick = function () {
          var id = b.getAttribute("data-weye"), i = st.off.indexOf(id);
          if (i === -1) st.off.push(id); else st.off.splice(i, 1);
          save(st); apply(st); render();
        };
      });
      function mover(attr, dir) {
        $$("[" + attr + "]", back).forEach(function (b) {
          b.onclick = function () {
            var id = b.getAttribute(attr), sibs = siblings(id).sort(function (a, c) { return orderOf(a) - orderOf(c); });
            var i = sibs.indexOf(id), j = i + dir;
            if (j < 0 || j >= sibs.length) return;
            var a = orderOf(sibs[i]), c = orderOf(sibs[j]);
            st.order[sibs[i]] = c; st.order[sibs[j]] = a;
            save(st); apply(st); render();
          };
        });
      }
      mover("data-wup", -1); mover("data-wdn", 1);
    }
    render();
    back.addEventListener("click", function (e) {
      if (e.target === back || e.target.hasAttribute("data-x")) back.remove();
      if (e.target.hasAttribute("data-reset")) { st = { off: REG.filter(function (w) { return !w.on; }).map(function (w) { return w.id; }), order: {} }; save(st); apply(st); render(); }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    apply(load());
    var cb = $("#customize-btn"); if (cb) cb.onclick = customize;
    // avatar menu
    var pb = $("#profile-btn"), menu = $("#avatar-menu");
    if (pb && menu) {
      var setOpen = function (open) { menu.classList.toggle("open", open); pb.setAttribute("aria-expanded", String(open)); };
      // onclick property, not addEventListener: idempotent if this script ever
      // runs twice (hot reload) — a duplicated listener would re-toggle closed.
      pb.onclick = function (e) {
        if (e.target.closest("#logout-btn")) return;           // let index.js logout run
        setOpen(!menu.classList.contains("open"));
      };
      pb.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(true); } if (e.key === "Escape") setOpen(false); };
      document.addEventListener("click", function (e) { if (!pb.contains(e.target)) setOpen(false); });
      // mirror identity into the menu header
      var mu = $("#am-user"), mr = $("#am-role"), pu = $("#profile-user"), pr = $("#profile-role");
      if (mu && pu) new MutationObserver(function () { mu.textContent = pu.textContent; }).observe(pu, { childList: true, characterData: true, subtree: true });
      if (mr && pr) new MutationObserver(function () { mr.textContent = pr.textContent; }).observe(pr, { childList: true, characterData: true, subtree: true });
    }
  });
})();
