#!/bin/sh
# iso/late_command.sh — run at the end of the Debian install, BEFORE reboot.
#
# preseed.cfg's late_command copies THIS script from the ISO's own
# filesystem and runs it (rather than cramming a long shell pipeline into
# the preseed.cfg value itself, which has escaping/readability problems for
# anything beyond a couple of commands).
#
# Correctness note (the reason this isn't done a simpler-looking way):
# /cdrom is the install medium, guaranteed mounted in the OUTER d-i
# environment this script runs in. /target is the standard d-i mount point
# for the new system's root filesystem, ALSO always available here, BEFORE
# reboot. Whether /cdrom is additionally visible from INSIDE an `in-target`
# chroot is medium/version-dependent and not something this sandbox could
# verify against a real ISO — so the copy/extract happens in the OUTER
# environment against /target/... (always correct), and `in-target` is used
# ONLY for the one step that's conventionally run that way: enabling the
# systemd unit. `systemctl enable` is a stateless symlink operation, so it
# works via in-target even without a live systemd instance in the chroot.
#
# sh, not bash: d-i's environment is busybox/dash, not a full bash.
set -e

PAYLOAD_SRC="/cdrom/forgeos/payload.tar.gz"
PAYLOAD_DEST="/target/opt/forgeos-src"
UNIT_NAME="forgeos-firstboot-install.service"

echo "forgeos late_command: extracting payload to ${PAYLOAD_DEST}"
mkdir -p "${PAYLOAD_DEST}"
tar -xzf "${PAYLOAD_SRC}" -C "${PAYLOAD_DEST}"

echo "forgeos late_command: installing the first-boot systemd unit"
cp "${PAYLOAD_DEST}/iso/firstboot/${UNIT_NAME}" "/target/etc/systemd/system/${UNIT_NAME}"
chmod +x "${PAYLOAD_DEST}/iso/firstboot/forgeos-firstboot-install.sh"

echo "forgeos late_command: enabling ${UNIT_NAME} for first real boot"
in-target systemctl enable "${UNIT_NAME}"

echo "forgeos late_command: done at $(date -u +%FT%TZ)"
in-target sh -c "echo late_command completed at \$(date -u +%FT%TZ) > /etc/forgeos-preseed-marker"
