// The one storage-health verdict (web/desktop/js/health.js).
//
// This exists because the sidebar, the dashboard hero and the Storage chip
// each used to compute "is my storage healthy?" separately and could disagree
// — the sidebar counted a drive with no SMART reading as healthy, the
// dashboard counted the same drive as failed. These assertions pin the rules
// that consumers rely on, so a future edit can't quietly reintroduce the split.
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const JS = path.join(__dirname, '..', '..', 'web', 'desktop', 'js', 'health.js');
const sandbox = { };
const run = new Function('window', fs.readFileSync(JS, 'utf8'));
run(sandbox);
const H = sandbox.ForgeHealth;

function test_worst_pool_is_worst_wins() {
  assert.strictEqual(H.worstPool([{ health: 'ok' }, { health: 'ok' }]).bad, false);
  assert.strictEqual(H.worstPool([{ health: 'ok' }, { health: 'warn' }]).bad, true);
  // err outranks warn outranks predict outranks ok
  assert.strictEqual(H.worstPool([{ health: 'err' }, { health: 'ok' }]).worst, 'err');
  assert.strictEqual(H.worstPool([{ health: 'predict' }, { health: 'warn' }]).worst, 'warn');
  // no health field at all is treated as ok, not as a failure
  assert.strictEqual(H.worstPool([{ name: 'tank' }]).bad, false);
}

function test_drive_without_smart_reading_is_unknown_not_healthy() {
  // THE disagreement this module was created to kill.
  const d = H.driveCount([{ name: 'sda', health: 100 }, { name: 'sdb' }]);
  assert.strictEqual(d.total, 2);
  assert.strictEqual(d.healthy, 1, 'a drive with no health number must not count as healthy');
  assert.strictEqual(d.unknown, 1);
  assert.strictEqual(d.bad, 1);
}

function test_drive_threshold() {
  assert.strictEqual(H.driveCount([{ health: 90 }]).bad, 0, '90 is the pass mark');
  assert.strictEqual(H.driveCount([{ health: 89 }]).bad, 1);
}

function test_verdict_states() {
  const ok = H.storage([{ health: 'ok' }], [{ health: 100 }]);
  assert.strictEqual(ok.state, 'ok');
  assert.strictEqual(ok.label, 'All good');

  // degraded pool -> attention
  assert.strictEqual(H.storage([{ health: 'warn' }], [{ health: 100 }]).state, 'attention');
  // failing drive -> attention
  assert.strictEqual(H.storage([{ health: 'ok' }], [{ health: 40 }]).state, 'attention');
  // drives present but no pool registered -> attention, not "all good"
  assert.strictEqual(H.storage([], [{ health: 100 }]).state, 'attention');
  // nothing at all -> ready
  const empty = H.storage([], []);
  assert.strictEqual(empty.state, 'ready');
  assert.strictEqual(empty.label, 'No storage yet');
}

function test_every_surface_gets_the_same_label() {
  // The three call sites render H.storage(...).label; if the wording changes
  // here it changes everywhere, which is the point.
  const v = H.storage([{ health: 'err' }], [{ health: 50 }]);
  assert.strictEqual(v.label, 'Needs attention');
  assert.strictEqual(v.pool.worst, 'err');
  assert.strictEqual(v.drives.healthy, 0);
}

function test_detail_line() {
  assert.strictEqual(H.detail([{ health: 'ok' }], [{ health: 100 }, { health: 100 }]),
                     '1 pool · 2/2 drives healthy');
  assert.strictEqual(H.detail([], []), 'No storage data');
  // no drives -> don't render a pointless "0/0 drives healthy"
  assert.strictEqual(H.detail([{ health: 'ok' }, { health: 'ok' }], []), '2 pools');
}

const tests = [test_worst_pool_is_worst_wins,
               test_drive_without_smart_reading_is_unknown_not_healthy,
               test_drive_threshold,
               test_verdict_states,
               test_every_surface_gets_the_same_label,
               test_detail_line];

let failed = 0;
for (const t of tests) {
  try { t(); console.log('ok - ' + t.name); }
  catch (e) { failed++; console.error('not ok - ' + t.name + '\n  ' + e.message); }
}
process.exit(failed ? 1 : 0);