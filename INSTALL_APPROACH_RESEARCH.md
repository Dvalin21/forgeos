# Installer approach research — ForgeOS

Date: 2026-10-05. Owner: Keith.

## Why this doc

ForgeOS currently boots a remastered Debian 13 netinst ISO whose wizard
asks the user everything. Synology, TrueNAS SCALE, and TrueNAS Core
popularized a different pattern: the OS installs itself quietly, and the
*first boot* runs a browser-based setup wizard instead. This doc compares
the two, evidence from an actual boot test done tonight, and the packaging
consequence.

## Evidence from the real ISO, tonight

The built `forgeos-installer-amd64.iso` (Aug 26, 756MB payload) boots.

- Isolinux menu loads, the ForgeOS entry is `menu default`.
- **The preseed is not being consumed.** Evidence:
  1. The installer stops at the language picker (`Prompt: '?' for help,
     default=20>` — every language listed).
  2. The repo's committed draft stanza (`iso/boot-menu/*.cfg`) carries
     `priority=critical` in the append line. The stanza that actually got
     baked into the Aug-26 ISO does **not** — `/isolinux/txt.cfg` and
     `/boot/grub/grub.cfg` inside the ISO both show the append line ending
     at `auto=true` with no `priority=critical`.
  3. Until `priority=critical` is restored, the installer walks every high
     priority debconf template (locale, timezone, network…) even though
     `preseed.cfg` sets them.
- A stray Dark-contrast/speakup chain also triggers a speech-synthesis
     probe on first boot of the same media — cosmetic but worth removing.
- A patched ISO rebuilding the stanza with `priority=critical` in both
  menu files was produced and is at `/tmp/forgeos-installer-patched.iso`;
  on a fresh VM it still shows the speak-up prompt, then locale. The
  root cause is the same: the installer is not running with the preseed
  critical-priority appliance, so every debconf field asks.

Next action on the ISO path: verify whether the entry is being booted at
all (`preseed/file` path resolvable vs `/int viewer: we can no longer
determine from serial logs because the text console is on VGA) and
either (a) restore `priority=critical` in the **actually-used** boot
entry in `iso/build-iso.sh` + the draft stanzas, or (b) switch to the
simpler model below.

## Approach A — current: full ISO with Debian d-i + preseed

User boots the ISO, Debian installs itself, ForgeOS payload is extracted
into the target rootfs during late_command, first-boot installs ForgeOS
package and brings up the setup wizard on the web UI.

**Pros**
- Works on any PC/VM with a USB or CD; no network required beyond apt
  access for OS-level packages.
- The same preseed technique is well-documented Debian d-i behavior.
- Closest to every mainstream distro installer mentally.

**Cons**
- The wizard is the Debian d-i wizard, then a *second* wizard in the
  web UI. Two installs, two surfaces. The preseed critical-priority
  format is brittle — we're already debugging why a baked-in entry
  doesn't match the draft.
- Web GUI config lives in a separate page, not the same browser flow
  you reused inside the VM.
- Big 757MB media; preseed-chapter strings are a known rename-risk
  across Debian releases (trixie moved several templates).

## Approach B — Synology/TrueNAS-style: ISO installs a quiet OS, first
boot is the browser

Same as A up through preseed, but the baked-in payload is just the
ForgeOS package, so after the quiet OS install the box reboots, and the
**ForgeOS web UI setup wizard** (already built — `/setup.html`) is the
primary configuration experience (network, system drive, LHSR groups,
monitoring). TrueNAS takes the literal other route: its installer only
sets the admin password, and everything else happens in the web UI.

**Pros**
- One configuration surface, the same browser UI they use after install.
- The setup wizard can enforce its own guard rails (apply-and-confirm
  on IP changes), which d-i can't.
- TrueNAS proves the model; Synology's Web Assistant is the same idea
  with the installer thin.

**Cons**
- Boot-on-first-run from USB still needs the stock Debian installer for
  the remaining OS-level decisions, or a similar netboot for the OS
  itself. You still need an ISO that *installs Debian* quietly.
- No significant media savings vs A; the difference is purely
  *which UI the user sees after boot*.

## Approach C — appliance `.img` (HAOS/Unraid/Core pattern)

Bake the complete rootfs into a disk image the user writes with
Balena/Etcher (or dd) to USB/SATA. First boot comes up with a web
server listening on DHCP or a fixed IP (`http://forgeos.local` or
`http://<ip>`), and the same `/setup.html` wizard is the first screen.

**Pros**
- Absolute simplest for a home-lab user: write image, power on, browser
  shows a wizard. No installer wizard at all.
- Exactly the pattern of Home Assistant OS, Unraid, and TrueNAS Core.

**Cons**
- Image is larger / per-arch (amd64 image only, need ARM build
  separately for Pi-class boxes).
- You lose the ability to reuse Debian's preseed-driven feature set
  (LVM, LUKS, etc.) unless you rebuild it into image staging.
- Recovery requires re-imaging or a read-only root (immutability),
  which Debian isn't configured for by default.
- If we want OEM/ship-to-user images, a signed, checksum-published
  .img is operationally more work than one ISO.

## Recommendation

- **Short term (for the test VM and Keith today): fix A's preseed
  priority.** The entry is nearly right; it just needs
  `priority=critical` restored in the actually-used stanza. The patched
  ISO is already built and ready to re-VM after confirming the speak-up
  false-positive and the disk selection behavior.
- **Adopt B for production.** Keep the ISO, restore the quiet preseed
  install, and put all NAS configuration in the web UI's setup wizard.
  This matches TrueNAS/Synology and gives us one config surface
  instead of two. No change to the media type — still an ISO.
- **Consider C later** only if we ship pre-baked images to users. It's
  the HAOS path, not the Debian-netinst path.

## Files to change if we take B

- `iso/build-iso.sh` — make the generated append line default to
  `priority=critical` (the committed draft has it, the built one lost
  it — find where the template drifts and lock it with a test
  `grep -q priority=critical` against the patched tree).
- `iso/boot-menu/*.cfg` — same: keep `priority=critical` as the single
  source of truth.
- First-boot unit (`iso/firstboot/forgeos-firstboot-install.sh`) —
  after the quiet install, drop the user onto the ForgeOS web UI at
  the LAN IP instead of asking more d-i questions.
- Our `/setup.html` — already in place; small onboarding tweaks
  (logo,welcome screen, forced password creation) if we commit to B.

End of report.
