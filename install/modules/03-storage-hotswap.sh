#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 03 - ForgeRAID Storage
# Includes: Hot-swap detection, SMART predictive failure,
#           pool-grouped drive monitoring, udev auto-handling
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

# ============================================================
# PACKAGES
# ============================================================
install_storage_packages() {
    step "Installing storage packages"
    apt_install \
        mdadm lvm2 btrfs-progs snapper parted gdisk \
        hdparm nvme-cli sg3-utils smartmontools \
        lsscsi inotify-tools bc udev

    # smartmontools daemon for continuous monitoring
    systemctl enable smartd 2>/dev/null || true
    info "Storage packages installed"
}

# ============================================================
# HOT-SWAP INFRASTRUCTURE
#
# How hot-swap detection works:
#   1. udev fires /add or /remove event when drive appears/disappears
#   2. Our udev rule calls forgeos-hotswap
#   3. forgeos-hotswap:
#      ADD:  SMART check → if healthy, offer to add to pool or spare
#            Notify Web UI via API
#      REMOVE: Check if drive was in an array → mark degraded
#              Notify Web UI + Gotify + Apprise
# ============================================================
setup_hotswap() {
    step "Configuring hot-swap detection"

    mkdir -p /opt/forgeos/scripts

    # udev rule — fires on block device add/remove
    cat > /etc/udev/rules.d/90-forgeos-hotswap.rules << 'UDEV'
# ForgeOS hot-swap detection
# Fires for SATA/SAS drives and NVMe devices

# Drive added
ACTION=="add", SUBSYSTEM=="block", KERNEL=="sd[a-z]|sd[a-z][a-z]", \
    ENV{DEVTYPE}=="disk", \
    RUN+="/bin/bash -c '/opt/forgeos/scripts/forgeos-hotswap add $env{DEVNAME} >> /var/log/forgeos/hotswap.log 2>&1 &'"

# NVMe added
ACTION=="add", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", \
    ENV{DEVTYPE}=="disk", \
    RUN+="/bin/bash -c '/opt/forgeos/scripts/forgeos-hotswap add $env{DEVNAME} >> /var/log/forgeos/hotswap.log 2>&1 &'"

# Drive removed
ACTION=="remove", SUBSYSTEM=="block", KERNEL=="sd[a-z]|sd[a-z][a-z]|nvme[0-9]n[0-9]", \
    ENV{DEVTYPE}=="disk", \
    RUN+="/bin/bash -c '/opt/forgeos/scripts/forgeos-hotswap remove $env{DEVNAME} >> /var/log/forgeos/hotswap.log 2>&1 &'"
UDEV

    # Hot-swap handler script
    cat > /opt/forgeos/scripts/forgeos-hotswap << 'HOTSWAP'
#!/usr/bin/env bash
# ForgeOS hot-swap event handler
# Called by udev on drive add/remove
source /etc/forgeos/forgeos.conf 2>/dev/null || true

ACTION="$1"
DEVICE="$2"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG="/var/log/forgeos/hotswap.log"
mkdir -p "$(dirname "$LOG")"

notify() {
    local level="$1" title="$2" msg="$3"
    # ForgeOS API
    curl -sf -X POST "http://localhost:5080/api/notify" \
        -H "Content-Type: application/json" \
        -d "{\"level\":\"${level}\",\"title\":\"${title}\",\"message\":\"${msg}\"}" \
        2>/dev/null || true
    # System log
    logger -t forgeos-hotswap "${level}: ${title}: ${msg}"
    echo "[$TIMESTAMP] ${level}: ${title}: ${msg}" >> "$LOG"
}

smart_check() {
    local dev="$1"
    local result
    result=$(smartctl -H "$dev" 2>/dev/null | grep -i 'result\|SMART Health' || echo "UNKNOWN")
    if echo "$result" | grep -qi 'PASSED\|OK'; then
        echo "PASSED"
    elif echo "$result" | grep -qi 'FAILED'; then
        echo "FAILED"
    else
        echo "UNKNOWN"
    fi
}

get_smart_attrs() {
    # Returns key indicators: reallocated, pending, uncorrectable
    local dev="$1"
    local reallocated pending uncorrectable
    reallocated=$(smartctl -A "$dev" 2>/dev/null | awk '/Reallocated_Sector_Ct/{print $10}' | head -1 || echo "0")
    pending=$(smartctl -A "$dev" 2>/dev/null | awk '/Current_Pending_Sector/{print $10}' | head -1 || echo "0")
    uncorrectable=$(smartctl -A "$dev" 2>/dev/null | awk '/Offline_Uncorrectable/{print $10}' | head -1 || echo "0")
    echo "${reallocated:-0} ${pending:-0} ${uncorrectable:-0}"
}

is_in_array() {
    local dev="$1"
    grep -qs "$dev" /proc/mdstat 2>/dev/null
}

find_array_for_dev() {
    local dev="$1"
    mdadm --examine "$dev" 2>/dev/null | grep 'Array UUID\|Raid Level\|Array Name' || echo ""
}

case "$ACTION" in
    add)
        sleep 3  # Let udev finish settling
        echo "[$TIMESTAMP] Drive added: $DEVICE" >> "$LOG"

        # SMART check on newly inserted drive
        local smart_status; smart_status=$(smart_check "$DEVICE")
        read -r reallocated pending uncorrectable <<< "$(get_smart_attrs "$DEVICE")"
        local model; model=$(smartctl -i "$DEVICE" 2>/dev/null | awk -F': ' '/Device Model/{print $2}' | xargs || echo "Unknown")
        local size; size=$(blockdev --getsize64 "$DEVICE" 2>/dev/null | awk '{printf "%.1f TB", $1/1099511627776}')

        if [[ "$smart_status" == "FAILED" || "$uncorrectable" -gt 0 ]]; then
            notify "critical" \
                "Hot-Swap: Faulty Drive Inserted — $DEVICE" \
                "Model: $model | Size: $size | SMART FAILED | Uncorrectable: $uncorrectable. Do NOT add to pool."
        elif [[ "$reallocated" -gt 20 || "$pending" -gt 5 ]]; then
            notify "warning" \
                "Hot-Swap: Drive Inserted with SMART Warnings — $DEVICE" \
                "Model: $model | Reallocated: $reallocated | Pending: $pending. Monitor carefully before adding to pool."
        else
            notify "info" \
                "Hot-Swap: Drive Inserted — $DEVICE" \
                "Model: $model | Size: $size | SMART OK | Ready to add to pool via Storage > ForgeRAID."
        fi

        # Check if this is a known array member (auto-rejoin after pull)
        if is_in_array "${DEVICE}1" || is_in_array "${DEVICE}p1"; then
            local md_dev
            md_dev=$(mdadm --examine "${DEVICE}1" 2>/dev/null | awk '/^\/dev\/md/{print $1}' | head -1 || true)
            if [[ -n "$md_dev" ]]; then
                notify "info" \
                    "Hot-Swap: Re-adding $DEVICE to array $md_dev" \
                    "Drive was part of a ForgeRAID array. Auto-re-adding as spare/replacement."
                # Re-add to array (mdadm handles failover automatically)
                mdadm --manage "$md_dev" --add "${DEVICE}1" >> "$LOG" 2>&1 \
                    || mdadm --manage "$md_dev" --add "${DEVICE}p1" >> "$LOG" 2>&1 \
                    || true
            fi
        fi
        ;;

    remove)
        echo "[$TIMESTAMP] Drive removed: $DEVICE" >> "$LOG"
        local was_in_pool=false array_name=""

        # Check if removed device was in an mdadm array
        if grep -qs "${DEVICE##/dev/}" /proc/mdstat 2>/dev/null; then
            was_in_pool=true
            array_name=$(grep -B2 "${DEVICE##/dev/}" /proc/mdstat | grep ^md | head -1)
        fi

        if $was_in_pool; then
            notify "critical" \
                "Hot-Swap: Pool Drive Removed — $DEVICE" \
                "Drive was in array ${array_name:-unknown}. Array is now DEGRADED. Replace drive to rebuild. Data safe if ForgeRAID-2."
        else
            notify "info" \
                "Hot-Swap: Drive Removed — $DEVICE" \
                "Unassigned/spare drive removed. No pool impact."
        fi
        ;;
