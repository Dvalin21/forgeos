#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 03c - Drive Classification + Cache Drives
#
# Drive type detection:
#   NVMe  — /dev/nvme* (PCIe NVMe protocol)
#   SSD   — rotational=0, no NVMe prefix → SATA/NVMe SSD
#   HDD   — rotational=1
#   USB   — transport=usb (via sysfs)
#   The type is tagged into the ForgeOS drive registry
#   and surfaced in the Web UI storage view.
#
# Cache drive (bcache):
#   bcache is a Linux kernel caching layer (in kernel since 3.10).
#   Architecture:
#     backing device (slow HDD/array) → bcache_dev → filesystem
#     caching device (fast SSD/NVMe) stores hot data
#
#   Modes:
#     writeback  — writes go to cache first, async to backing
#                  (fastest, slight data risk if cache fails)
#     writethrough — writes go to both cache + backing simultaneously
#                   (safe, slower writes than writeback)
#     writearound — writes bypass cache, reads are cached
#                   (for sequential write workloads, e.g. backups)
#     none        — cache disabled (passthrough mode)
#
#   For ForgeOS (NAS workload):
#     Default: writeback — best general performance
#     Recommended for SSD cache <50GB: writethrough (safer)
#     Recommended for NVMe cache: writeback
#
#   Cache works UNDER LVM and UNDER btrfs — transparent to everything above.
#   The bcache device (/dev/bcache0) becomes the backing device for LVM.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

DRIVE_REGISTRY="/etc/forgeos/drives.json"

