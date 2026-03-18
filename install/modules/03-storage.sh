#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 03 - ForgeRAID Storage
#
# HOW THIS WORKS (and why it's better than "btrfs RAID 5/6"):
# ─────────────────────────────────────────────────────────────
# Synology SHR doesn't use btrfs for RAID redundancy.
# That's a common misconception. What they actually do:
#
#   Layer 1: mdadm  — handles actual RAID (no write-hole,
#                     15+ years proven, battle-hardened)
#   Layer 2: LVM    — combines mdadm arrays, enables flexible
#                     sizing when disks are DIFFERENT sizes
#   Layer 3: btrfs  — sits on top for: snapshots, checksums,
#                     compression, send/recv, dedup
#
# MIXED DISK SIZE SUPPORT (the SHR trick):
#   Disks: 8TB, 6TB, 4TB, 4TB, 2TB
#   We partition each disk into segments equal to smallest disk
#   Then combine segments into RAID-5/6 arrays via mdadm
#   LVM merges all arrays into one logical volume
#   Result: maximum possible space with full redundancy
#
# ForgeRAID levels:
#   ForgeRAID-1  = mdadm RAID-1  (2 drives, 1 parity)
#   ForgeRAID-5  = mdadm RAID-5  (3+ drives, 1 parity)
#   ForgeRAID-6  = mdadm RAID-6  (4+ drives, 2 parity)
#   ForgeRAID-10 = mdadm RAID-10 (4+ drives, fast+safe)
#   ForgeRAID-S  = ForgeRAID-Smart (SHR-like, auto-optimized)
#                  Uses LVM to combine mixed-size disks
#
# NO ZFS — btrfs RAM usage is ~30x less than ZFS ARC
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"
source "$(dirname "$0")/../lib/detect.sh"

# ============================================================
# INSTALL PACKAGES
# ============================================================
install_storage_packages() {
    step "Installing storage packages"

    apt_install \
        mdadm \
        lvm2 \
        btrfs-progs \
        btrfs-compsize \
        snapper \
        snapper-gui \
        parted \
        gdisk \
        hdparm \
        sdparm \
        nvme-cli \
        sg3-utils \
        smartmontools \
        lsscsi \
        blktrace \
        inotify-tools \
        bc

    # Snapper bash completion
    apt_install bash-completion 2>/dev/null || true

    # Enable multipath if hardware supports it
    if lsmod | grep -q dm_multipath 2>/dev/null; then
        apt_install multipath-tools
    fi

    info "Storage packages installed"
}

