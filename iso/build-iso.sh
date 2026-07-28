#!/usr/bin/env bash
# iso/build-iso.sh — remaster a stock Debian 13 (trixie) netinst ISO into a
# bootable ForgeOS installer.
#
# COULD NOT BE EXECUTED IN THE SANDBOX THIS WAS WRITTEN IN: no network access
# to fetch a real Debian ISO, and even the xorriso *package* timed out on a
# throttled connection while building this. Written against xorriso's long-
# stable, well-documented remaster pattern (the -boot_image any replay
# technique below has been the standard way to clone a hybrid BIOS+UEFI ISO
# without hand-reconstructing its El Torito boot catalog for years — this
# part is a documented convention, not a guess). What genuinely needs your
# eyes on the real ISO: the exact boot-menu config file path (STEP 2 below
# tries several known-conventional candidates and lists the ISO's contents
# if none match, rather than silently doing nothing or guessing wrong).
#
# Usage:
#   iso/build-iso.sh <path-to-debian-13-netinst.iso> [output.iso]
#
# Prerequisites this script checks for you: xorriso, and that
# iso/forgeos-payload.tar.gz already exists (run payload/build-payload.sh
# first if not).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d /tmp/forgeos-iso-build.XXXXXX)"
# Deliberately NOT auto-deleted on exit: it holds the source ISO's boot
# report and the patched menu files, which are exactly what you'd want to
# inspect after either a failure or a success (to eyeball the menu patch
# before boot-testing). Cleaning it up is on you — it's in /tmp.

SRC_ISO="${1:-}"
OUT_ISO="${2:-${SCRIPT_DIR}/forgeos-installer.iso}"