# ============================================================
# DRIVE TYPE DETECTION
# ============================================================
detect_drive_types() {
    step "Detecting and classifying all drives"

    apt_install hdparm smartmontools nvme-cli lsscsi

    local registry="{\"drives\":["
    local first=true
    local sys_disk; sys_disk=$(get_system_disk 2>/dev/null | sed 's|/dev/||' || echo "")

    while IFS= read -r dev; do
        [[ -b "/dev/${dev}" ]] || continue
        [[ "$dev" =~ ^(loop|sr|md|dm|ram) ]] && continue

        local type="unknown"
        local transport="unknown"
        local model="unknown"
        local size_bytes=0
        local size_human="?"
        local is_sys=false

        # System disk marker
        [[ "$dev" == "$sys_disk" || "/dev/$dev" == "$sys_disk"* ]] && is_sys=true

        # NVMe detection (definitive — name prefix)
        if [[ "$dev" =~ ^nvme ]]; then
            type="nvme"
            transport="pcie"
            model=$(nvme id-ctrl "/dev/${dev}" 2>/dev/null | awk -F: '/^mn /{gsub(/ /,"",$2); print $2}' | head -1 \
                    || cat "/sys/block/${dev}/device/model" 2>/dev/null | xargs \
                    || echo "NVMe SSD")

        # USB detection (check transport before rotational — USB HDDs exist)
        elif [[ "$(cat /sys/block/${dev}/queue/rotational 2>/dev/null)" == "0" ]] \
             && _is_usb_drive "$dev"; then
            type="usb-ssd"
            transport="usb"
            model=$(cat "/sys/block/${dev}/device/model" 2>/dev/null | xargs || echo "USB SSD")

        elif _is_usb_drive "$dev"; then
            type="usb-hdd"
            transport="usb"
            model=$(cat "/sys/block/${dev}/device/model" 2>/dev/null | xargs || echo "USB HDD")

        # SSD (rotational=0, SATA or other non-NVMe)
        elif [[ "$(cat /sys/block/${dev}/queue/rotational 2>/dev/null)" == "0" ]]; then
            type="ssd"
            transport=$(cat "/sys/block/${dev}/queue/zoned" 2>/dev/null \
                        || _get_transport "$dev" || echo "sata")
            model=$(cat "/sys/block/${dev}/device/model" 2>/dev/null | xargs \
                    || smartctl -i "/dev/${dev}" 2>/dev/null | awk -F': ' '/Device Model/{print $2}' | xargs \
                    || echo "SATA SSD")

        # HDD (rotational=1)
        elif [[ "$(cat /sys/block/${dev}/queue/rotational 2>/dev/null)" == "1" ]]; then
            type="hdd"
            transport=$(_get_transport "$dev" || echo "sata")
            model=$(cat "/sys/block/${dev}/device/model" 2>/dev/null | xargs \
                    || smartctl -i "/dev/${dev}" 2>/dev/null | awk -F': ' '/Device Model/{print $2}' | xargs \
                    || echo "HDD")
        fi

        # Size
        size_bytes=$(cat "/sys/block/${dev}/size" 2>/dev/null || echo "0")
        size_bytes=$(( size_bytes * 512 ))
        if [[ $size_bytes -gt 0 ]]; then
            size_human=$(awk "BEGIN{
                n=${size_bytes}
                if(n>1099511627776) printf \"%.1fTB\", n/1099511627776
                else if(n>1073741824) printf \"%.1fGB\", n/1073741824
                else printf \"%.0fMB\", n/1048576
            }")
        fi

        # Collect SMART briefly
        local smart_health="UNKNOWN"
        if [[ "$type" == "nvme" ]]; then
            smart_health=$(nvme smart-log "/dev/${dev}" 2>/dev/null \
                | awk '/critical_warning/{print ($NF=="0x0")?"PASSED":"WARNING"}' | head -1 \
                || echo "UNKNOWN")
        else
            smart_health=$(smartctl -H "/dev/${dev}" 2>/dev/null \
                | awk '/result:/{print $NF}' | head -1 || echo "UNKNOWN")
        fi

        # Build JSON entry
        $first || registry="${registry},"
        first=false
        registry="${registry}{\"dev\":\"/dev/${dev}\",\"type\":\"${type}\",\"transport\":\"${transport}\",\"model\":\"${model}\",\"size\":\"${size_human}\",\"size_bytes\":${size_bytes},\"smart\":\"${smart_health}\",\"system_disk\":${is_sys}}"

        info "  /dev/${dev}: ${type} | ${model} | ${size_human} | SMART: ${smart_health}$( $is_sys && echo ' [SYSTEM]' || true)"

    done < <(lsblk -dno NAME 2>/dev/null)

    registry="${registry}]}"

    echo "$registry" > "$DRIVE_REGISTRY"
    chmod 644 "$DRIVE_REGISTRY"

    # Summary
    local hdd_count ssd_count nvme_count usb_count
    hdd_count=$(echo "$registry" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for x in d['drives'] if x['type']=='hdd'))")
    ssd_count=$(echo "$registry"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for x in d['drives'] if x['type']=='ssd'))")
    nvme_count=$(echo "$registry" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for x in d['drives'] if x['type']=='nvme'))")
    usb_count=$(echo "$registry"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for x in d['drives'] if 'usb' in x['type']))")

    forgenas_set "DRIVE_HDD_COUNT"  "${hdd_count:-0}"
    forgenas_set "DRIVE_SSD_COUNT"  "${ssd_count:-0}"
    forgenas_set "DRIVE_NVME_COUNT" "${nvme_count:-0}"
    forgenas_set "DRIVE_USB_COUNT"  "${usb_count:-0}"

    info "Drive inventory: ${hdd_count:-0} HDD | ${ssd_count:-0} SSD | ${nvme_count:-0} NVMe | ${usb_count:-0} USB"
    info "Registry: $DRIVE_REGISTRY"
}

_is_usb_drive() {
    local dev="$1"
    # Walk sysfs to find transport
    local sysdev="/sys/block/${dev}"
    if readlink -f "${sysdev}" 2>/dev/null | grep -qi "usb"; then
        return 0
    fi
    local transport; transport=$(udevadm info --query=property "/dev/${dev}" 2>/dev/null \
        | awk -F= '/ID_BUS/{print $2}' | head -1 || echo "")
    [[ "$transport" == "usb" ]]
}

_get_transport() {
    local dev="$1"
    udevadm info --query=property "/dev/${dev}" 2>/dev/null \
        | awk -F= '/ID_BUS/{print $2}' | head -1 \
        || echo "sata"
}

# API endpoint for Web UI
install_drive_api() {
    cat > /usr/local/bin/forgeos-drives << 'DRVAPI'
#!/usr/bin/env bash
# ForgeOS Drive Registry API
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-list}"; shift || true