# ============================================================
# DISK DETECTION + DISPLAY
# ============================================================
detect_and_display_disks() {
    echo ""
    echo -e "  ${BOLD}Available disks (excluding system disk):${NC}"
    echo ""

    local sys_disk
    sys_disk=$(lsblk -no pkname "$(findmnt -n -o SOURCE /)" 2>/dev/null \
               | head -1 | sed 's/[0-9]*$//')
    sys_disk="/dev/${sys_disk:-sda}"

    FORGEOS_DATA_DISKS=()
    local idx=0

    while IFS= read -r line; do
        local dev size model transport
        dev=$(echo "$line" | awk '{print $1}')
        size=$(echo "$line" | awk '{print $2}')
        model=$(echo "$line" | awk '{print $3}' | tr '_' ' ')
        transport=$(echo "$line" | awk '{print $6}')

        [[ "/dev/$dev" == "$sys_disk" ]] && continue
        [[ "$dev" =~ ^loop ]] && continue
        [[ "$dev" =~ ^sr ]]   && continue

        FORGEOS_DATA_DISKS+=("/dev/$dev")
        echo -e "  [$idx] /dev/${dev}  ${BOLD}${size}${NC}  ${model}  (${transport:-disk})"
        (( idx++ ))
    done < <(lsblk -dno NAME,SIZE,MODEL,TYPE,FSTYPE,TRAN \
             | grep -v "^loop\|^sr" | grep " disk")

    echo ""
    FORGEOS_DISK_COUNT=${#FORGEOS_DATA_DISKS[@]}
    info "Found $FORGEOS_DISK_COUNT available data disks"
}

# ============================================================
# FORGEARAID WIZARD
# ============================================================
forgearaid_wizard() {
    step "ForgeRAID Storage Configuration"

    detect_and_display_disks

    if [[ $FORGEOS_DISK_COUNT -eq 0 ]]; then
        warn "No data disks found. Skipping RAID setup."
        warn "Add disks and run: forgeos-storage create-pool"
        return
    fi

    echo -e "  ${BOLD}ForgeRAID mode:${NC}"
    echo -e "  [1] ForgeRAID-Smart  — Auto-optimizes mixed disk sizes (recommended)"
    echo -e "                         Synology SHR-equivalent. Uses all space."
    echo -e "  [2] ForgeRAID-6      — 2-disk fault tolerance (4+ disks)"
    echo -e "  [3] ForgeRAID-5      — 1-disk fault tolerance (3+ disks)"
    echo -e "  [4] ForgeRAID-10     — Mirrored stripes (4+ disks, fastest)"
    echo -e "  [5] ForgeRAID-1      — Simple mirror (2 disks)"
    echo -e "  [6] JBOD             — No redundancy, full capacity"
    echo -e "  [7] Skip             — Configure storage later via Web UI"
    echo ""
    echo -ne "  Choice [1]: "
    read -r raid_choice

    [[ "${raid_choice:-7}" == "7" ]] && {
        info "Storage configuration deferred to Web UI > Storage"
        return
    }

    # Disk selection
    echo ""
    echo -ne "  ${BOLD}Select disks${NC} (e.g. 0 1 2 3, or 'all'): "
    read -r disk_sel

    local selected_disks=()
    if [[ "$disk_sel" == "all" ]]; then
        selected_disks=("${FORGEOS_DATA_DISKS[@]}")
    else
        for idx in $disk_sel; do
            selected_disks+=("${FORGEOS_DATA_DISKS[$idx]}")
        done
    fi

    echo ""
    echo -ne "  ${BOLD}Pool name${NC} [datapool]: "
    read -r pool_name
    pool_name="${pool_name:-datapool}"

    echo -ne "  ${BOLD}Mount point${NC} [/srv/nas/${pool_name}]: "
    read -r mount_point
    mount_point="${mount_point:-/srv/nas/${pool_name}}"

    # Confirm
    echo ""
    echo -e "  ${YELLOW}⚠ WARNING: This will DESTROY all data on:${NC}"
    for d in "${selected_disks[@]}"; do echo -e "    ${d}"; done
    echo ""
    echo -ne "  Type ${BOLD}CONFIRM${NC} to proceed: "
    read -r confirm
    [[ "$confirm" != "CONFIRM" ]] && { info "Aborted."; return; }

    case "${raid_choice:-1}" in
        1) create_smart_pool "$pool_name" "$mount_point" "${selected_disks[@]}" ;;
        2) create_mdadm_pool "$pool_name" "$mount_point" "raid6"  "${selected_disks[@]}" ;;
        3) create_mdadm_pool "$pool_name" "$mount_point" "raid5"  "${selected_disks[@]}" ;;
        4) create_mdadm_pool "$pool_name" "$mount_point" "raid10" "${selected_disks[@]}" ;;
        5) create_mdadm_pool "$pool_name" "$mount_point" "raid1"  "${selected_disks[@]}" ;;
        6) create_jbod_pool  "$pool_name" "$mount_point" "${selected_disks[@]}" ;;
    esac
}