esac
HOTSWAP
    chmod +x /opt/forgeos/scripts/forgeos-hotswap

    mkdir -p /var/log/forgeos
    udevadm control --reload-rules 2>/dev/null || true
    info "Hot-swap detection configured"
}

# ============================================================
# SMART MONITORING — PREDICTIVE FAILURE
#
# Thresholds that indicate a drive is failing BEFORE it dies:
#   ID 5   Reallocated_Sector_Ct > 10   (bad sectors remapped)
#   ID 187 Reported_Uncorrect    > 0    (uncorrectable errors)
#   ID 188 Command_Timeout       > 5
#   ID 196 Reallocated_Event_Cnt > 10
#   ID 197 Current_Pending_Sector > 0   (sectors waiting to be reallocated)
#   ID 198 Offline_Uncorrectable > 0    (failed to remap)
#   NVMe:  Critical Warning      != 0
# ============================================================
configure_smart_monitoring() {
    step "Configuring SMART predictive failure monitoring"

    # Configure smartd daemon with aggressive monitoring
    cat > /etc/smartd.conf << 'SMARTD'
# ForgeOS SMART Monitoring Configuration
# Monitors ALL drives every 30 minutes, alerts on any degradation

# Monitor all detected drives
DEVICESCAN \
    -a \
    -o on \
    -S on \
    -n standby,q \
    -s (S/../.././02|L/../../6/03) \
    -W 4,45,55 \
    -R 5 \
    -R 187 \
    -R 196 \
    -R 197 \
    -R 198 \
    -m root \
    -M exec /opt/forgeos/scripts/forgeos-smart-alert

# Explanation of flags:
# -a           : Monitor all SMART attributes
# -o on        : Enable offline data collection
# -S on        : Enable attribute autosave
# -n standby,q : Don't wake sleeping drives, quiet if spun down
# -s S/../.././02  : Short self-test every day at 02:00
# -s L/../../6/03  : Long self-test every Saturday at 03:00
# -W 4,45,55   : Warn at 45°C, fail at 55°C, threshold change 4°C
# -R 5         : Report reallocated sector changes (ANY change = alert)
# -R 187       : Report reported uncorrectable errors
# -R 196       : Report reallocated event count changes
# -R 197       : Report pending sectors (imminent failure)
# -R 198       : Report offline uncorrectable count
SMARTD

    # SMART alert handler — fires when smartd detects an issue
    cat > /opt/forgeos/scripts/forgeos-smart-alert << 'SMARTALERT'
#!/usr/bin/env bash
# ForgeOS SMART Alert Handler
# Called by smartd when a drive attribute crosses a threshold
source /etc/forgeos/forgeos.conf 2>/dev/null || true

DEVICE="$SMARTD_DEVICE"
FAILTYPE="$SMARTD_FAILTYPE"
MESSAGE="$SMARTD_MESSAGE"
TEMPERATURE="${SMARTD_TEMPERATURE:-0}"
MAILER="${SMARTD_ADDRESS:-root}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Determine severity
case "$FAILTYPE" in
    "Health Status change"*|"SMART Usage Attribute"*)
        LEVEL="warning"
        ;;
    "SMART Prefailure Attribute"*|"Device open failed"*)
        LEVEL="critical"
        ;;
    "Temperature"*)
        [[ "$TEMPERATURE" -ge 55 ]] && LEVEL="critical" || LEVEL="warning"
        ;;
    *)
        LEVEL="warning"
        ;;