case "$CMD" in
list)
    # Refresh and output JSON
    python3 /opt/forgeos/scripts/drive-scan.py 2>/dev/null \
        || cat /etc/forgeos/drives.json 2>/dev/null \
        || echo '{"drives":[]}'
    ;;
scan)
    # Re-run detection
    bash /opt/forgeos/install/modules/03c-drive-types.sh
    ;;
type)
    dev="${1:?device}"
    python3 -c "
import json
d=json.load(open('/etc/forgeos/drives.json'))
for x in d['drives']:
    if x['dev']=='/dev/${dev}' or x['dev']=='${dev}':
        print(x.get('type','unknown'))
        break
" 2>/dev/null || echo "unknown"
    ;;
esac
DRVAPI
    chmod +x /usr/local/bin/forgeos-drives
}

# ============================================================
# BCACHE CACHE DRIVE SETUP
# ============================================================
install_bcache() {
    step "Installing bcache utilities"
    apt_install bcache-tools
    info "bcache-tools installed"
}

setup_cache_drive() {
    # Usage: setup_cache_drive <cache_dev> <backing_dev> [mode]
    # Example: setup_cache_drive /dev/nvme0n1 /dev/sda writeback
    local cache_dev="${1:?cache device (SSD/NVMe)}"
    local backing_dev="${2:?backing device (HDD)}"
    local mode="${3:-writeback}"
    local cache_type

    # Determine cache device type for user confirmation
    cache_type=$(forgeos-drives type "$(basename "$cache_dev")" 2>/dev/null || echo "unknown")
    info "Setting up bcache: ${cache_dev} (${cache_type}) caching ${backing_dev} [${mode}]"

    # Safety: refuse to cache a system disk
    local sys_disk; sys_disk=$(get_system_disk)
    if [[ "$backing_dev" == "$sys_disk"* || "$cache_dev" == "$sys_disk"* ]]; then
        die "ABORT: system disk detected ($sys_disk). Cache setup refused to protect OS."
    fi

    # Wipe and format both devices
    wipefs -a "$cache_dev"   >> "$FORGENAS_LOG" 2>&1 || true
    wipefs -a "$backing_dev" >> "$FORGENAS_LOG" 2>&1 || true

    # Register backing device
    make-bcache -B "$backing_dev" >> "$FORGENAS_LOG" 2>&1 || \
        die "make-bcache backing failed on $backing_dev"

    # Register cache device
    make-bcache -C "$cache_dev" >> "$FORGENAS_LOG" 2>&1 || \
        die "make-bcache cache failed on $cache_dev"

    # Wait for bcache devices to appear
    sleep 2
    udevadm trigger && udevadm settle

    # Find the bcache device
    local bcache_dev
    bcache_dev=$(ls /dev/bcache* 2>/dev/null | head -1)
    [[ -z "$bcache_dev" ]] && die "No /dev/bcache* appeared after make-bcache"

    # Attach cache to backing
    local cache_set_uuid
    cache_set_uuid=$(bcache-super-show "$cache_dev" 2>/dev/null \
        | awk '/cset.uuid/{print $2}' | head -1 || echo "")
    if [[ -n "$cache_set_uuid" ]]; then
        echo "$cache_set_uuid" > "/sys/block/$(basename "$bcache_dev")/bcache/attach" 2>/dev/null || true
    fi

    # Set cache mode
    echo "$mode" > "/sys/block/$(basename "$bcache_dev")/bcache/cache_mode" 2>/dev/null \
        || warn "Could not set cache mode — may need reboot"

    # Persist cache mode across reboots
    cat >> /etc/rc.local << RCLOCAL
# ForgeOS bcache mode
echo ${mode} > /sys/block/$(basename "$bcache_dev")/bcache/cache_mode 2>/dev/null || true
RCLOCAL

    # Save to registry
    forgenas_set "BCACHE_CACHE_DEV"   "$cache_dev"
    forgenas_set "BCACHE_BACKING_DEV" "$backing_dev"
    forgenas_set "BCACHE_DEVICE"      "$bcache_dev"
    forgenas_set "BCACHE_MODE"        "$mode"
    forgenas_set "BCACHE_ENABLED"     "yes"

    info "bcache configured: ${cache_dev} → ${bcache_dev} (mode: ${mode})"
    info "  Use ${bcache_dev} as your LVM physical volume or format directly"
    warn "  bcache devices persist across reboots but may need 'bcache-register' if they disappear"
}

