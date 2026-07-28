#!/usr/bin/env bash
# iso/firstboot/forgeos-firstboot-install.sh — runs ONCE, on the real first
# boot after a fresh install (invoked by forgeos-firstboot-install.service,
# enabled by late_command.sh during install).
#
# Order: network conversion FIRST (fast, makes the box reachable at its
# final static address quickly — the bootstrap step below can take a
# while, and there's no reason to leave the box on a soon-to-be-obsolete
# DHCP lease while it runs). Then the full ForgeOS install via the SAME
# bootstrap.sh a manual install uses — no separate first-boot-specific
# installer logic to drift out of sync with it.
#
# Idempotency: forgeos_firstboot.py already no-ops if the interface is
# already static. This script additionally will not re-run bootstrap.sh
# if a completion marker from a prior successful run exists. On FAILURE,
# the marker is not written and the systemd unit stays enabled — rerun via
# `systemctl restart forgeos-firstboot-install` after fixing whatever
# broke, rather than an automatic retry loop that could boot-loop a
# genuinely broken box.
set -euo pipefail

REPO_ROOT="/opt/forgeos-src"
MARKER="/etc/forgeos-firstboot-complete"
LOG_TAG="forgeos-firstboot"

log() { echo "${LOG_TAG}: $*"; }

if [[ -f "${MARKER}" ]]; then
    log "already completed at $(cat "${MARKER}") — nothing to do"
    exit 0
fi

if [[ ! -d "${REPO_ROOT}" ]]; then
    log "ERROR: ${REPO_ROOT} not found — the payload wasn't extracted correctly during install"
    exit 1
fi

log "step 1/2: converting DHCP -> static at the leased address"
if ! python3 "${REPO_ROOT}/src/forgeos_firstboot.py"; then
    log "ERROR: network conversion failed — see the messages above. Not proceeding to install."
    exit 1
fi
log "step 1/2: done"

log "step 2/2: running the full ForgeOS installer (bootstrap.sh --unattended)"
# --unattended with defaults: hostname/timezone are left as whatever the
# preseed/base install already set, lan-cidr defaults to 10.0.0.0/24,
# security profile "medium". Keith can override any of this by editing the
# flags below before baking the payload, or by re-running
# `forgeos-install-cli.py` by hand later to change profile/features.
if ! "${REPO_ROOT}/install/v2/bootstrap.sh" --unattended --profile medium; then
    log "ERROR: bootstrap.sh failed — see the messages above. Not marking complete;"
    log "fix whatever broke and run: systemctl restart forgeos-firstboot-install"
    exit 1
fi
log "step 2/2: done"

# NOTE on the admin password: forgeos-install-cli.py prints it once to
# stdout ("shown only once"). Run non-interactively under systemd, stdout
# goes to the journal, not a live terminal — so "once" here means once in
# the journal, not literally ephemeral. Retrieve it with:
#   journalctl -u forgeos-firstboot-install --no-pager | grep -A2 'admin login'
# This reuses systemd's existing journal rather than inventing a second
# notice mechanism — the trust boundary (root/sudo to read it) is the same
# either way.

date -u +%FT%TZ > "${MARKER}"
log "complete — disabling this unit so it doesn't run again"
systemctl disable forgeos-firstboot-install.service || true