esac

TITLE="SMART Alert: ${DEVICE}"
MSG="Type: ${FAILTYPE} | ${MESSAGE} | Temp: ${TEMPERATURE}°C | Time: ${TIMESTAMP}"

# Get current SMART critical attributes for context
ATTRS=$(smartctl -A "$DEVICE" 2>/dev/null | awk '
    /Reallocated_Sector_Ct|Current_Pending_Sector|Offline_Uncorrectable|Reported_Uncorrect/ {
        printf "%s=%s ", $2, $10
    }' || echo "")
[[ -n "$ATTRS" ]] && MSG="${MSG} | SMART: ${ATTRS}"

# Notify via ForgeOS API (Web UI, Gotify, Apprise)
curl -sf -X POST "http://localhost:5080/api/notify" \
    -H "Content-Type: application/json" \
    -d "{\"level\":\"${LEVEL}\",\"title\":\"${TITLE}\",\"message\":\"${MSG}\"}" \
    2>/dev/null || true

# Taskbar tray indicator update
curl -sf -X POST "http://localhost:5080/api/drive-alert" \
    -H "Content-Type: application/json" \
    -d "{\"device\":\"${DEVICE}\",\"level\":\"${LEVEL}\",\"message\":\"${MSG}\"}" \
    2>/dev/null || true

# System logger
logger -t forgeos-smart "${LEVEL}: ${DEVICE}: ${FAILTYPE}: ${MESSAGE}"
echo "[$TIMESTAMP] ${LEVEL}: ${DEVICE}: ${MSG}" >> /var/log/forgeos/smart-alerts.log
SMARTALERT
    chmod +x /opt/forgeos/scripts/forgeos-smart-alert

    enable_service smartd
    info "SMART monitoring: continuous, 30-min intervals, predictive failure alerts"
    info "  Alerts sent to: Web UI tray, Gotify, Apprise, system log"
    info "  Alert log: /var/log/forgeos/smart-alerts.log"
}

