#!/usr/bin/env bash
# ============================================================
# ForgeOS lib/detect.sh — Hardware detection
# ============================================================
source "$(dirname "$0")/../lib/common.sh" 2>/dev/null || true

detect_all() {
    detect_cpu
    detect_gpu
    detect_network
    detect_memory
    detect_disks
    detect_virtualization
}

detect_cpu() {
    CPU_MODEL=$(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
    CPU_CORES=$(nproc)
    CPU_ARCH=$(uname -m)
    CPU_VENDOR=$(grep -m1 'vendor_id' /proc/cpuinfo | awk '{print $3}' || echo "unknown")
    CPU_IS_INTEL=false; CPU_IS_AMD=false
    [[ "$CPU_VENDOR" == "GenuineIntel" ]] && CPU_IS_INTEL=true
    [[ "$CPU_VENDOR" == "AuthenticAMD" ]] && CPU_IS_AMD=true
    forgenas_set "CPU_MODEL" "$CPU_MODEL"
    forgenas_set "CPU_CORES" "$CPU_CORES"
}

detect_gpu() {
    GPU_NVIDIA=false; GPU_AMD=false; GPU_INTEL=false

    if lspci 2>/dev/null | grep -qi "NVIDIA"; then
        GPU_NVIDIA=true
        GPU_MODEL=$(lspci 2>/dev/null | grep -i NVIDIA | grep -i "VGA\|3D\|Display" | head -1 | sed 's/.*: //')
    fi
    if lspci 2>/dev/null | grep -qi "AMD.*VGA\|Advanced Micro.*VGA\|Radeon"; then
        GPU_AMD=true
        GPU_MODEL="${GPU_MODEL:-$(lspci 2>/dev/null | grep -i 'Radeon\|AMD.*VGA' | head -1 | sed 's/.*: //')}"
    fi
    if lspci 2>/dev/null | grep -qi "Intel.*VGA\|Intel.*Graphics"; then
        GPU_INTEL=true
        GPU_INTEL_MODEL=$(lspci 2>/dev/null | grep -i 'Intel.*VGA\|Intel.*Graphics' | head -1 | sed 's/.*: //')
        # Arc detection
        if echo "$GPU_INTEL_MODEL" | grep -qi "Arc"; then
            GPU_INTEL_ARC=true
        else
            GPU_INTEL_ARC=false
        fi
    fi

    forgenas_set "GPU_NVIDIA" "$GPU_NVIDIA"
    forgenas_set "GPU_AMD"    "$GPU_AMD"
    forgenas_set "GPU_INTEL"  "$GPU_INTEL"
}

detect_network() {
    # Find primary NIC (non-loopback, non-virtual, with IP)
    NIC_PRIMARY=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -1 || echo "eth0")
    NIC_SPEED=$(cat /sys/class/net/${NIC_PRIMARY}/speed 2>/dev/null || echo "0")
    NIC_IP=$(ip -4 addr show "$NIC_PRIMARY" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1 || echo "")

    # Detect 10GbE / 25GbE / 40GbE
    NIC_HIGHSPEED=false
    [[ "${NIC_SPEED:-0}" -ge 10000 ]] && NIC_HIGHSPEED=true

    # Count all physical NICs (for bonding)
    NIC_COUNT=$(ls /sys/class/net/ | grep -v "^lo$\|^veth\|^docker\|^br-\|^virbr\|^incus\|^lxd" | wc -l)

    forgenas_set "NIC_PRIMARY"   "$NIC_PRIMARY"
    forgenas_set "NIC_IP"        "$NIC_IP"
    forgenas_set "NIC_SPEED"     "${NIC_SPEED}Mb"
    forgenas_set "NIC_COUNT"     "$NIC_COUNT"
    forgenas_set "NIC_HIGHSPEED" "$NIC_HIGHSPEED"
}

