# ForgeOS — OS-Level Backup & Disaster Recovery (Design)

Goal (Keith): disaster recovery. Two tracks:
  1. Back up client machines (Windows/Mac/Linux) to ForgeOS — via UrBackup
     integrated as a managed ForgeOS service (NOT reimplemented).
  2. Native bare-metal backup/restore of ForgeOS ITSELF — via ReaR
     (Relax-and-Recover), which complements the Restic that ForgeOS
     already installs.

Both are INTEGRATIONS of mature, battle-tested tools — not from-scratch
reimplementations. Writing live cross-platform imaging clients + a bootable
restore environment ourselves would be a multi-year effort and is explicitly
out of scope.

---

## Repo grounding (what ForgeOS already has)

- **Existing file backup:** install/modules/15-backup.sh installs Restic +
  Rclone, with timers (Restic nightly 02:00, Rclone 04:30) and a master key
  at /etc/forgeos/backup/keys/master.key. src/backup_api.py exposes 16 routes
  (borg/restic/rclone status/create/snapshot/sync/list). This is FILE backup,
  not image/bare-metal — the gap ReaR fills.
- **Storage:** mdadm + LVM + btrfs layered design for the DATA pool; snapper +
  btrfs-progs already installed. LVM is present → LVM snapshots available for
  consistent imaging. The storage module operates on data disks and
  explicitly EXCLUDES the system disk — so the OS disk (option 2's target) is
  currently unmanaged. That's the gap.
- **v2 architecture:** config-DB (src/forgeos_config.py) + per-service
  generators + registry + forgeos-generate CLI; nginx generator already
  derives reverse-proxy vhosts from enabled services; SMTP notifications +
  health watcher exist. An app installed from the app store auto-gets an
  nginx vhost. All of this is what we plug the two backup tracks into.

---

## Track 1 — UrBackup for client machines (option 1)

### What UrBackup is (researched)
Client/server. Server stores backups + web UI; lightweight client daemons on
each machine auto-discover the server (UDP broadcast) and do file + image
backups while the system runs. Image backups use LVM/btrfs snapshots → full
disk images suitable for bare-metal restore. Restore via web UI (files) or a
Debian-based bootable USB (bare metal). Server ships as Debian .deb; tested
on Debian 13.4 with Server 2.5.36 — i.e. Keith's exact VM OS.

### Ports
- 55413/tcp (client↔server), 55414/tcp (web UI), 55415/tcp (internet/fileserv),
  35623/udp (LAN discovery broadcast).

### Integration model (NOT a Docker container — native managed service)
This becomes a base-or-app ForgeOS service driven by the v2 pattern:
- **Install:** add the UrBackup Debian repo + apt-install urbackup-server
  (a generator/installer step, mirroring how the base installs nginx etc.).
- **Config-DB section** `urbackup`: enabled, backup storage path (default a
  dataset under the NAS pool, e.g. /srv/nas/backups/urbackup), retention,
  web UI port. Generator writes /etc/default/urbackupsrv (storage dir, port,
  tmp dir) from the DB — the same render→apply pattern as our other
  generators (no heredocs).
- **Reverse proxy:** reuse the nginx generator — add a vhost
  backup.<domain> → 127.0.0.1:55414, TLS via the existing cert path. This is
  the proven pattern (the howtoforge guide literally runs UrBackup behind
  nginx + SSL; we already generate exactly that).
- **Storage location matters:** UrBackup's backup dir should live on the
  btrfs DATA pool (dedup/compression/snapshots), NOT the OS disk. Tie the
  default to the pool mount.
- **Firewall:** the security generator opens 55413-55415/tcp + 35623/udp on
  the LAN CIDR only.
- **Clients:** ForgeOS doesn't write clients — UrBackup provides Windows
  installer, macOS pkg, and a universal Linux .sh. ForgeOS's web UI just
  shows the download links + the server's discovery info. (This is where
  Mac/Windows/Linux coverage comes from, for free, battle-tested.)

### What we get / what we avoid
GET: cross-platform client image+file backup, bare-metal restore USB, dedup,
web management — all maintained upstream. AVOID: writing VSS/APFS/LVM live
imagers and a bootable restore environment (the multi-year trap).

### Honest caveats
- UrBackup image backups are strongest on Windows (NTFS); Linux client image
  backup works via LVM/btrfs but is less turnkey; macOS client is file-backup
  oriented (APFS full-image is hard for everyone). For DR of Macs, file
  backup + Time Machine alongside is the realistic story.
