/* ForgeOS — one storage-health verdict, shared by the sidebar, the dashboard
   and the Storage page.

   These three used to compute their own answer to "is my storage healthy?"
   and they could disagree: the sidebar counted a drive with no SMART reading
   as healthy, the dashboard counted the same drive as failed, and each used
   different wording for the same state (All good / Online / Healthy). A
   non-techie sees all three on one screen, so disagreement reads as
   "this thing is broken".

   Anything that needs the verdict asks here instead of re-deriving it.
   Pure functions over the /api/storage/{pools,drives} payloads — no DOM,
   no fetch, no globals beyond this one export. */
(function (global) {
  "use strict";

  // Worst-wins ordering for the pool health strings storage_api reports.
  var POOL_RANK = { ok: 0, predict: 1, warn: 2, rebuilding: 2, err: 3 };

  // A drive at or above this SMART health percentage counts as healthy.
  // Matches the threshold the Storage page has always used on drive cards.
  var DRIVE_MIN = 90;

  /* Worst pool health, and whether any pool is not "ok".
     Returns { worst: <health string>, bad: <bool> }. */
  function worstPool(pools) {
    var worst = "ok";
    var bad = false;
    (pools || []).forEach(function (p) {
      var h = (p && p.health) || "ok";
      if ((POOL_RANK[h] || 0) > (POOL_RANK[worst] || 0)) worst = h;
      if (h !== "ok") bad = true;
    });
    return { worst: worst, bad: bad };
  }

  /* Drive tally. A drive with no SMART reading is counted as `unknown`, NOT
     as healthy — an unreadable drive must never make the verdict "good".
     Returns { total, healthy, unknown, bad }. */
  function driveCount(drives) {
    var total = (drives || []).length;
    var healthy = 0;
    var unknown = 0;
    (drives || []).forEach(function (d) {
      if (!d || typeof d.health !== "number") { unknown++; return; }
      if (d.health >= DRIVE_MIN) healthy++;
    });
    return { total: total, healthy: healthy, unknown: unknown, bad: total - healthy };
  }

  /* The one verdict.
     state: "ok" | "attention" | "ready"
     label: the wording every surface uses, so the sidebar, hero and Storage
            chip read identically. */
  function storage(pools, drives) {
    var p = worstPool(pools);
    var d = driveCount(drives);
    var havePools = pools && pools.length;
    var haveDrives = drives && drives.length;
    var state;
    var label;
    if (!havePools && !haveDrives) {
      state = "ready";
      label = "No storage yet";
    } else if (!havePools || p.bad || d.bad) {
      state = "attention";
      label = "Needs attention";
    } else {
      state = "ok";
      label = "All good";
    }
    return { state: state, label: label, pool: p, drives: d };
  }

  /* Short supporting line for the sidebar footer: "2 pools · 3/4 drives healthy". */
  function detail(pools, drives) {
    var v = storage(pools, drives);
    var parts = [];
    if (pools && pools.length) {
      parts.push(pools.length + " pool" + (pools.length === 1 ? "" : "s"));
    }
    if (v.drives.total) {
      parts.push(v.drives.healthy + "/" + v.drives.total + " drives healthy");
    }
    return parts.length ? parts.join(" · ") : "No storage data";
  }

  global.ForgeHealth = {
    POOL_RANK: POOL_RANK,
    DRIVE_MIN: DRIVE_MIN,
    worstPool: worstPool,
    driveCount: driveCount,
    storage: storage,
    detail: detail
  };
})(window);