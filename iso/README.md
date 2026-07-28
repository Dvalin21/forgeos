# iso/ — ForgeOS ISO build

Status: **I1, I2, I3 done.** I4 (the actual xorriso remaster script) remains
— that's the only thing standing between this and a bootable ISO.

## What's here

- `preseed.cfg` — automates the Debian install end to end except ONE
  question: which disk to install onto. Syntax-checked with
  `debconf-set-selections -c` (passed clean).
- `boot-menu/isolinux-forgeos.cfg`, `boot-menu/grub-forgeos.cfg` — draft
  boot menu entries for BIOS and UEFI boot respectively.
- `late_command.sh` — what preseed's late_command actually runs: extracts
  the baked payload onto the target disk, installs + enables the
  first-boot systemd unit. Simulated end-to-end against fake /cdrom and
  /target trees (real cp/tar, faked `in-target`) — verified the unit file,
  the executable script, the enable symlink, and the completion marker all
  land at the exact paths the rest of the chain expects.
- `firstboot/forgeos-firstboot-install.sh` + `.service` — runs once on the
  real first boot: converts DHCP to static (I2's forgeos_firstboot.py),
  then runs the exact same `install/v2/bootstrap.sh` a manual install
  uses. Idempotent (a completion marker skips re-runs); a failure at
  either step leaves the marker unwritten and the unit enabled for a
  manual retry rather than boot-looping. Verified with 5 simulated runs
  (happy path, idempotent skip, bootstrap failure, network-conversion
  failure, missing-payload) using mocked python3/bootstrap.sh/systemctl —
  and `systemd-analyze verify` passed on the unit file itself.
- `payload/build-payload.sh` — bakes a versioned tarball of the repo
  (version read from pyproject.toml, no separate file to drift). Actually
  run in this sandbox, not just written: produced a real 1.6M tarball,
  contents verified (dev cruft excluded, everything late_command.sh needs
  is present, doesn't embed itself).

## A bug the simulation caught, worth knowing about

`build-payload.sh` originally excluded the entire `iso/` directory from
the payload — reasonable-sounding ("the payload doesn't need to contain
itself"), and wrong: `late_command.sh` extracts the payload and then
copies the first-boot unit files OUT of `iso/firstboot/` inside it. The
first end-to-end simulation failed with a `cp: cannot stat` error at
exactly that step. Fixed by excluding only the payload tarballs
themselves, not the whole directory. Left as a reminder that "this
directory looks self-referential, exclude it" is exactly the kind of
reasoning that needs a simulation to catch, not just re-reading the code.

## Open items that need YOUR confirmation, not mine

**1. Debconf question key names + boot-menu file structure** — unchanged
from I1; still need diffing against a real trixie ISO, which this sandbox
can't fetch. See the notes in `preseed.cfg` and the boot-menu files
themselves.

**2. The OS-level account decision** (root disabled, local account
password-locked, SSH-key/console-only access) — still my default, not
yet explicitly confirmed. One-line change if you want a real temporary
password instead.

**3. Where the admin password ends up.** `forgeos-install-cli.py` prints
it once to stdout, "shown only once" — fine when run interactively at a
terminal, but under systemd during an unattended first boot, stdout goes
to the journal instead. Retrieve it with:
```
journalctl -u forgeos-firstboot-install --no-pager | grep -A2 'admin login'
```
This reuses the journal rather than inventing a second notice mechanism —
same trust boundary (root/sudo) either way. Flagging it so it's a
deliberate choice, not a surprise.

## Testing before a full ISO exists

You still don't need I4 to test most of this. Two useful checkpoints:

**Preseed content**, same as before I3 — serve `iso/` over HTTP to a stock
netinst VM and manually append `preseed/url=...` at the boot prompt.

**The late_command + first-boot chain**, now that it's real: build the
payload (`bash iso/payload/build-payload.sh`), then once you've done a
manual (non-preseeded) Debian install in a test VM, you can dry-run the
chain by hand — copy `iso/late_command.sh` and the payload onto that VM,
run `late_command.sh` with `/cdrom` and `/target` pointed at real paths,
reboot, and watch `journalctl -u forgeos-firstboot-install -f`. This
proves the actual install chain works before the ISO remaster is real,
the same incremental-verification instinct as the network page's hardware
loop.

## Next

I4: `build-iso.sh` — unpack the real Debian netinst ISO with xorriso,
inject `preseed.cfg` + `late_command.sh` + `forgeos-payload.tar.gz` at
`/forgeos/` on the ISO filesystem, splice the boot-menu entries in
(finally confirming against the real file structure), repack, and boot-test
in Proxmox.

