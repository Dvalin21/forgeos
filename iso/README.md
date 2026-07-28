# iso/ — ForgeOS ISO build (I1: preseed scaffold)

Status: **I1 only.** `preseed.cfg` and the boot-menu drafts exist; nothing
here produces a bootable ISO yet — that's I3 (payload + late_command +
first-boot unit) and I4 (the actual xorriso remaster script).

## What's here

- `preseed.cfg` — automates the Debian install end to end except ONE
  question: which disk to install onto. Syntax-checked with
  `debconf-set-selections -c` (passed clean) — that's real verification,
  not just eyeballing, but it only confirms the file *parses*, not that
  every question key is still correct for trixie specifically (see below).
- `boot-menu/isolinux-forgeos.cfg`, `boot-menu/grub-forgeos.cfg` — draft
  boot menu entries for BIOS and UEFI boot respectively, adding an
  "Install ForgeOS" option that boots with this preseed.

## Open items that need YOUR confirmation, not mine

**1. Debconf question key names.** This sandbox has no network access to
debian.org, so I built `preseed.cfg` from Debian's long-stable preseed
convention rather than by diffing against the actual current trixie
example preseed file. The technique (leaving `partman-auto/disk` unset
under `priority=critical` so it's the one thing that still prompts) is
solid and confirmed. A handful of exact key spellings might have moved
between releases. **Before the first real build**, diff this against
`installer/doc/example-preseed.txt` on the actual netinst ISO, or
`https://www.debian.org/releases/trixie/example-preseed.txt`, and tell me
if anything doesn't match — I'll fix it immediately.

**2. Boot menu file structure.** Same constraint — I don't know the exact
current isolinux/grub file layout inside a trixie netinst ISO from here.
The two `.cfg` files in `boot-menu/` are stanzas meant to be spliced into
the real menu files once you unpack the ISO in I4. Send me what the real
files look like and I'll adjust the splice points.

**3. The OS-level account decision (in `preseed.cfg`, flagged again here
since it's a real security choice, not a technicality).** My default: root
login disabled, a `forgeos` local account created but its password LOCKED
(no password-based login is possible at all) — OS-level access is via SSH
key or the Proxmox/physical console until you provision a key, exactly how
this VM has been accessed all along. All real administration happens
through the web UI. If you'd rather have a real (even temporary) OS
password for initial SSH access, say so and it's a one-line change.

## Testing I1 in isolation, before I3/I4 exist

You don't need the full xorriso remaster to test whether the preseed
*content* actually behaves the way it's supposed to. Boot a stock Debian
13 netinst ISO in a throwaway Proxmox VM and point it at this file over
HTTP instead of baking it in yet:

```bash
# on your workstation, from the forgeos repo
python3 -m http.server 8080 --directory iso
```

Then at the Debian installer's boot prompt (the *stock* menu, before any
ForgeOS boot-menu changes exist), manually add to the kernel command line:

```
auto=true priority=critical preseed/url=http://<your-workstation-ip>:8080/preseed.cfg hostname=forgeos
```

This proves out the actual question I care about most: does it stop and
show the disk picker, and does everything else fly by with zero prompts?
That's a much cheaper feedback loop than a full ISO remaster + boot test,
and it isolates preseed correctness from xorriso/remaster correctness —
worth doing before I4 exists.

## Next

I3: bake the versioned ForgeOS payload into the ISO, wire up the real
`late_command` (currently just drops a marker file) to unpack it and
install the first-boot systemd unit that runs `forgeos_install.py` +
`forgeos_firstboot.py`. I4: the actual `build-iso.sh` xorriso remaster.