# bcache management script exposed to Web UI API
install_cache_management() {
    step "Installing cache drive management"

    cat > /usr/local/bin/forgeos-cache << 'CACHECLI'
#!/usr/bin/env bash
# ForgeOS Cache Drive Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

case "$CMD" in
status)
    echo "=== ForgeOS Cache Drives ==="
    for bcdev in /sys/block/bcache*/bcache; do
        [[ -d "$bcdev" ]] || continue
        local dev; dev=$(basename "$(dirname "$bcdev")")
        local state; state=$(cat "$bcdev/state" 2>/dev/null || echo "unknown")
        local mode;  mode=$(cat "$bcdev/cache_mode" 2>/dev/null || echo "N/A")
        local stats; stats=$(cat "$bcdev/stats_total/cache_hits" 2>/dev/null || echo "0")
        local misses; misses=$(cat "$bcdev/stats_total/cache_misses" 2>/dev/null || echo "0")
        local total=$(( stats + misses )); local hitratio=0
        [[ $total -gt 0 ]] && hitratio=$(( stats * 100 / total ))
        echo "  /dev/${dev}  state=${state}  mode=${mode}"
        echo "    Cache hits: ${stats}  misses: ${misses}  hit rate: ${hitratio}%"
        local backing; backing=$(readlink -f "${bcdev}/../.." 2>/dev/null | xargs basename 2>/dev/null || echo "?")
        echo "    Backing device: /dev/${backing}"
    done
    [[ ! -d /sys/block/bcache0 ]] && echo "  No cache drives configured"
    ;;
setup)
    [[ $# -lt 2 ]] && { echo "Usage: forgeos-cache setup <cache_dev> <backing_dev> [writeback|writethrough|writearound]"; exit 1; }
    cache_dev="$1" backing_dev="$2" mode="${3:-writeback}"
    # Validate device types
    cache_type=$(forgeos-drives type "$(basename "$cache_dev")" 2>/dev/null || echo "unknown")
    if [[ "$cache_type" == "hdd" ]]; then
        echo "WARNING: $cache_dev is detected as HDD — cache drives should be SSD or NVMe for performance"
        read -rp "Continue anyway? [y/N]: " ans
        [[ "${ans,,}" == "y" ]] || exit 0
    fi
    bash -c "source /opt/forgeos/install/modules/03c-drive-types.sh 2>/dev/null; setup_cache_drive '$cache_dev' '$backing_dev' '$mode'" \
        || { echo "Cache setup failed — check logs"; exit 1; }
    ;;
mode)
    local dev="${1:-bcache0}" mode="${2:?mode}"
    echo "$mode" > "/sys/block/${dev}/bcache/cache_mode" \
        && echo "Cache mode set: $mode" || echo "Failed (device may not exist)"
    ;;
detach)
    local dev="${1:-bcache0}"
    echo 1 > "/sys/block/${dev}/bcache/detach" 2>/dev/null \
        && echo "Cache detached from $dev" || echo "Detach failed"
    ;;
stats)
    for f in /sys/block/bcache*/bcache/stats_total; do
        [[ -d "$f" ]] || continue
        local dev; dev=$(echo "$f" | cut -d/ -f5)
        echo "  /dev/${dev}:"
        for s in "$f"/cache_*; do
            [[ -f "$s" ]] || continue
            printf "    %-40s %s\n" "$(basename "$s"):" "$(cat "$s")"
        done
    done
    ;;
register)
    # Re-register bcache devices after reboot if they don't auto-appear
    for dev in /dev/sd* /dev/nvme*n*; do
        [[ -b "$dev" ]] || continue
        bcache-super-show "$dev" 2>/dev/null | grep -q "sb.version" \
            && echo "$dev" > /sys/fs/bcache/register 2>/dev/null && echo "Registered: $dev" || true
    done
    ;;