# ============================================================
# POOL STATUS API ENDPOINT (for Web UI drive grouping)
# Returns JSON with drives grouped by pool
# Called by the Web UI every 5 seconds for live dashboard
# ============================================================
create_pool_status_api() {
    step "Creating pool status reporter"

    cat > /usr/local/bin/forgeos-pool-status << 'POOLSTAT'
#!/usr/bin/env bash
# ForgeOS Pool Status — JSON output for Web UI
# Web UI calls this to populate the pool-grouped drive view
# Output: {pools: [{name, type, health, used, total, drives: [...]}]}

source /etc/forgeos/forgeos.conf 2>/dev/null || true

get_drive_smart() {
    local dev="$1"
    local reallocated pending uncorrectable temp health
    health=$(smartctl -H "$dev" 2>/dev/null | awk '/result/{print $NF}' || echo "UNKNOWN")
    reallocated=$(smartctl -A "$dev" 2>/dev/null | awk '/Reallocated_Sector_Ct/{print $10}' | head -1 || echo "0")
    pending=$(smartctl -A "$dev" 2>/dev/null | awk '/Current_Pending_Sector/{print $10}' | head -1 || echo "0")
    uncorrectable=$(smartctl -A "$dev" 2>/dev/null | awk '/Offline_Uncorrectable/{print $10}' | head -1 || echo "0")
    temp=$(smartctl -A "$dev" 2>/dev/null | awk '/Temperature_Celsius/{print $10}' | head -1 \
           || smartctl -x "$dev" 2>/dev/null | awk '/Temperature:/{print $2}' | head -1 || echo "0")

    # Determine smart_level
    local smart_level="ok"
    [[ "${uncorrectable:-0}" -gt 0 ]] && smart_level="err"
    [[ "${reallocated:-0}" -gt 20 || "${pending:-0}" -gt 5 ]] && smart_level="warn"
    [[ "${reallocated:-0}" -gt 5  || "${pending:-0}" -gt 0  ]] && [[ "$smart_level" == "ok" ]] && smart_level="predict"
    [[ "$health" == "FAILED" ]] && smart_level="err"

    echo "{\"health\":\"${health}\",\"reallocated\":${reallocated:-0},\"pending\":${pending:-0},\"uncorrectable\":${uncorrectable:-0},\"temp\":${temp:-0},\"smart_level\":\"${smart_level}\"}"
}

# Build pool list from mdadm + btrfs
python3 << 'PYSTAT'
import subprocess, json, os, re

def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True).strip()
    except:
        return ""