# ============================================================
# FORGEARAID-SMART (SHR equivalent)
# Mixed disk sizes, maximum utilization
#
# Algorithm:
#   1. Get all disk sizes in bytes
#   2. Sort ascending
#   3. Group into segments: each "round" uses all disks at
#      the size of the smallest remaining disk
#   4. Create one mdadm RAID-5 array per round
#   5. Combine all arrays with LVM
#   6. Create btrfs on the LVM volume
# ============================================================
create_smart_pool() {
    local pool_name="$1" mount_point="$2"; shift 2
    local disks=("$@")
    local n=${#disks[@]}

    step "Creating ForgeRAID-Smart pool: $pool_name ($n disks)"

    # Get disk sizes in bytes
    declare -A disk_sizes
    for disk in "${disks[@]}"; do
        local size_bytes
        size_bytes=$(blockdev --getsize64 "$disk" 2>/dev/null || echo "0")
        disk_sizes["$disk"]=$size_bytes
    done

    # Sort disks by size ascending
    local sorted_disks
    sorted_disks=$(for disk in "${disks[@]}"; do
        echo "${disk_sizes[$disk]} $disk"
    done | sort -n | awk '{print $2}')
    readarray -t sorted_disks <<< "$sorted_disks"

    # Calculate ForgeRAID-Smart layout
    # Each "tier" uses the incremental space between consecutive disk sizes
    mdadm_arrays=()
    local remaining_sizes=()
    for disk in "${sorted_disks[@]}"; do remaining_sizes+=("${disk_sizes[$disk]}"); done

    local tier=0
    local prev_size=0
    declare -A disk_partitions  # tracks next partition number per disk

    # Initialize partition counters
    for disk in "${disks[@]}"; do
        disk_partitions["$disk"]=1
    done

    # Prepare disks (GPT partition tables)
    for disk in "${disks[@]}"; do
        parted -s "$disk" mklabel gpt >> "$FORGENAS_LOG" 2>&1 || true
    done

    local lvm_pvs=()

    # Process tiers from smallest to largest disk
    for (( i=0; i < n; i++ )); do
        local current_size=${remaining_sizes[$i]}
        local tier_size=$(( current_size - prev_size ))
        local available_disks_count=$(( n - i ))  # all disks from i onward

        [[ $tier_size -le 0 ]] && { prev_size=$current_size; continue; }

        # Skip tiny remainders (< 1GB)
        [[ $tier_size -lt $((1024*1024*1024)) ]] && { prev_size=$current_size; continue; }

        local tier_size_mb=$(( tier_size / 1024 / 1024 ))

        info "Tier $tier: ${available_disks_count} disks × $(( tier_size_mb / 1024 ))GB"

        # Create partitions for this tier on all remaining disks
        local tier_parts=()
        for (( j=i; j < n; j++ )); do
            local disk="${sorted_disks[$j]}"
            local pnum="${disk_partitions[$disk]}"
            local start_mb=$(( ( disk_sizes[$disk] - remaining_sizes[$j] + prev_size * 0 ) / 1024 / 1024 + 1 ))
            # Actually use percentage-based for safety
            # Simple: just create next partition consuming tier_size_mb
            parted -s "$disk" mkpart primary "$(( start_mb ))MiB" "$(( start_mb + tier_size_mb ))MiB" \
                >> "$FORGENAS_LOG" 2>&1 || warn "Partition creation issue on $disk tier $tier"
            partprobe "$disk" 2>/dev/null || true
            sleep 1
            local part="${disk}${pnum}"
            [[ -b "${disk}p${pnum}" ]] && part="${disk}p${pnum}"  # NVMe naming
            tier_parts+=("$part")
            disk_partitions["$disk"]=$(( pnum + 1 ))
        done

        # Determine RAID level for this tier
        local tier_raid_level
        if [[ ${#tier_parts[@]} -ge 4 ]]; then
            tier_raid_level="raid6"
        elif [[ ${#tier_parts[@]} -ge 3 ]]; then
            tier_raid_level="raid5"
        elif [[ ${#tier_parts[@]} -ge 2 ]]; then
            tier_raid_level="raid1"
        else
            tier_raid_level="linear"
        fi

        local md_dev="/dev/md${tier}"
        info "  Creating ${tier_raid_level} array on ${md_dev}..."

        # Wipe existing metadata
        for part in "${tier_parts[@]}"; do
            mdadm --zero-superblock "$part" >> "$FORGENAS_LOG" 2>&1 || true
        done

        mdadm --create "$md_dev" \
            --level="$tier_raid_level" \
            --raid-devices="${#tier_parts[@]}" \
            --metadata=1.2 \
            --name="${pool_name}_t${tier}" \
            "${tier_parts[@]}" \
            >> "$FORGENAS_LOG" 2>&1 \
            || die "mdadm array creation failed for tier $tier"

        # Wait for initial sync to start (don't wait for full sync)
        sleep 2

        lvm_pvs+=("$md_dev")
        (( tier++ ))
        prev_size=$current_size
    done

    # Create LVM volume group across all mdadm arrays
    local vg_name="${pool_name}_vg"

    for pv in "${lvm_pvs[@]}"; do
        pvcreate "$pv" >> "$FORGENAS_LOG" 2>&1 || warn "pvcreate failed for $pv"
    done

    vgcreate "$vg_name" "${lvm_pvs[@]}" >> "$FORGENAS_LOG" 2>&1 \
        || die "vgcreate failed for $vg_name"

    # Use 95% of VG (leave some for LVM snapshots/metadata)
    lvcreate -l '95%VG' -n "${pool_name}" "$vg_name" >> "$FORGENAS_LOG" 2>&1 \
        || die "lvcreate failed"

    local lv_dev="/dev/${vg_name}/${pool_name}"

    # Format with btrfs
    mkfs.btrfs -L "$pool_name" -m raid1 -d single "$lv_dev" >> "$FORGENAS_LOG" 2>&1 \
        || die "mkfs.btrfs failed on $lv_dev"

    # Mount
    mkdir -p "$mount_point"
    local mount_opts="defaults,compress=zstd:3,noatime,space_cache=v2"
    mount -o "$mount_opts" "$lv_dev" "$mount_point"

    # fstab entry
    local uuid; uuid=$(blkid -s UUID -o value "$lv_dev")
    echo "UUID=${uuid}  ${mount_point}  btrfs  ${mount_opts}  0  0" >> /etc/fstab

    # Save mdadm config
    mdadm --detail --scan >> /etc/mdadm/mdadm.conf

    _finish_pool "$pool_name" "$mount_point" "ForgeRAID-Smart" "$lv_dev"
}

# ============================================================
# STANDARD MDADM POOL (single level, optionally mixed sizes)
# For mixed sizes in standard RAID, we use the smallest disk's
# size as the common denominator (same as Linux default)
# Users who want maximum space from mixed sizes → use Smart
# ============================================================
create_mdadm_pool() {
    local pool_name="$1" mount_point="$2" raid_level="$3"; shift 3
    local disks=("$@")
    local n=${#disks[@]}

    step "Creating ForgeRAID pool: $pool_name ($raid_level, $n disks)"

    # Validate minimum disk count
    case "$raid_level" in
        raid6)  [[ $n -ge 4 ]] || die "ForgeRAID-6 requires 4+ disks" ;;
        raid5)  [[ $n -ge 3 ]] || die "ForgeRAID-5 requires 3+ disks" ;;
        raid10) [[ $n -ge 4 ]] || die "ForgeRAID-10 requires 4+ disks (even number)" ;;
        raid1)  [[ $n -ge 2 ]] || die "ForgeRAID-1 requires 2+ disks" ;;
    esac

    # Partition all disks
    for disk in "${disks[@]}"; do
        parted -s "$disk" mklabel gpt >> "$FORGENAS_LOG" 2>&1 || true
        parted -s "$disk" mkpart primary 1MiB 100% >> "$FORGENAS_LOG" 2>&1 || true
        partprobe "$disk" 2>/dev/null || true
        sleep 1
    done

    # Get partition paths
    local parts=()
    for disk in "${disks[@]}"; do
        if [[ -b "${disk}p1" ]]; then
            parts+=("${disk}p1")   # NVMe: /dev/nvme0n1p1
        else
            parts+=("${disk}1")    # SATA/SAS: /dev/sda1
        fi
    done

    # Wipe superblocks
    for part in "${parts[@]}"; do
        mdadm --zero-superblock "$part" >> "$FORGENAS_LOG" 2>&1 || true
    done

    local md_dev="/dev/md0"
    # Find available md device
    local i=0
    while [[ -b "/dev/md${i}" ]]; do (( i++ )); done
    md_dev="/dev/md${i}"

    # Create array
    mdadm --create "$md_dev" \
        --level="$raid_level" \
        --raid-devices="$n" \
        --metadata=1.2 \
        --name="$pool_name" \
        "${parts[@]}" \
        >> "$FORGENAS_LOG" 2>&1 \
        || die "mdadm --create failed"

    sleep 2  # Let sync start

    # Format btrfs directly on mdadm device (no LVM needed for uniform disks)
    mkfs.btrfs -L "$pool_name" "$md_dev" >> "$FORGENAS_LOG" 2>&1 \
        || die "mkfs.btrfs failed"

    mkdir -p "$mount_point"
    local mount_opts="defaults,compress=zstd:3,noatime,space_cache=v2"
    mount -o "$mount_opts" "$md_dev" "$mount_point"

    local uuid; uuid=$(blkid -s UUID -o value "$md_dev")
    echo "UUID=${uuid}  ${mount_point}  btrfs  ${mount_opts}  0  0" >> /etc/fstab
    mdadm --detail --scan >> /etc/mdadm/mdadm.conf

    _finish_pool "$pool_name" "$mount_point" "$raid_level" "$md_dev"
}

# ============================================================
# JBOD (no redundancy, btrfs for checksums only)
# ============================================================
create_jbod_pool() {
    local pool_name="$1" mount_point="$2"; shift 2
    local disks=("$@")

    step "Creating JBOD pool: $pool_name"

    local parts=()
    for disk in "${disks[@]}"; do
        parted -s "$disk" mklabel gpt >> "$FORGENAS_LOG" 2>&1 || true
        parted -s "$disk" mkpart primary 1MiB 100% >> "$FORGENAS_LOG" 2>&1 || true
        partprobe "$disk" 2>/dev/null || true
        sleep 1
        if [[ -b "${disk}p1" ]]; then parts+=("${disk}p1")
        else parts+=("${disk}1"); fi
    done

    mkdir -p "$mount_point"

    if [[ ${#parts[@]} -eq 1 ]]; then
        mkfs.btrfs -L "$pool_name" "${parts[0]}" >> "$FORGENAS_LOG" 2>&1
        mount -o "defaults,compress=zstd:3,noatime" "${parts[0]}" "$mount_point"
        local uuid; uuid=$(blkid -s UUID -o value "${parts[0]}")
        echo "UUID=${uuid}  ${mount_point}  btrfs  defaults,compress=zstd:3,noatime  0  0" >> /etc/fstab
    else
        # Multi-disk JBOD via btrfs RAID-0 (note: no redundancy warning printed)
        warn "JBOD multi-disk: using btrfs RAID-0. No redundancy — data loss on ANY disk failure."
        mkfs.btrfs -L "$pool_name" -d raid0 -m raid1 "${parts[@]}" >> "$FORGENAS_LOG" 2>&1
        mount -o "defaults,compress=zstd:3,noatime" "${parts[0]}" "$mount_point"
        local uuid; uuid=$(blkid -s UUID -o value "${parts[0]}")
        echo "UUID=${uuid}  ${mount_point}  btrfs  defaults,compress=zstd:3,noatime  0  0" >> /etc/fstab
    fi

    _finish_pool "$pool_name" "$mount_point" "JBOD" "${parts[0]}"
}

# ============================================================
# POST-POOL SETUP (common to all pool types)
# ============================================================
_finish_pool() {
    local pool_name="$1" mount_point="$2" raid_type="$3" dev="$4"

    # Standard subdirectory structure
    mkdir -p "${mount_point}"/{data,media,photos,documents,backups,docker,public}
    chmod 777 "${mount_point}/public"
    chmod 755 "${mount_point}"/{data,media,photos,documents,backups,docker}

    # Configure snapper for btrfs snapshots
    configure_snapper "$pool_name" "$mount_point"

    # Enable btrfs maintenance
    enable_btrfs_maintenance "$dev"

    # Save to config
    forgenas_set "PRIMARY_POOL"       "$pool_name"
    forgenas_set "PRIMARY_POOL_MOUNT" "$mount_point"
    forgenas_set "PRIMARY_POOL_TYPE"  "$raid_type"
    forgenas_set "PRIMARY_POOL_DEV"   "$dev"

    info "Pool '${pool_name}' (${raid_type}) mounted at ${mount_point}"

    # Show sync status
    if [[ -f /proc/mdstat ]]; then
        local sync_line
        sync_line=$(grep -A2 'md[0-9]' /proc/mdstat 2>/dev/null | grep 'sync' || echo "")
        if [[ -n "$sync_line" ]]; then
            info "Array syncing in background (normal, data is accessible now)"
            info "Monitor with: watch -n2 cat /proc/mdstat"
        fi
    fi
}

# ============================================================
# SNAPPER (btrfs snapshot management)
# Equivalent to Synology Snapshot Replication
# ============================================================
configure_snapper() {
    local pool_name="$1" mount_point="$2"

    step "Configuring btrfs snapshots (snapper) for $pool_name"

    # Create snapper config
    snapper -c "$pool_name" create-config "$mount_point" >> "$FORGENAS_LOG" 2>&1 \
        || { warn "snapper config creation failed"; return; }

    # Set retention policy
    snapper -c "$pool_name" set-config \
        TIMELINE_CREATE=yes \
        TIMELINE_CLEANUP=yes \
        TIMELINE_LIMIT_HOURLY=24 \
        TIMELINE_LIMIT_DAILY=30 \
        TIMELINE_LIMIT_WEEKLY=8 \
        TIMELINE_LIMIT_MONTHLY=12 \
        TIMELINE_LIMIT_YEARLY=5 \
        NUMBER_CLEANUP=yes \
        NUMBER_LIMIT=50 \
        >> "$FORGENAS_LOG" 2>&1

    enable_service snapper-timeline.timer
    enable_service snapper-cleanup.timer

    info "Snapper snapshots configured: 24h/30d/8w/12m/5y retention"
}

# ============================================================
# BTRFS MAINTENANCE TIMERS
# ============================================================
enable_btrfs_maintenance() {
    local dev="$1"

    # Enable btrfs scrub weekly (data integrity check)
    systemctl enable btrfs-scrub@-.timer 2>/dev/null \
        || {
            # Create scrub timer if not present
            cat > /etc/systemd/system/forgeos-btrfs-scrub.service << SVC
[Unit]
Description=ForgeOS btrfs scrub
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for mp in \$(findmnt -t btrfs -o TARGET -n); do btrfs scrub start "\$mp"; done'
SVC
            cat > /etc/systemd/system/forgeos-btrfs-scrub.timer << TIMER
[Unit]
Description=Weekly btrfs scrub
[Timer]
OnCalendar=Sun 03:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
TIMER
            systemctl daemon-reload
            systemctl enable forgeos-btrfs-scrub.timer
        }

    # btrfs balance (rebalance data distribution) monthly
    cat > /etc/systemd/system/forgeos-btrfs-balance.service << SVC
[Unit]
Description=ForgeOS btrfs balance
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for mp in \$(findmnt -t btrfs -o TARGET -n); do btrfs balance start -dusage=80 -musage=80 "\$mp"; done'
Nice=15
IOSchedulingClass=idle
SVC
    cat > /etc/systemd/system/forgeos-btrfs-balance.timer << TIMER
[Unit]
Description=Monthly btrfs balance
[Timer]
OnCalendar=monthly
RandomizedDelaySec=7200
Persistent=true
[Install]
WantedBy=timers.target
TIMER
    systemctl daemon-reload
    systemctl enable forgeos-btrfs-balance.timer

    info "btrfs maintenance timers enabled (scrub weekly, balance monthly)"
}

# ============================================================
# FORGEOS-STORAGE MANAGEMENT CLI
# Called by Web UI and admins
# ============================================================
create_storage_cli() {
    step "Installing forgeos-storage management tool"

    cat > /usr/local/bin/forgeos-storage << 'CLI'
#!/usr/bin/env bash
# ForgeOS Storage Management CLI
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

pool_status() {
    echo "=== ForgeRAID Arrays ==="
    cat /proc/mdstat 2>/dev/null || echo "(no mdadm arrays)"
    echo ""
    echo "=== LVM Volume Groups ==="
    vgs 2>/dev/null || echo "(no LVM VGs)"
    echo ""
    echo "=== btrfs Filesystems ==="
    btrfs filesystem show 2>/dev/null
    echo ""
    echo "=== Mounted Pools ==="
    findmnt -t btrfs -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null
}

pool_health() {
    echo "=== SMART Status ==="
    for disk in $(lsblk -d -o NAME,TYPE | awk '/disk/{print $1}'); do
        echo "--- /dev/$disk ---"
        smartctl -H "/dev/$disk" 2>/dev/null | grep -E 'result:|SMART Health'
    done
    echo ""
    echo "=== mdadm Array Health ==="
    for md in /dev/md*; do
        [[ -b "$md" ]] || continue
        mdadm --detail "$md" 2>/dev/null | grep -E 'State:|Active|Failed|Spare'
    done
}

snapshot_create() {
    local config="${1:-}" desc="${2:-manual}"
    if [[ -z "$config" ]]; then
        snapper list-configs | awk 'NR>2{print $1}' | while read -r c; do
            snapper -c "$c" create --description "$desc" --cleanup-algorithm timeline
            echo "Snapshot created on config: $c"
        done
    else
        snapper -c "$config" create --description "$desc" --cleanup-algorithm timeline
    fi
}

snapshot_list() {
    local config="${1:-}"
    if [[ -z "$config" ]]; then
        snapper list-configs | awk 'NR>2{print $1}' | while read -r c; do
            echo "=== $c ==="
            snapper -c "$c" list
        done
    else
        snapper -c "$config" list
    fi
}

snapshot_rollback() {
    local config="$1" snap_num="$2"
    [[ -z "$config" || -z "$snap_num" ]] && { echo "Usage: rollback <config> <snap_num>"; exit 1; }
    echo "Rolling back $config to snapshot $snap_num..."
    snapper -c "$config" undochange "${snap_num}..0"
}

add_disk() {
    local pool="$1" disk="$2"
    [[ -z "$pool" || -z "$disk" ]] && { echo "Usage: add-disk <pool> <disk>"; exit 1; }
    local md_dev
    md_dev=$(mdadm --detail "/dev/md0" 2>/dev/null | grep "Array Size" | head -1 || true)
    # This is complex — delegate to Web UI for safety
    echo "Disk addition is best done via Web UI > Storage > $pool > Add Disk"
    echo "This ensures correct partition sizing and array expansion."
}

case "$CMD" in
    status)       pool_status ;;
    health)       pool_health ;;
    snapshot)     snapshot_create "$@" ;;
    snapshots)    snapshot_list "$@" ;;
    rollback)     snapshot_rollback "$@" ;;
    add-disk)     add_disk "$@" ;;
    scrub)
        local mp="${1:-/srv/nas}"
        btrfs scrub start "$mp"
        echo "Scrub started on $mp (monitor: btrfs scrub status $mp)"
        ;;
    df)
        for mp in $(findmnt -t btrfs -o TARGET -n); do
            echo "--- $mp ---"
            btrfs filesystem df "$mp"
            btrfs filesystem usage "$mp" | grep -E 'Device size|Used|Free'
        done
        ;;
    help|*)
        echo "ForgeOS Storage CLI"
        echo "  status             Show all pools and arrays"
        echo "  health             SMART + array health check"
        echo "  snapshot [pool]    Create snapshot now"
        echo "  snapshots [pool]   List snapshots"
        echo "  rollback <pool> <n> Roll back to snapshot N"
        echo "  scrub [mountpoint] Start btrfs scrub"
        echo "  df                 Show filesystem usage"
        ;;
esac
CLI
    chmod +x /usr/local/bin/forgeos-storage
    info "forgeos-storage CLI installed"
}

# ============================================================
# MDADM MONITORING — alerts on array degradation
# ============================================================
configure_mdadm_monitoring() {
    step "Configuring mdadm monitoring"

    cat > /etc/mdadm/mdadm.conf << MDCONF
# ForgeOS mdadm configuration
DEVICE partitions
MAILADDR root
MAILFROM forgeos@localhost
PROGRAM /opt/forgeos/scripts/mdadm-alert.sh
MDCONF

    cat > /opt/forgeos/scripts/mdadm-alert.sh << 'ALERT'
#!/usr/bin/env bash
# mdadm event → ForgeOS notification
EVENT="$1"
DEVICE="$2"
curl -sf -X POST "http://localhost:5080/api/notify" \
    -H "Content-Type: application/json" \
    -d '{"level":"critical","title":"ForgeRAID Alert: '"$DEVICE"'","message":"mdadm event: '"$EVENT"'"}' \
    2>/dev/null || true
logger -t forgeos-storage "RAID ALERT: $EVENT on $DEVICE"
ALERT
    chmod +x /opt/forgeos/scripts/mdadm-alert.sh

    enable_service mdadm
    info "mdadm monitoring enabled"
}

# ============================================================
# MAIN
# ============================================================
mkdir -p /opt/forgeos/scripts /srv/nas
install_storage_packages
forgearaid_wizard
create_storage_cli
configure_mdadm_monitoring

info "Storage module complete"
info "  CLI:     forgeos-storage status"
info "  Scrub:   forgeos-storage scrub /srv/nas"
info "  Snaps:   forgeos-storage snapshots"
info "  Web UI:  Storage > ForgeRAID"