help|*)
    echo "ForgeOS Cache Drive Manager"
    echo ""
    echo "  status                         All bcache devices + hit rates"
    echo "  setup <cache> <backing> [mode] Configure cache drive"
    echo "    modes: writeback (default), writethrough, writearound, none"
    echo "    Example: forgeos-cache setup /dev/nvme0n1 /dev/sda writeback"
    echo "  mode <bcache_dev> <mode>       Change cache mode live"
    echo "  detach <bcache_dev>            Detach cache (passthrough mode)"
    echo "  stats                          Detailed hit/miss statistics"
    echo "  register                       Re-register after reboot"
    echo ""
    echo "  RECOMMENDED:"
    echo "    NVMe as cache: writeback (best performance)"
    echo "    SSD as cache < 50GB: writethrough (safer)"
    echo "    Backup pools: writearound (sequential writes bypass cache)"
    ;;
esac
CACHECLI
    chmod +x /usr/local/bin/forgeos-cache

    # API endpoint for Web UI
    cat > /opt/forgeos/scripts/drive-scan.py << 'DRVPY'
#!/usr/bin/env python3
"""ForgeOS drive scan — called by Web UI for live drive type data"""
import json, os, subprocess, re
from pathlib import Path

def read_file(path, default=""):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default

def is_usb(dev):
    syslink = subprocess.getoutput(f"readlink -f /sys/block/{dev}") or ""
    return "usb" in syslink.lower()

def get_type(dev):
    if dev.startswith("nvme"):
        return "nvme"
    if is_usb(dev):
        rot = read_file(f"/sys/block/{dev}/queue/rotational", "1")
        return "usb-ssd" if rot == "0" else "usb-hdd"
    rot = read_file(f"/sys/block/{dev}/queue/rotational", "1")
    return "ssd" if rot == "0" else "hdd"

def get_size(dev):
    sectors = int(read_file(f"/sys/block/{dev}/size", "0"))
    b = sectors * 512
    if b > 1e12: return f"{b/1e12:.1f}TB"
    if b > 1e9:  return f"{b/1e9:.1f}GB"
    return f"{b/1e6:.0f}MB"

def get_model(dev):
    paths = [
        f"/sys/block/{dev}/device/model",
        f"/sys/block/{dev}/device/name",
    ]
    for p in paths:
        v = read_file(p)
        if v:
            return v.strip()
    return "Unknown"

def get_smart_level(dev, dtype):
    try:
        out = subprocess.check_output(["smartctl", "-H", f"/dev/{dev}"],
            stderr=subprocess.DEVNULL, text=True, timeout=5)
        if "PASSED" in out: return "ok"
        if "FAILED" in out: return "err"
    except Exception:
        pass
    return "unknown"

sys_disk = subprocess.getoutput(
    "lsblk -no pkname $(findmnt -n -o SOURCE /) 2>/dev/null | head -1").strip()

drives = []
for dev in sorted(os.listdir("/sys/block")):
    if re.match(r"^(loop|sr|md|dm|ram|zram|bcache)", dev):
        continue
    if not os.path.isfile(f"/sys/block/{dev}/size"):
        continue
    dtype = get_type(dev)
    is_sys = (dev == sys_disk or dev.startswith(sys_disk))
    
    # Cache info
    bcache_info = {}
    if os.path.isdir(f"/sys/block/{dev}/bcache"):
        bcache_info = {
            "is_bcache": True,
            "mode": read_file(f"/sys/block/{dev}/bcache/cache_mode"),
            "state": read_file(f"/sys/block/{dev}/bcache/state"),
        }
    
    drives.append({
        "dev": f"/dev/{dev}",
        "name": dev,
        "type": dtype,
        "model": get_model(dev),
        "size": get_size(dev),
        "system_disk": is_sys,
        "smart_level": get_smart_level(dev, dtype) if not is_sys else "ok",
        **bcache_info,
    })

print(json.dumps({"drives": drives}, indent=2))
DRVPY
    chmod +x /opt/forgeos/scripts/drive-scan.py
}

# ============================================================
# MAIN
# ============================================================
detect_drive_types
install_bcache
install_cache_management
install_drive_api

forgenas_set "MODULE_DRIVE_TYPES_DONE" "yes"
info "Drive classification + cache module complete"
info "  Drive list:     forgeos-drives list"
info "  Cache status:   forgeos-cache status"
info "  Setup cache:    forgeos-cache setup /dev/nvme0n1 /dev/sda writeback"
info "  Registry:       $DRIVE_REGISTRY"