def get_mdstat():
    """Parse /proc/mdstat into pool → device mapping"""
    pools = {}
    current = None
    try:
        for line in open('/proc/mdstat'):
            m = re.match(r'^(md\d+)\s*:\s*(\w+)\s+(\w+)', line)
            if m:
                current = m.group(1)
                pools[current] = {'state': m.group(2), 'level': m.group(3), 'devs': [], 'rebuild': None}
            elif current and re.search(r'sd[a-z]+\d+|nvme\d+n\d+p\d+', line):
                devs = re.findall(r'(sd[a-z]+|nvme\d+n\d+)\d*', line)
                pools[current]['devs'] = list(set(devs))
            elif current and 'recovery' in line:
                pct = re.search(r'(\d+\.\d+)%', line)
                pools[current]['rebuild'] = pct.group(1) if pct else '?'
    except:
        pass
    return pools

def get_lvm_pools():
    """Get LVM VGs and map to mdadm arrays"""
    vg_map = {}
    out = run("vgs --noheadings -o vg_name,pv_name 2>/dev/null")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            vg, pv = parts[0], parts[1]
            md = re.search(r'(md\d+)', pv)
            if md:
                vg_map[vg] = vg_map.get(vg, []) + [md.group(1)]
    return vg_map

def get_btrfs_pools():
    """Get btrfs filesystems and their devices"""
    pools = {}
    current = None
    out = run("btrfs filesystem show 2>/dev/null")
    for line in out.splitlines():
        m = re.search(r"Label: '?([^']+)'?", line)
        if m:
            current = m.group(1).strip()
            pools[current] = {'devs': [], 'used': 0, 'total': 0}
        elif current and 'devid' in line:
            dev = re.search(r'/dev/(\S+)', line)
            if dev:
                pools[current]['devs'].append('/dev/' + dev.group(1))
            sz = re.search(r'size (\S+)', line)
            used = re.search(r'used (\S+)', line)
            # parse sizes
    return pools

def btrfs_usage(mountpoint):
    out = run(f"btrfs filesystem usage {mountpoint} 2>/dev/null")
    used = total = 0
    for line in out.splitlines():
        m = re.search(r'Device size:\s+(\S+)', line)
        if m: total = m.group(1)
        m = re.search(r'Used:\s+(\S+)', line)
        if m: used = m.group(1)
    return used, total

def get_drive_info(dev):
    """Get drive model, size, temp from smartctl"""
    info = {'dev': dev, 'model': 'Unknown', 'size': '?', 'temp': 0,
            'smart': 'UNKNOWN', 'reallocated': 0, 'pending': 0, 'smart_level': 'ok'}
    out = run(f"smartctl -i -A -H /dev/{dev} 2>/dev/null")
    m = re.search(r'Device Model:\s+(.+)', out)
    if m: info['model'] = m.group(1).strip()
    m = re.search(r'User Capacity:.+\[(.+)\]', out)
    if m: info['size'] = m.group(1).strip()
    m = re.search(r'Temperature_Celsius\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)', out)
    if m: info['temp'] = int(m.group(1))
    m = re.search(r'result: (\w+)', out)
    if m: info['smart'] = m.group(1)
    m = re.search(r'Reallocated_Sector_Ct.+?(\d+)\n', out)
    if m: info['reallocated'] = int(m.group(1))
    m = re.search(r'Current_Pending_Sector.+?(\d+)\n', out)
    if m: info['pending'] = int(m.group(1))
    m = re.search(r'Offline_Uncorrectable.+?(\d+)\n', out)
    if m: info['uncorrectable'] = int(m.group(1) if m else '0')

    # smart_level
    sl = 'ok'
    if info.get('uncorrectable', 0) > 0: sl = 'err'
    elif info['reallocated'] > 20 or info['pending'] > 5: sl = 'warn'
    elif info['reallocated'] > 5  or info['pending'] > 0: sl = 'predict'
    if info['smart'] == 'FAILED': sl = 'err'
    info['smart_level'] = sl
    info['temp_level'] = 'hot' if info['temp'] >= 55 else ('warn' if info['temp'] >= 45 else 'ok')
    return info

