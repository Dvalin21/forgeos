# PC Backup

`/imaging.html`. UrBackup server — image and file backups of the computers
on your network.

## Status

Top right shows `Running · vX.Y.Z` when the `urbakupsrv` systemd service
is healthy.

## What it does

1. The UrBackup **server** runs on the NAS and stores backups on the NAS.
2. Install the UrBackup **client** on each Windows/Linux/macOS machine on
   the LAN; clients are discovered automatically.
3. Clients run scheduled file backups, and full image backups on Windows.
4. A dead machine is restored with a restore boot stick — no OS reinstall.

**Open UrBackup** launches the native UrBackup web interface. Everything
about schedules, clients, and restores is configured there, not in this
page — first thing after installing: set *UrBackup Settings → Backup
storage path* to a NAS pool (e.g. `/srv/nas/tank/urbackup`), never the
root filesystem.

## Restoring a machine

1. Download the **Restore CD** ISO from urbackup.org and write it to a USB
   stick.
2. Boot the target machine from the stick; it finds this server on the LAN.
3. Pick the image backup to restore. Full-disk images restore bootable
   systems.

## Verified

- The server chip reads `Running · v2.5.37.0` — service healthy.
