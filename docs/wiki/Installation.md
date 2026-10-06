# Installation

ForgeOS ships with two install paths running the same installer.

## Option 1 — Installer script on a live Debian

Best when you already have a Debian install on the box (or plan to keep ssh/system access during install):

```bash
git clone -b v2-rearchitect https://github.com/Dvalin21/forgeos.git
cd forgeos
sudo bash install/v2/bootstrap.sh
```

* Interactive mode will ask: hostname, timezone, LAN name, security profile, optional services (WireGuard, NFS, Data Connect, Coral, GPU).
* Unattended mode:

```bash
sudo bash install/v2/bootstrap.sh --unattended \
  --hostname nas --timezone America/Chicago \
  --domain nas.local --profile medium --wireguard
```

The script seeds the config DB, runs the generators, installs package deps, and brings up `forgeos-api`. Log to `/var/log/forgeos-install.log`.

## Option 2 — ISO installer thumb drive (quiet preseed)

Best for a blank box or a small-home user who wants one USB stick and a browser:

```bash
git clone -b v2-rearchitect https://github.com/Dvalin21/forgeos.git
bash iso/build-iso.sh /path/to/debian-13.7.0-amd64-netinst.iso
sudo dd if=forgeos-installer-amd64-v3.iso of=/dev/sdX bs=4M status=progress oflag=direct
```

1. Put the stick in, boot the machine from USB (BIOS or UEFI both work).
2. Press Enter at the stock d-i speech-probe screen.
3. The preseeded installer then boots the quiet path; the one question that remains is which disk to install onto.
4. When complete and rebooted, get the server's IP from the console or router DHCP table.
5. Open `https://<that-ip>/setup.html` in a browser on the same LAN and finish setup: hostname, LAN name, timezone, OS drive, LHSR groups, monitoring, review.
6. After applying, the normal ForgeOS desktop is live at `https://<that-ip>/`.

The ISO starts **exactly the same** first-boot content as the script path
(`install/v2/bootstrap.sh` runs from the payload); the difference is the
Debian install is done for you by the media.

## After either path

| Service | URL |
|---|---|
| ForgeOS Web UI | `https://nas.local` |
| FileBrowser | `https://files.nas.local` |
| Grafana | `https://grafana.nas.local` |
| OnlyOffice | `https://office.nas.local` |
| Immich | `https://photos.nas.local` |
| Data Connect | `https://data-connect.nas.local` |

If a network-locked edit ever strands you, boot to the live system and re-run `sudo bash install/v2/bootstrap.sh` directly.