- Licensing: UrBackup server is open source (AGPL/Common-clause history —
  must verify current license before bundling/redistribution vs. just
  installing from upstream repo on the user's box). ACTION: confirm license
  terms before we ship anything that redistributes it.

### LICENSE VERDICT (verified)
UrBackup is **AGPLv3+** (© Martin Raiber; base server + all clients free for
personal AND commercial use, no fees). Bundling as a base service is allowed.
The ONE rule that shapes our integration: AGPL's network-copyleft means if we
MODIFY UrBackup and run it as a service, we'd have to publish those mods.
  - SAFE (our plan): install STOCK UrBackup from its own package/repo, run it
    as a SEPARATE service, ForgeOS only configures/orchestrates it (writes its
    config, reverse-proxies it, surfaces status). Two cooperating programs is
    NOT a derivative work — ForgeOS stays GPLv3, UrBackup stays AGPLv3, no
    contamination. (This is how TrueNAS/QNAP package it.)
  - DO NOT: fork+modify UrBackup's code and ship it, or link ForgeOS code into
    the UrBackup process.
  - Commercial add-ons exist (Infscape: Windows Change Block Tracking, the
    UrBackup Appliance) — not needed, not bundled; the free AGPL version is
    fully functional for our use. Track 1 is CLEARED to proceed on this basis.

---

## Track 2 — ReaR for ForgeOS bare-metal DR (option 2)

### Why ReaR (researched)
ReaR creates a **bootable rescue ISO** with the box's drivers, disk layout,
and network config, plus a full system backup archive. Boot the rescue
media, type `rear recover`, and it rebuilds partitions, filesystems,
bootloader, and data — even on different hardware. It's the missing
bare-metal half that Restic (file-level) doesn't do. Two commands:
`rear mkrescue` (bootable image) and `rear mkbackup` (archive + image).
Backup target can be NFS, CIFS, or USB.

### Integration model
- **apt-install rear** (+ genisoimage/syslinux for ISO; nfs/cifs utils as
  needed) — an installer/generator step.
- **Config-DB section** `osbackup`: enabled, output type (ISO|USB),
  backup_url (where the rescue image + archive go — MUST be a separate
  filesystem from root; ReaR enforces this), schedule.
- **Generator** writes /etc/rear/local.conf from the DB (OUTPUT, BACKUP,
  BACKUP_URL, etc.) — render→apply, no heredocs. Critical correctness point:
  BACKUP_URL must NOT be on the root fs (ReaR refuses) — validate in the
  pydantic model that the target differs from the OS disk.
- **Schedule:** a systemd timer runs `rear mkbackup` (e.g. weekly) writing
  the rescue ISO + archive to the DATA pool (/srv/nas/osbackup/) and/or a
  cloud target via the existing Rclone.
- **Restore flow (documented + surfaced in UI):** download/burn the latest
  rescue ISO → boot the dead/new box → `rear recover` → it pulls the archive
  from the configured target. The web UI shows "Download recovery ISO" +
  last-backup status + a tested-restore reminder.
- **Notifications:** wire mkbackup success/failure into the SMTP + health
  notification path we built.

### What we get / what we avoid
GET: true bare-metal DR of the ForgeOS box itself, restore-to-dissimilar-
hardware, on top of tools designed for it. AVOID: hand-rolling dd/partition/
bootloader logic (the nixCraft thread shows all the ways dd bites you:
smaller target disks, partition boundaries, etc.).

### Honest caveats
- ReaR rescue media MUST be tested on the actual hardware before trusting it
  (everyone says this; the softpanorama + ReaR docs stress verifying the
  boot env works on your specific NIC/disk controller). The UI should nudge
  toward a test restore.
- ReaR backup target must be a separate filesystem (enforced). On the VM
  with multiple disks this is fine; document it clearly.
- This protects the OS disk. The DATA pool is protected separately (Restic +
  btrfs snapshots already). Make the distinction explicit in the UI so the
  user knows OS vs data are different backups.

---

## How this maps onto the v2 build pattern

Each track is a config-DB section + a generator + an installer step + an
nginx vhost (track 1) + notification wiring — i.e. exactly the components we
already have a proven, tested pattern for. No new architecture needed.

Proposed config-DB additions:
```
urbackup: { enabled, storage_path, webui_port, retention_days }
osbackup: { enabled, output, backup_url, schedule, cloud_sync }
```

## Build sequence (proposed — for review, nothing built yet)
1. Verify UrBackup server license terms for our distribution model.
2. config-DB: add urbackup + osbackup sections (pydantic, with the
   "backup_url not on root fs" validator). Pure + tested first.
3. urbackup generator (writes /etc/default/urbackupsrv) + nginx vhost +
   firewall rule + installer step. Tested.
4. rear generator (writes /etc/rear/local.conf) + timer + installer step +
   notification wiring. Tested.
5. Web UI: a "Disaster Recovery" page — UrBackup status + client download
   links; ForgeOS OS-backup status + "download recovery ISO" + last-run.
6. Real-hardware validation on the VM: a UrBackup client backup from a
   laptop, and a ReaR test-restore of the ForgeOS VM.

## Open questions for Keith
1. UrBackup backup storage: default to a dataset on the btrfs DATA pool
   (/srv/nas/backups/urbackup)? (Recommended — dedup/compression.)
2. Base service or app-store app? UrBackup is heavier; app-store fits the
   "optional, install on demand" model better. ForgeOS OS-backup (ReaR) is
   small and DR-critical → base.
3. ReaR target: the DATA pool, a dedicated disk, and/or cloud via Rclone?
4. OK to verify UrBackup's current license before committing to bundling vs
   install-from-upstream?

## DECIDED (Keith)
1. UrBackup = BASE service (always installed), not app-store.
2. Backup target for BOTH tracks: a DEDICATED disk + cloud (via Rclone).
   So the config schema needs an explicit backup-disk target + optional
   cloud sync, NOT the shared NAS pool by default.
3. Start with ReaR (ForgeOS self-DR) — smaller, all-native, DR-critical.
4. UrBackup license still to be verified before its build (track 1).

Implications:
- osbackup.backup_url points at the dedicated disk mount; cloud_sync via the
  existing Rclone remote. The "must be a separate filesystem from root" rule
  is satisfied by construction (dedicated disk).
- The dedicated backup disk needs to be selected/mounted — tie into the
  storage layer; the schema references it by mount path or by-id.
