# ForgeOS Wiki

Operator's guide to the ForgeOS web UI. Every page in the desktop UI is
documented here, in the words of what the screen actually shows. Where a
button maps to a system change, the underlying service or file is named.

**First login:** open `https://<your-nas-ip>/` in a browser. Sign in with
your admin username and password. The session is a Bearer token stored in
this browser's localStorage; closing the tab keeps you signed in.

## Pages

| Page | What it is for |
|------|----------------|
| [Dashboard](Dashboard) | At-a-glance health of the box |
| [Storage](Storage) | Disks, pools, scrubs, LHSR planner, SMART trends |
| [Data Connect](Data-Connect) | Shared database directories / Postgres & MySQL servers |
| [File Manager](File-Manager) | Browse, upload, permissions on storage roots |
| [Shares (SMB)](Shares) | Folders shared to Windows/macOS/Linux |
| [Network](Network) | Interfaces, hostname, DNS, dynamic DNS, routes |
| [Reverse Proxy](Reverse-Proxy) | nginx hosts, domains, TLS |
| [Firewall](Firewall) | ufw rules |
| [VPN](VPN) | WireGuard device access |
| [Apps & Containers](Apps) | ForgeOS app catalog + containers |
| [NAS Backup](Backup) | Borg/Restic/Rclone jobs on NAS data |
| [PC Backup](PC-Backup) | UrBackup server for network PCs |
| [Security Center](Security-Center) | fail2ban jails, auto security updates |
| [Notifications](Notifications) | Recent events + drive alerts |
| [Users](Users) | Accounts, roles, 2FA policy |
| [My Profile](My-Profile) | Your password + two-factor enrollment |
| [Settings](Settings) | Hostname/timezone/theme/SMTP |
| [Setup Wizard](Setup-Wizard) | First-boot configuration |
| [Installation](Installation) | ISO installer vs script install walkthrough |
| [Activity Log](Activity-Log) | Who did what, when |

## Common controls

- **Sidebar** — every page has the same left navigation. The pinned card at
  the bottom shows live NAS health; it polls the storage API about once a
  minute and reports "Unavailable" if the API does not answer within 8
  seconds.
- **Theme** — Settings → System card → Theme (Auto / Light / Dark). Auto
  follows the OS; a manual choice persists in this browser.
- **Refresh** — the round-arrow button at the top right of a page re-reads
  the data for that page.
- **Empty states** — a page with no data shows one sentence telling you what
  to do next; it never shows a bare "Loading…" forever.