detect_memory() {
    MEM_TOTAL_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    MEM_TOTAL_GB=$(( MEM_TOTAL_KB / 1024 / 1024 ))
    MEM_ECC=false

    # ECC detection
    if command -v dmidecode &>/dev/null; then
        if dmidecode --type 17 2>/dev/null | grep -qi "ECC"; then
            MEM_ECC=true
        fi
    fi

    # Warn if RAM is low
    if [[ $MEM_TOTAL_GB -lt 4 ]]; then
        warn "Low RAM: ${MEM_TOTAL_GB}GB detected. ForgeOS recommends 8GB+."
    fi

    forgenas_set "MEM_TOTAL_GB" "$MEM_TOTAL_GB"
    forgenas_set "MEM_ECC"      "$MEM_ECC"
}

detect_disks() {
    local sys_disk; sys_disk=$(get_system_disk 2>/dev/null || echo "/dev/sda")

    DATA_DISK_COUNT=0
    DATA_DISKS=()
    NVME_DISKS=()
    HDD_DISKS=()

    while IFS= read -r line; do
        local dev size tran
        dev=$(echo "$line" | awk '{print $1}')
        size=$(echo "$line" | awk '{print $2}')
        tran=$(echo "$line" | awk '{print $6}')

        [[ "/dev/$dev" == "$sys_disk" ]] && continue
        [[ "$dev" =~ ^loop ]]            && continue
        [[ "$dev" =~ ^sr ]]              && continue

        DATA_DISKS+=("/dev/$dev")
        if [[ "$tran" == "nvme" || "$dev" =~ ^nvme ]]; then
            NVME_DISKS+=("/dev/$dev")
        else
            HDD_DISKS+=("/dev/$dev")
        fi
        (( DATA_DISK_COUNT++ ))

    done < <(lsblk -dno NAME,SIZE,MODEL,TYPE,FSTYPE,TRAN 2>/dev/null | grep " disk")

    forgenas_set "DATA_DISK_COUNT" "$DATA_DISK_COUNT"
    forgenas_set "NVME_DISK_COUNT" "${#NVME_DISKS[@]}"
    forgenas_set "HDD_DISK_COUNT"  "${#HDD_DISKS[@]}"
}

detect_virtualization() {
    VIRT_TYPE="none"
    if command -v systemd-detect-virt &>/dev/null; then
        VIRT_TYPE=$(systemd-detect-virt 2>/dev/null || echo "none")
    elif [[ -f /proc/1/environ ]] && grep -q "container" /proc/1/environ 2>/dev/null; then
        VIRT_TYPE="container"
    fi
    IS_VM=false
    [[ "$VIRT_TYPE" != "none" ]] && IS_VM=true
    forgenas_set "VIRT_TYPE" "$VIRT_TYPE"
    forgenas_set "IS_VM"     "$IS_VM"
}

detect_print_summary() {
    echo -e "  ${BOLD}Hardware Summary${NC}"
    echo -e "    CPU:    ${CPU_MODEL:-unknown} (${CPU_CORES:-?} cores)"
    echo -e "    RAM:    ${MEM_TOTAL_GB:-?}GB $( $MEM_ECC && echo '[ECC]' || true)"
    echo -e "    NIC:    ${NIC_PRIMARY:-?} @ ${NIC_SPEED:-?}"
    echo -e "    Disks:  ${DATA_DISK_COUNT:-0} data disks (${#HDD_DISKS[@]} HDD, ${#NVME_DISKS[@]} NVMe)"
    $GPU_NVIDIA && echo -e "    GPU:    NVIDIA: ${GPU_MODEL:-?}"
    $GPU_AMD    && echo -e "    GPU:    AMD: ${GPU_MODEL:-?}"
    $GPU_INTEL  && echo -e "    GPU:    Intel: ${GPU_INTEL_MODEL:-?}"
    $IS_VM      && echo -e "    Virt:   ${VIRT_TYPE} (performance may be limited)"
    echo ""
}
