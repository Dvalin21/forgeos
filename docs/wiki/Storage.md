# Storage

Storage Manager is the center of the product: pools, volumes, drives, and
the LHSR hybrid-RAID planner.

## Pool Overview

Lists every registered btrfs pool. For each pool: name, RAID level chip,
drive count, mount state, and buttons:
- **Run consistency check** — starts a btrfs scrub of the pool. This reads
  every block and repairs from the good copy when possible. It runs online;
  no downtime. Progress appears in *Storage activity*, and while it runs a
  line appears in the sidebar on every page so you can walk away from this tab.
- **Add drive** — add a physical disk to an existing pool.

Under the pool list, one line reports the check schedule:

- **Not scheduled** — nothing runs the scrub for you. Pressing the button by
  hand is the only way a check ever happens, so "healthy" is a snapshot, not a
  promise.
- **Scheduled weekly/monthly/daily** — a systemd timer runs the check for you
  (`POST /api/storage/scrub-schedule`). Turning this on is the single
  highest-value thing you can do for the health of this box: it means a
  problem is found while you still have a second good copy. **Last checked**
  shows when the last one finished.

The confirm dialog for a check says what it costs (the box stays online but is
slower and busier while it runs, usually a few hours on a large pool), offers
*Run now*, and offers the schedule as an alternative. If the pool has **no
second copy** — profile `single` — the dialog says so plainly: a check can
detect corruption there but cannot repair it, and your data is protected by
your backups instead.

If a pool exists on the disks but was never registered (for example the VM
or hardware was in use before ForgeOS was installed), it shows up in a dashed
card under **Found N existing pool(s) not registered**:
- **Keep it — register** — calls `POST /api/storage/pools/adopt` and adds
  the pool to config without touching data.
- **Start fresh** — calls `POST /api/storage/pools/destroy`: unmounts the
  pool and wipes the signature off every member disk. The API refuses
  `confirm:false` and refuses to wipe the pool that hosts `/`.

## Capacity

A donut chart of total pool used/free plus per-volume bars
(`GET /api/storage/df`).

## Storage activity

Newest-first audit of storage events (spin-downs, adopts, scrubs). The
round-arrow button refreshes; **View all** opens the full log page.

## LHSR Planner

Given unassigned drives, compute a hybrid RAID layout: hot SSD/NVMe tier
first, HDDs behind. **Plan Layout** calls `POST /api/lhsr/plan`. The plan is
shown before anything is applied; applying (in `lhsr create`) partitions and
formats — it only runs after you click it, never automatically.

## Disk Health Trends

SMART snapshots over time with predictive warnings. When no data exists it
says so and offers recording a snapshot.

## Physical Drives

One card per disk, grouped by role (Pool · In use · OS). Each card shows
capacity, media type, temperature, and health **in words** — *Healthy*,
*Degraded* or *Crashed*, each with a one-line explanation ("The drive is
healthy." / "…we recommend replacing the drive."). This is deliberately the
same vocabulary Synology DSM uses, so a drive reads the way you expect. The
percentage bar is still there underneath; *Info* opens the raw `smartctl`
report for anyone who wants the numbers.

Actions per card:
- **Spin** — spin the drive down (`hdparm`). Safe; it spins back up on the
  next read. Log it: activity entry `storage.drive.spindown`.
- **Replace** — marks the drive for replacement and starts a rebuild
  (btrfs `replace`).
- **Info** — raw `smartctl` output for this drive.

## Collapsed panels

**LHSR Planner** and **Disk Health Trends** start collapsed. They are power
tools; a person checking on their NAS should not have to scroll past a
tiering calculator. Click the header to open one.

## Verified

- `GET /api/storage/pools` returns the tank pool (raid1, mounted, healthy).
- Adopt flow executed live: cleared config pools → `GET
  /api/storage/unmanaged` listed tank → `POST /api/storage/pools/adopt` →
  pools list shows it healthy again.
- Create Pool, Run consistency check, Add drive, Spin, Replace, Info were
  exercised in the prior pass (audit log shows `storage.pool.scrub_done`,
  `storage.drive.spindown` entries).
- The drive action buttons fit in the card at desktop width (this was a
  bug; the Info button was clipped before the fix).
