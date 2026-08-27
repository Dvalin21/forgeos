/* ForgeOS — Setup Wizard */
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function $$(s) { return [].slice.call(document.querySelectorAll(s)); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
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

  var _state = {
    network: { interface: "", address: "", prefixlen: 24, gateway: "", dns: "" },
    system: { hostname: "", lan_name: "", timezone: "" },
    os_drive: "",
    lhsr_groups: [],
    snapshots: { enabled: true, calendar: "daily" },
  };

  var _interfaces = [];
  var _disks = [];
  var _timezones = [];

  // ── step navigation ──
  function goStep(n) {
    $$(".wizard-panel").forEach(function (p) { p.classList.remove("active"); });
    $$(".wizard-panel[data-panel=\"" + n + "\"]").forEach(function (p) { p.classList.add("active"); });
    $$("#wizard-steps .step").forEach(function (s) {
      var sn = parseInt(s.getAttribute("data-step"), 10);
      s.classList.remove("active", "done");
      if (sn < n) s.classList.add("done");
      if (sn === n) s.classList.add("active");
    });
  }

  $("[data-prev]").forEach(function (b) {
    b.onclick = function () {
      var cur = parseInt($(".wizard-panel.active").getAttribute("data-panel"), 10);
      if (cur > 1) goStep(cur - 1);
    };
  });

  // ── step 1: network ──
  async function loadNetwork() {
    var r = await api("/api/setup/network-interfaces");
    if (!r.ok) return;
    _interfaces = (r.data && r.data.interfaces) || [];
    var sel = $("#net-iface");
    sel.innerHTML = _interfaces.map(function (i) {
      return '<option value="' + esc(i.name) + '">' + esc(i.name) + ' (' + esc(i.mac || "no MAC") + ')</option>';
    }).join("");
    if (_interfaces.length) {
      _state.network.interface = _interfaces[0].name;
    }
    sel.onchange = function () { _state.network.interface = sel.value; };
  }

  $("#net-next").onclick = function () {
    _state.network.interface = $("#net-iface").value;
    _state.network.address = $("#net-ip").value.trim();
    _state.network.prefixlen = parseInt($("#net-prefix").value, 10) || 24;
    _state.network.gateway = $("#net-gw").value.trim();
    _state.network.dns = $("#net-dns").value.trim();
    if (!_state.network.address) { toast("IP address required", "warn"); return; }
    goStep(2);
  };

  // ── step 2: system ──
  async function loadSystem() {
    var r = await api("/api/setup/timezones");
    if (!r.ok) return;
    _timezones = (r.data && r.data.timezones) || [];
    var sel = $("#sys-tz");
    sel.innerHTML = _timezones.map(function (tz) {
      return '<option value="' + esc(tz) + '">' + esc(tz) + '</option>';
    }).join("");
    // Try to guess America/Chicago as default
    var chicago = _timezones.find(function (t) { return t === "America/Chicago"; });
    if (chicago) sel.value = chicago;
    _state.system.timezone = sel.value;
    sel.onchange = function () { _state.system.timezone = sel.value; };
  }

  $("#sys-next").onclick = function () {
    _state.system.hostname = $("#sys-hostname").value.trim();
    _state.system.lan_name = $("#sys-lan").value.trim();
    _state.system.timezone = $("#sys-tz").value;
    if (!_state.system.hostname) { toast("Hostname required", "warn"); return; }
    if (!_state.system.timezone) { toast("Timezone required", "warn"); return; }
    goStep(3);
  };

  // ── step 3: OS drive ──
  async function loadDisks() {
    var r = await api("/api/setup/disks");
    if (!r.ok) return;
    _disks = (r.data && r.data.disks) || [];
    var list = $("#os-drive-list");
    list.innerHTML = _disks.map(function (d) {
      var gb = (d.size_bytes / (1024 * 1024 * 1024)).toFixed(1);
      var tag = d.is_system ? ' <span style="color:var(--primary)">(current OS)</span>' : '';
      return '<div class="disk-option" data-path="' + esc(d.path) + '">' +
        '<input type="radio" name="os-drive" value="' + esc(d.path) + '">' +
        '<div><strong>' + esc(d.path) + '</strong>' + tag +
        '<div class="size">' + gb + ' GB</div></div></div>';
    }).join("");
    $$("#os-drive-list .disk-option").forEach(function (opt) {
      opt.onclick = function () {
        $$("#os-drive-list .disk-option").forEach(function (o) { o.classList.remove("selected"); });
        opt.classList.add("selected");
        opt.querySelector("input").checked = true;
        _state.os_drive = opt.getAttribute("data-path");
      };
    });
    // Pre-select system disk
    var sysDisk = _disks.find(function (d) { return d.is_system; });
    if (sysDisk) {
      var opt = $('.disk-option[data-path="' + sysDisk.path + '"]');
      if (opt) opt.click();
    }
  }

  $("#os-next").onclick = function () {
    if (!_state.os_drive) { toast("Select an OS drive", "warn"); return; }
    loadLhsrGroups();
    goStep(4);
  };

  // ── step 4: LHSR groups ──
  function loadLhsrGroups() {
    var available = _disks.filter(function (d) { return d.path !== _state.os_drive; });
    var container = $("#lhsr-groups");

    if (!_state.lhsr_groups.length) {
      _state.lhsr_groups = [{ name: "tank", parity: 1, disks: [] }];
    }

    renderGroups(available);
  }

  function renderGroups(available) {
    var container = $("#lhsr-groups");
    container.innerHTML = _state.lhsr_groups.map(function (g, gi) {
      var assigned = g.disks;
      var free = available.filter(function (d) { return assigned.indexOf(d.path) === -1; });
      var gb = function (path) {
        var d = _disks.find(function (x) { return x.path === path; });
        return d ? (d.size_bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB" : "";
      };
      return '<div class="group-card">' +
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<h4>Group ' + (gi + 1) + '</h4>' +
        (_state.lhsr_groups.length > 1 ? '<button class="btn-ghost" data-remove-group="' + gi + '" style="height:30px;font-size:11px">Remove</button>' : '') +
        '</div>' +
        '<div class="field"><label>Group Name</label><input class="group-name" data-idx="' + gi + '" value="' + esc(g.name) + '" placeholder="tank"></div>' +
        '<label style="font-size:12px;font-weight:700;color:var(--muted)">Redundancy</label>' +
        '<div class="parity-select">' +
        '<button class="' + (g.parity === 1 ? 'active' : '') + '" data-parity="1" data-idx="' + gi + '">LHSR1 (single parity)</button>' +
        '<button class="' + (g.parity === 2 ? 'active' : '') + '" data-parity="2" data-idx="' + gi + '">LHSR2 (dual parity)</button>' +
        '</div>' +
        '<label style="font-size:12px;font-weight:700;color:var(--muted);margin-top:8px">Disks</label>' +
        '<div class="disk-select">' +
        assigned.map(function (p) {
          return '<div class="disk-option selected" data-path="' + esc(p) + '">' +
            '<input type="checkbox" checked value="' + esc(p) + '">' +
            '<div><strong>' + esc(p) + '</strong><div class="size">' + gb(p) + '</div></div></div>';
        }).join("") +
        free.map(function (d) {
          return '<div class="disk-option" data-path="' + esc(d.path) + '">' +
            '<input type="checkbox" value="' + esc(d.path) + '">' +
            '<div><strong>' + esc(d.path) + '</strong><div class="size">' + (d.size_bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB</div></div></div>';
        }).join("") +
        '</div></div>';
    }).join("");

    // Wire up events
    $$(".group-name").forEach(function (inp) {
      inp.onchange = function () {
        var idx = parseInt(inp.getAttribute("data-idx"), 10);
        _state.lhsr_groups[idx].name = inp.value.trim() || "group" + (idx + 1);
      };
    });
    $$(".parity-select button").forEach(function (btn) {
      btn.onclick = function () {
        var idx = parseInt(btn.getAttribute("data-idx"), 10);
        var parity = parseInt(btn.getAttribute("data-parity"), 10);
        _state.lhsr_groups[idx].parity = parity;
        renderGroups(_disks.filter(function (d) { return d.path !== _state.os_drive; }));
      };
    });
    $$(".group-card .disk-option").forEach(function (opt) {
      opt.onclick = function () {
        var path = opt.getAttribute("data-path");
        var card = opt.closest(".group-card");
        var gi = [].indexOf.call(card.parentElement.children, card);
        var g = _state.lhsr_groups[gi];
        var cb = opt.querySelector("input");
        if (cb.checked) {
          // Remove from group
          g.disks = g.disks.filter(function (p) { return p !== path; });
        } else {
          // Add to group
          g.disks.push(path);
        }
        renderGroups(_disks.filter(function (d) { return d.path !== _state.os_drive; }));
      };
    });
    $$("[data-remove-group]").forEach(function (btn) {
      btn.onclick = function () {
        var idx = parseInt(btn.getAttribute("data-remove-group"), 10);
        _state.lhsr_groups.splice(idx, 1);
        renderGroups(_disks.filter(function (d) { return d.path !== _state.os_drive; }));
      };
    });
  }

  $("#add-group").onclick = function () {
    _state.lhsr_groups.push({ name: "group" + (_state.lhsr_groups.length + 1), parity: 1, disks: [] });
    renderGroups(_disks.filter(function (d) { return d.path !== _state.os_drive; }));
  };

  $("#lhsr-next").onclick = function () {
    // Validate: each group needs at least 3 disks for LHSR1, 4 for LHSR2
    for (var i = 0; i < _state.lhsr_groups.length; i++) {
      var g = _state.lhsr_groups[i];
      var min = g.parity === 2 ? 4 : 3;
      if (g.disks.length < min) {
        toast("Group '" + g.name + "' needs at least " + min + " disks for LHSR" + g.parity, "warn");
        return;
      }
    }
    goStep(5);
  };

  // ── step 5: monitoring ──
  $("#snap-enabled").onclick = function () {
    _state.snapshots.enabled = !_state.snapshots.enabled;
    $("#snap-enabled").className = "switch" + (_state.snapshots.enabled ? " on" : "");
    $("#schedule-row").style.display = _state.snapshots.enabled ? "flex" : "none";
  };

  $("#snap-next").onclick = function () {
    _state.snapshots.calendar = $("#snap-calendar").value;
    renderReview();
    goStep(6);
  };

  // ── step 6: review ──
  function renderReview() {
    var txt = "Network:\n";
    txt += "  Interface: " + _state.network.interface + "\n";
    txt += "  IP: " + _state.network.address + "/" + _state.network.prefixlen + "\n";
    txt += "  Gateway: " + _state.network.gateway + "\n";
    txt += "  DNS: " + _state.network.dns + "\n\n";
    txt += "System:\n";
    txt += "  Hostname: " + _state.system.hostname + "\n";
    txt += "  LAN Name: " + _state.system.lan_name + "\n";
    txt += "  Timezone: " + _state.system.timezone + "\n\n";
    txt += "OS Drive: " + _state.os_drive + "\n\n";
    txt += "LHSR Groups:\n";
    _state.lhsr_groups.forEach(function (g) {
      txt += "  " + g.name + " (LHSR" + g.parity + "): " + g.disks.join(", ") + "\n";
    });
    txt += "\nSMART Monitoring:\n";
    txt += "  Enabled: " + _state.snapshots.enabled + "\n";
    if (_state.snapshots.enabled) {
      txt += "  Frequency: " + _state.snapshots.calendar + "\n";
    }
    $("#review-content").textContent = txt;
  }

  $("#apply-btn").onclick = async function () {
    var btn = $("#apply-btn");
    btn.disabled = true;
    btn.textContent = "Applying...";

    var body = {
      hostname: _state.system.hostname,
      timezone: _state.system.timezone,
      lan_name: _state.system.lan_name,
      network: _state.network.interface ? _state.network : null,
      os_drive: _state.os_drive,
      lhsr_groups: _state.lhsr_groups,
    };

    var r = await api("/api/setup/configure", { method: "POST", body: JSON.stringify(body) });
    if (!r.ok) {
      toast((r.data && r.data.detail) || "Configuration failed", "err");
      btn.disabled = false;
      btn.textContent = "Apply Configuration";
      return;
    }

    // Install scheduler if enabled
    if (_state.snapshots.enabled) {
      var sr = await api("/api/lhsr/scheduler", {
        method: "POST",
        body: JSON.stringify({ action: "install", calendar: _state.snapshots.calendar }),
      });
      if (!sr.ok) {
        toast("Scheduler install failed: " + ((sr.data && sr.data.detail) || "unknown"), "warn");
      }
    }

    toast("Configuration applied successfully!", "ok");
    btn.textContent = "Done";
    setTimeout(function () {
      window.location.href = "/";
    }, 2000);
  };

  // ── init ──
  async function init() {
    var r = await api("/api/setup/status");
    if (r.ok && r.data && r.data.configured) {
      // Already configured — redirect to home
      window.location.href = "/";
      return;
    }
    await loadNetwork();
    await loadSystem();
    await loadDisks();
    goStep(1);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
