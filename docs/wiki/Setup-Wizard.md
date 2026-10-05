# Setup Wizard

`/setup.html`. First-boot configuration, in six steps. Each step validates
before moving on.

## Step 1 — Network

- **Interface** — pick the adapter (e.g. `ens18`).
- **IP address + prefix length** — set a static address, e.g.
  `10.0.0.241/24`.
- **Gateway** — e.g. `10.0.0.1`.
- **DNS server** — resolver IP.

**Next** validates the values. An apply-and-confirm safeguard runs after
applying a static address so a typo cannot cut off access permanently.

## Step 2 — System

Hostname, LAN name (mDNS), and timezone.

## Step 3 — OS Drive

Pick which disk hosts the OS. This is a device selection — the wizard does
not format anything until you confirm in Review.

## Step 4 — LHSR Groups

Define a hybrid RAID group: disks and parity (1 = one parity copy, 2 = two).

## Step 5 — Monitoring

Set snapshot frequency (daily/weekly) and where SMART trends are recorded.

## Step 6 — Review

Everything chosen, summarized. The apply step writes config and installs
systemd timers; the wizard never leaves a half-configured box.

## Verified

- Network step renders with the interface list, whitelisted fields, and
  placeholders readable in both light and dark themes.
