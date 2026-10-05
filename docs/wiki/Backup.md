# NAS Backup

`/backup.html`. Scheduled backups of what is stored on the NAS itself —
not for backing up your PCs (see [PC Backup](PC-Backup)).

## Backup tools

Chips at the top of the jobs card show which engines are installed:
**borg**, **restic**, **rclone**, all three. Each job picks one.

## Backup jobs

A job binds: a tool, a source path on the NAS, a destination (local disk,
SSH, or cloud via rclone), and a schedule. *Job / Tool / Schedule / Last
run* are listed. **Add backup job** opens the dialog. Clicking a job runs
it; the result is written to the Activity Log.

## OS disaster recovery

For the NAS itself: a full system image via ReaR plus an OSBackup archive.

- **Enable OS backup** — renders `/etc/rear/local.conf` from the wizard
  fields.
- **Backup path** — must be a *separate* filesystem, not the root
  filesystem. Default `/mnt/backup/osbackup`. The **Browse** button picks
  the directory.
- **Schedule** — systemd timer calendar value (e.g. `weekly`).
- **Cloud sync** — also push the archive through an rclone remote.
- **Save DR config** — validates and installs the scheduler.

Chips show state: `rear installed`, `config rendered`, `timer active` or
`timer inactive`, `ISO 175 MB`, `last: …`.

## Recent tasks

Every backup/DR run lands here with TOOL / ACTION / STATUS / STARTED.

## Requirements

Admin role — every `/api/backup/*` route is admin-gated and a non-admin
gets 403.

## Verified

- Empty state renders: "No backup jobs yet."
- Non-admin tokens receive 403 on backup routes (regression-tested in
  `tests/test_backup_api.py`).