log()  { echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

# ── Step 0: prerequisites ──────────────────────────────────────────
[[ -n "${SRC_ISO}" ]] || die "usage: $0 <path-to-debian-13-netinst.iso> [output.iso]

Get the source ISO from the official Debian site (this script does not
fetch it for you — no hardcoded URL here that could go stale across point
releases): https://www.debian.org/distrib/netinst
Pick the amd64 'netinst' image for the current trixie point release."

[[ -f "${SRC_ISO}" ]] || die "source ISO not found: ${SRC_ISO}"

command -v xorriso >/dev/null 2>&1 || die "xorriso not installed. apt install xorriso"

PAYLOAD="${SCRIPT_DIR}/forgeos-payload.tar.gz"
[[ -f "${PAYLOAD}" ]] || die "payload not found: ${PAYLOAD}
Run iso/payload/build-payload.sh first."

PRESEED="${SCRIPT_DIR}/preseed.cfg"
LATE_CMD="${SCRIPT_DIR}/late_command.sh"
[[ -f "${PRESEED}" ]] || die "missing: ${PRESEED}"
[[ -f "${LATE_CMD}" ]] || die "missing: ${LATE_CMD}"

log "Source ISO:  ${SRC_ISO}"
log "Payload:     ${PAYLOAD} ($(du -h "${PAYLOAD}" | cut -f1))"
log "Output:      ${OUT_ISO}"
log "Work dir:    ${WORK_DIR}"

# ── Step 1: capture the source ISO's boot setup ────────────────────
# Not used directly (see -boot_image any replay below, which reuses it
# automatically) — saved to the work dir so you can inspect it if the
# final ISO doesn't boot, to compare against what actually got applied.
log "Step 1/5: capturing the source ISO's El Torito boot setup"
xorriso -indev "${SRC_ISO}" -report_el_torito as_mkisofs \
    > "${WORK_DIR}/source-boot-setup.txt" 2>&1 || true
log "  saved to ${WORK_DIR}/source-boot-setup.txt (kept if this script fails)"

# ── Step 2: find the boot-menu config file(s) to edit ──────────────
# UNVERIFIED AGAINST A REAL ISO — see the header comment. Tries the
# conventional paths for BIOS (isolinux) and UEFI (grub) menus; if none
# match, lists the ISO's own file tree so you can tell me the real path
# and I'll fix the candidate list rather than you guessing blind.
log "Step 2/5: locating the boot-menu config file(s)"

BIOS_CANDIDATES=(
    "/isolinux/txt.cfg"
    "/isolinux/menu.cfg"
    "/isolinux/isolinux.cfg"
)
UEFI_CANDIDATES=(
    "/boot/grub/grub.cfg"
)

find_in_iso() {
    # $1 = path to test. Returns 0 (found) or 1 via xorriso's own exit code.
    xorriso -indev "${SRC_ISO}" -find "$1" -type f >/dev/null 2>&1
}

BIOS_MENU=""
for c in "${BIOS_CANDIDATES[@]}"; do
    if find_in_iso "$c"; then BIOS_MENU="$c"; break; fi
done
UEFI_MENU=""
for c in "${UEFI_CANDIDATES[@]}"; do
    if find_in_iso "$c"; then UEFI_MENU="$c"; break; fi
done

if [[ -z "${BIOS_MENU}" && -z "${UEFI_MENU}" ]]; then
    echo ""
    echo "None of the known candidate boot-menu paths matched this ISO."
    echo "Full file listing follows — find the real menu file path and either"
    echo "re-run with it added to BIOS_CANDIDATES/UEFI_CANDIDATES in this"
    echo "script, or send it to me and I'll fix the candidate list:"
    echo ""
    xorriso -indev "${SRC_ISO}" -find / -type f 2>/dev/null | grep -iE '\.cfg$|isolinux|grub' || true
    die "boot-menu config file not found automatically (see listing above)"
fi
[[ -n "${BIOS_MENU}" ]] && log "  BIOS menu found: ${BIOS_MENU}"
[[ -n "${UEFI_MENU}" ]] && log "  UEFI menu found: ${UEFI_MENU}"

# ── Step 3: extract, patch, and stage the modified menu file(s) ───
log "Step 3/5: injecting the ForgeOS boot entry"
mkdir -p "${WORK_DIR}/menu"

patch_menu() {
    local iso_path="$1" stanza_file="$2" out_name="$3"
    local extracted="${WORK_DIR}/menu/${out_name}"
    xorriso -indev "${SRC_ISO}" -osirrox on -extract "${iso_path}" "${extracted}"
    # Prepend the ForgeOS entry so it becomes the first/default item. The
    # stock menu (including its own "Advanced options" submenu) is otherwise
    # left untouched — see iso/README.md on why that's expected to just work.
    cat "${stanza_file}" "${extracted}" > "${extracted}.new"
    mv "${extracted}.new" "${extracted}"
    echo "${extracted}"
}

MAP_ARGS=()
if [[ -n "${BIOS_MENU}" ]]; then
    patched="$(patch_menu "${BIOS_MENU}" "${SCRIPT_DIR}/boot-menu/isolinux-forgeos.cfg" "bios.cfg")"
    MAP_ARGS+=(-map "${patched}" "${BIOS_MENU}")
fi
if [[ -n "${UEFI_MENU}" ]]; then
    patched="$(patch_menu "${UEFI_MENU}" "${SCRIPT_DIR}/boot-menu/grub-forgeos.cfg" "uefi.cfg")"
    MAP_ARGS+=(-map "${patched}" "${UEFI_MENU}")
fi

# ── Step 4: build the new ISO ──────────────────────────────────────
# -boot_image any replay: reuse the SOURCE ISO's exact El Torito boot
# catalog (BIOS + UEFI, whichever it has) rather than reconstructing one by
# hand — the standard, low-risk way to remaster a hybrid-boot ISO.
log "Step 4/5: building ${OUT_ISO}"
xorriso -indev "${SRC_ISO}" \
        -outdev "${OUT_ISO}" \
        -map "${PRESEED}"  /forgeos/preseed.cfg \
        -map "${LATE_CMD}" /forgeos/late_command.sh \
        -map "${PAYLOAD}"  /forgeos/payload.tar.gz \
        "${MAP_ARGS[@]}" \
        -boot_image any replay \
        -commit

# ── Step 5: sanity-check the output ────────────────────────────────
log "Step 5/5: verifying the output ISO"
xorriso -indev "${OUT_ISO}" -find /forgeos -type f 2>/dev/null

echo ""
log "Done: ${OUT_ISO}"
echo ""
echo "This has NOT been boot-tested (no way to do that from where this was"
echo "built). Next: boot it in a throwaway Proxmox VM — same hardware loop"
echo "used for the Network page."
echo ""
echo "Debug artifacts kept at: ${WORK_DIR}"
echo "  source-boot-setup.txt — the source ISO's original boot report"
echo "  menu/*.cfg            — the patched boot-menu file(s), worth"
echo "                           eyeballing before you boot-test"
echo "Delete it yourself when you're done: rm -rf ${WORK_DIR}"