# Build output
mdstat = get_mdstat()
lvm = get_lvm_pools()
result = {'pools': [], 'unassigned': []}

# Get all physical disks
all_devs = set()
for line in run("lsblk -dno NAME,TYPE").splitlines():
    p = line.split()
    if len(p) == 2 and p[1] == 'disk':
        all_devs.add(p[0])

# Map devices to their pools
dev_to_pool = {}

# Find btrfs mounts
for line in run("findmnt -t btrfs -o TARGET,SOURCE -n").splitlines():
    parts = line.split()
    if len(parts) < 2: continue
    mp, src = parts[0], parts[1]
    # Find what disks back this LVM/mdadm
    for md_name, md_info in mdstat.items():
        for d in md_info['devs']:
            if d not in dev_to_pool:
                dev_to_pool[d] = md_name

# Build pool entries
for md_name, md_info in mdstat.items():
    # Find associated btrfs/LVM label
    label = md_name
    for vg, mds in lvm.items():
        if md_name in mds: label = vg; break

    drives = [get_drive_info(d) for d in md_info['devs']]
    health = 'ok'
    if any(d['smart_level'] == 'err' for d in drives): health = 'err'
    elif any(d['smart_level'] == 'warn' for d in drives): health = 'warn'
    elif any(d['smart_level'] == 'predict' for d in drives): health = 'predict'
    if md_info['state'] == 'inactive': health = 'err'
    if md_info.get('rebuild'): health = 'rebuilding'

    result['pools'].append({
        'name': label, 'md': md_name,
        'level': md_info['level'],
        'state': md_info['state'],
        'health': health,
        'rebuild_pct': md_info.get('rebuild'),
        'drives': drives
    })
    for d in md_info['devs']:
        dev_to_pool[d] = md_name

# Unassigned drives
unassigned = []
for dev in sorted(all_devs):
    # Skip if it's a partition or in a pool
    if dev in dev_to_pool: continue
    if re.search(r'\d+$', dev) and not re.search(r'nvme\d+n\d+$', dev): continue
    # Skip system disk
    sys = run("lsblk -no pkname $(findmnt -n -o SOURCE /) 2>/dev/null | head -1").strip()
    if dev == sys: continue
    unassigned.append(get_drive_info(dev))

result['unassigned'] = unassigned
print(json.dumps(result, indent=2))
PYSTAT
POOLSTAT
    chmod +x /usr/local/bin/forgeos-pool-status

    info "Pool status API installed: forgeos-pool-status (JSON output)"
}

# ============================================================
# MDADM ARRAY WIZARD (unchanged from previous, just hot-swap aware)
# ============================================================
install_storage_packages
setup_hotswap
configure_smart_monitoring
create_pool_status_api

# Wire into storage wizard from previous version
# (forgearaid_wizard and mdadm pool creation remain from 03-storage.sh v1)
[[ -f "$(dirname "$0")/03-storage-raid.sh" ]] \
    && source "$(dirname "$0")/03-storage-raid.sh" \
    || info "RAID wizard: run forgeos-storage create-pool to configure pools"

forgenas_set "HOTSWAP_ENABLED" "yes"
forgenas_set "SMART_MONITOR_ENABLED" "yes"

info "Storage monitoring module complete"
info "  Hot-swap:     automatic — plug in drive, get notified"
info "  SMART:        forgeos-pool-status (JSON, for Web UI)"
info "  Alert log:    /var/log/forgeos/smart-alerts.log"
info "  Hot-swap log: /var/log/forgeos/hotswap.log"
