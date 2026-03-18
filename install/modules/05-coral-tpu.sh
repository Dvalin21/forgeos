#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 05 - Google Coral TPU PCIe
#
# RESEARCH SUMMARY (critical — read before modifying):
# ──────────────────────────────────────────────────────────
# The Coral Edge TPU PCIe driver has TWO components:
#
#   1. gasket.ko  — generic PCIe framework (Google wrote)
#   2. apex.ko    — Coral-specific driver, depends on gasket
#
# SINGLE vs DUAL TPU — SAME DRIVER, different device count:
#   Single M.2/mPCIe: 1 PCIe function → /dev/apex_0
#   Dual M.2:         Internal PCIe switch exposes TWO
#                     independent PCIe functions, both with
#                     PCI ID 1ac1:089a → /dev/apex_0 + /dev/apex_1
#   The host M.2 slot MUST support x2 PCIe lanes (bifurcation)
#   for both TPUs to be enumerated. Single-lane x1 slots will
#   only enumerate one TPU regardless of the dual card.
#
# MSI-X REQUIREMENT:
#   The host PCIe slot MUST support MSI-X (PCI 3.0 spec).
#   If `lspci -vv | grep MSI-X` returns nothing for the card,
#   the /dev/apex_* device will never appear. Hardware limitation.
#
# DRIVER SOURCE — why we DON'T use Google's official package:
#   Google's official apt repo package (gasket-dkms from
#   packages.cloud.google.com) fails to build on Linux kernel
#   6.x+ due to API changes in fs.h and other headers.
#   Google has not updated the package since ~2022.
#   The community-maintained fork at:
#     github.com/KyleGospo/gasket-dkms
#   contains the kernel 6.x compatibility patches and builds
#   cleanly on Ubuntu 22.04/24.04 with kernels 5.15–6.8+.
#   We use this fork as the primary install path.
#   Fallback: google/gasket-driver.git (official, may still fail
#   on 6.x without patches — we apply them automatically).
#
# RUNTIME LIBRARY:
#   libedgetpu1-std  — standard clock (lower temp, recommended)
#   libedgetpu1-max  — max clock (~15% faster, runs hotter)
#   Both from Google's apt repo. The repo still works for the
#   runtime library — only the DKMS package is broken there.
#
# POWER THROTTLING:
#   The driver throttles clock speed when temp exceeds trip points.
#   Configurable via sysfs: /sys/class/apex/apex_0/
#   and via modprobe params: /etc/modprobe.d/apex.conf
#
# FRIGATE DOCKER COMPOSE:
#   Pass /dev/apex_0 (single) or /dev/apex_0 + /dev/apex_1
#   (dual) into the Frigate container. Auto-detected below.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

CORAL_DIR="/opt/forgeos/apps/coral"
FRIGATE_DIR="/opt/forgeos/apps/frigate"
FRIGATE_DATA="/srv/forgeos/frigate"

mkdir -p "$CORAL_DIR" "$FRIGATE_DIR" "$FRIGATE_DATA"/{config,media,db}

# ============================================================
# HARDWARE DETECTION
# Detect Coral PCIe devices before installing anything.
# PCI ID: 1ac1:089a (Global Unichip Corp. Coral Edge TPU)
# ============================================================
detect_coral() {
    step "Detecting Google Coral TPU PCIe hardware"

    # Check MSI-X support first (required by all Coral PCIe devices)
    local coral_devices
    coral_devices=$(lspci -nn 2>/dev/null | grep -c "089a" || echo "0")

    if [[ "$coral_devices" -eq 0 ]]; then
        info "No Coral TPU PCIe hardware detected (lspci -nn | grep 089a = 0)"
        info "  If hardware is installed: verify MSI-X support with:"
        info "    lspci -vv | grep -A3 089a | grep MSI-X"
        info "  Skipping Coral driver installation"
        forgenas_set "CORAL_DETECTED" "no"
        forgenas_set "CORAL_COUNT" "0"
        return 1
    fi

    # Check MSI-X capability
    local msix_ok
    msix_ok=$(lspci -vv 2>/dev/null | grep -A3 "089a" | grep -c "MSI-X" || echo "0")
    if [[ "$msix_ok" -eq 0 ]]; then
        warn "Coral PCIe device found (${coral_devices}x) but MSI-X not detected"
        warn "  MSI-X is REQUIRED for the apex driver to create /dev/apex_* devices"
        warn "  Your motherboard PCIe slot may not support MSI-X"
        warn "  Driver will still be installed — may work after BIOS update or ASPM=off"
    fi

    forgenas_set "CORAL_DETECTED" "yes"
    forgenas_set "CORAL_COUNT"    "$coral_devices"
    forgenas_set "CORAL_MSIX_OK"  "$( [[ $msix_ok -gt 0 ]] && echo yes || echo no )"

    info "Coral TPU detected: ${coral_devices} device(s) via PCI ID 1ac1:089a"
    [[ "$coral_devices" -ge 2 ]] && \
        info "  Dual TPU card or multiple cards detected → will expose apex_0 + apex_1"
    [[ "$coral_devices" -eq 1 ]] && \
        info "  Single TPU → will expose apex_0"

    return 0
}

# ============================================================
# INSTALL GASKET DKMS (community fork — kernel 6.x compatible)
# ============================================================
install_gasket_dkms() {
    step "Installing gasket-dkms (KyleGospo fork — kernel 6.x compatible)"

    # Prerequisites
    apt_install \
        dkms \
        linux-headers-$(uname -r) \
        git \
        devscripts \
        dh-dkms \
        debhelper \
        build-essential \
        libfuse2

    # Remove any previous gasket installation (clean slate)
    dkms remove gasket/1.0 --all >> "$FORGENAS_LOG" 2>&1 || true
    apt-get remove -y gasket-dkms >> "$FORGENAS_LOG" 2>&1 || true

    # Clone KyleGospo's maintained fork
    local build_dir="/tmp/gasket-build-$$"
    mkdir -p "$build_dir"
    cd "$build_dir"

    _progress "Cloning KyleGospo/gasket-dkms"
    git clone --depth=1 https://github.com/KyleGospo/gasket-dkms.git \
        >> "$FORGENAS_LOG" 2>&1 || {
        warn "KyleGospo fork failed — falling back to google/gasket-driver"
        _install_gasket_google_source "$build_dir"
        cd /
        rm -rf "$build_dir"
        return
    }
    _done

    cd gasket-dkms

    _progress "Building gasket-dkms .deb package"
    debuild -us -uc -tc -b >> "$FORGENAS_LOG" 2>&1 || {
        warn "debuild failed — trying manual DKMS install"
        _install_gasket_manual
        cd /
        rm -rf "$build_dir"
        return
    }
    _done

    cd ..
    local deb; deb=$(ls gasket-dkms_*.deb 2>/dev/null | head -1)
    if [[ -n "$deb" ]]; then
        dpkg -i "$deb" >> "$FORGENAS_LOG" 2>&1 \
            || { apt-get install -f -y >> "$FORGENAS_LOG" 2>&1; dpkg -i "$deb" >> "$FORGENAS_LOG" 2>&1; }
        cp "$deb" "$CORAL_DIR/"
        info "gasket-dkms built and installed from KyleGospo fork"
    else
        warn "No .deb file found after build — attempting manual DKMS install"
        _install_gasket_manual
    fi

    cd /
    rm -rf "$build_dir"
}

# Fallback A: google/gasket-driver official source
_install_gasket_google_source() {
    local build_dir="$1"
    cd "$build_dir"

    git clone --depth=1 https://github.com/google/gasket-driver.git \
        >> "$FORGENAS_LOG" 2>&1 || { warn "gasket-driver clone failed"; return 1; }

    cd gasket-driver
    debuild -us -uc -tc -b >> "$FORGENAS_LOG" 2>&1 || true
    cd ..

    local deb; deb=$(ls gasket-dkms_*.deb 2>/dev/null | head -1)
    [[ -n "$deb" ]] && dpkg -i "$deb" >> "$FORGENAS_LOG" 2>&1 || true
}

# Fallback B: manual DKMS without debuild
_install_gasket_manual() {
    local src_dir="/usr/src/gasket-1.0"
    rm -rf "$src_dir"
    git clone --depth=1 https://github.com/KyleGospo/gasket-dkms.git \
        "$src_dir/source" >> "$FORGENAS_LOG" 2>&1 \
        || git clone --depth=1 https://github.com/google/gasket-driver.git \
           "$src_dir/source" >> "$FORGENAS_LOG" 2>&1 \
        || { warn "Cannot clone gasket source"; return 1; }

    # Copy source files to DKMS location
    cp -r "${src_dir}/source/src" "${src_dir}/" 2>/dev/null || true
    cp    "${src_dir}/source/Makefile" "${src_dir}/" 2>/dev/null || true

    # Write dkms.conf if not present
    [[ ! -f "${src_dir}/dkms.conf" ]] && cat > "${src_dir}/dkms.conf" << 'DKMSCONF'
PACKAGE_NAME="gasket"
PACKAGE_VERSION="1.0"
CLEAN="make -C src/ clean"
MAKE="make -C src/ all KERNELVER=${kernelver}"
BUILT_MODULE_LOCATION[0]="src/"
BUILT_MODULE_NAME[0]="gasket"
BUILT_MODULE_LOCATION[1]="src/"
BUILT_MODULE_NAME[1]="apex"
DEST_MODULE_LOCATION[0]="/updates/dkms"
DEST_MODULE_LOCATION[1]="/updates/dkms"
AUTOINSTALL="yes"
DKMSCONF

    dkms add gasket/1.0 >> "$FORGENAS_LOG" 2>&1 || true
    dkms build gasket/1.0 >> "$FORGENAS_LOG" 2>&1 \
        && dkms install gasket/1.0 >> "$FORGENAS_LOG" 2>&1 \
        && info "gasket DKMS installed (manual method)" \
        || warn "gasket DKMS build failed — install after kernel headers are correct"
}

# ============================================================
# EDGE TPU RUNTIME LIBRARY
# The apt repo from Google still works for the runtime library.
# Only the DKMS kernel module package is broken there.
# ============================================================
install_edgetpu_runtime() {
    step "Installing Edge TPU runtime library (libedgetpu)"

    # Google's apt repo
    echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
        > /etc/apt/sources.list.d/coral-edgetpu.list

    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/coral-edgetpu.gpg 2>/dev/null \
        || curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
           | apt-key add - >> "$FORGENAS_LOG" 2>&1 || warn "Coral GPG key fetch failed"

    _apt_ready=false
    # Install ONLY the runtime — NOT gasket-dkms from here (it's broken on 6.x)
    apt_install libedgetpu1-std \
        || apt_install_optional libedgetpu1-std

    # Hold gasket-dkms to prevent Google's broken version from being installed
    apt-mark hold gasket-dkms 2>/dev/null || true

    # Python bindings (for Frigate and PyCoral)
    apt_install_optional python3-pycoral python3-tflite-runtime \
        || pip3 install pycoral tflite-runtime --quiet 2>/dev/null || true

    info "Edge TPU runtime: libedgetpu1-std installed"
    info "  For max performance (hotter): apt install libedgetpu1-max"
}

# ============================================================
# UDEV RULES + KERNEL MODULE LOADING
# ============================================================
configure_apex_system() {
    step "Configuring apex udev rules and module loading"

    # udev rule — creates apex group, device accessible to it
    cat > /etc/udev/rules.d/65-apex.rules << 'UDEV'
# Google Coral Edge TPU PCIe access rules
# Matches both single and dual TPU cards (creates apex_0, apex_1, etc.)
SUBSYSTEM=="apex", MODE="0660", GROUP="apex", TAG+="systemd"

# Also match by PCI ID for early detection
SUBSYSTEM=="pci", ATTR{vendor}=="0x1ac1", ATTR{device}=="0x089a", TAG+="systemd"
UDEV

    # apex group
    getent group apex &>/dev/null || groupadd apex
    source "$FORGENAS_CONFIG"
    local user="${ADMIN_USER:-forgeos}"
    usermod -aG apex "$user" 2>/dev/null || true

    # Load modules at boot
    cat > /etc/modules-load.d/coral-tpu.conf << 'MODS'
# Google Coral TPU PCIe modules
gasket
apex
MODS

    # Module parameters — ASPM off helps on some motherboards where
    # the PCIe link state management interferes with Apex initialization
    cat > /etc/modprobe.d/apex.conf << 'APEX'
# Google Coral Apex PCIe module parameters
# Uncomment pcie_aspm=off if /dev/apex_* devices don't appear after reboot:
# options apex pcie_aspm=off
#
# Temperature trip points (°C):
# trip_point0_temp: start throttling (default 65)
# trip_point1_temp: heavy throttle  (default 75)
# trip_point2_temp: max throttle    (default 80)
# hw_temp_warn2:    shutdown temp   (default 85)
options apex trip_point0_temp=65 trip_point1_temp=75 trip_point2_temp=80
APEX

    # Try to load now (will work after reboot if modules not yet built)
    modprobe gasket >> "$FORGENAS_LOG" 2>&1 || true
    modprobe apex   >> "$FORGENAS_LOG" 2>&1 || true
    udevadm control --reload-rules && udevadm trigger 2>/dev/null || true

    info "apex udev rules, group, and module config written"
    info "  Reboot required to finalize driver loading"
}

# ============================================================
# GRUB UPDATE for ASPM (may be needed for some motherboards)
# ============================================================
configure_grub_for_coral() {
    # Only add pcie_aspm=off if MSI-X was detected but apex still not working
    # We DON'T add this by default — it affects all PCIe devices
    # Instead, we document it and let user enable if needed
    local grub_file="/etc/default/grub"
    if grep -q "pcie_aspm=off" "$grub_file" 2>/dev/null; then
        return 0  # already set
    fi

    # Write a note in the ForgeOS config
    forgenas_set "CORAL_ASPM_NOTE" \
        "If /dev/apex_0 missing after reboot: add pcie_aspm=off to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub then run update-grub"
    info "GRUB ASPM note: if apex devices missing, see /etc/forgeos/forgeos.conf CORAL_ASPM_NOTE"
}

# ============================================================
# VERIFY INSTALLATION
# ============================================================
verify_coral() {
    step "Verifying Coral TPU installation"

    local found_devices=0
    for i in 0 1 2 3; do
        if [[ -e "/dev/apex_${i}" ]]; then
            (( found_devices++ ))
            local temp
            temp=$(cat "/sys/class/apex/apex_${i}/temp" 2>/dev/null | awk '{printf "%.1f", $1/1000}' || echo "N/A")
            info "  /dev/apex_${i} — Edge TPU ${i} detected, temp: ${temp}°C"
        fi
    done

    if [[ $found_devices -eq 0 ]]; then
        warn "No /dev/apex_* devices found yet"
        warn "  This is NORMAL before reboot — the kernel module was just built"
        warn "  After reboot run: ls /dev/apex_*"
        warn "  If still missing: check lspci -vv | grep MSI-X near the 089a device"
        forgenas_set "CORAL_DRIVER_LOADED" "pending_reboot"
    else
        info "Coral TPU: ${found_devices} device(s) active"
        forgenas_set "CORAL_DRIVER_LOADED" "yes"
        forgenas_set "CORAL_ACTIVE_DEVICES" "$found_devices"
    fi
}

# ============================================================
# FRIGATE NVR DOCKER COMPOSE
# Auto-configures device passthrough for detected TPU count
# ============================================================
generate_frigate_compose() {
    step "Generating Frigate NVR Docker Compose"

    source "$FORGENAS_CONFIG"
    local coral_count="${CORAL_COUNT:-1}"
    local domain="${DOMAIN:-nas.local}"

    # Build device list for compose
    local devices="      - /dev/dri:/dev/dri  # GPU hardware decoding"
    for i in $(seq 0 $(( coral_count - 1 ))); do
        devices="${devices}
      - /dev/apex_${i}:/dev/apex_${i}  # Coral TPU ${i}"
    done

    # Calculate shm_size (64MB per camera, estimate 8 cameras default)
    local shm_size="256mb"

    cat > "${FRIGATE_DIR}/docker-compose.yml" << FRIGATE
version: "3.8"
# ForgeOS Frigate NVR — with Google Coral TPU
# Coral devices: ${coral_count} detected
# Edit config: ${FRIGATE_DATA}/config/config.yml
# Manage: https://nvr.${domain}

services:
  frigate:
    container_name: forgeos-frigate
    privileged: true
    restart: unless-stopped
    image: ghcr.io/blakeblackshear/frigate:stable
    shm_size: "${shm_size}"

    devices:
${devices}

    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ${FRIGATE_DATA}/config/config.yml:/config/config.yml
      - ${FRIGATE_DATA}/media:/media/frigate
      - ${FRIGATE_DATA}/db:/db
      - type: tmpfs
        target: /tmp/cache
        tmpfs:
          size: 1073741824  # 1GB RAM cache for clips

    ports:
      - "127.0.0.1:5001:5000"   # Frigate Web UI
      - "1935:1935"             # RTMP feeds
      - "8554:8554"             # RTSP feeds
      - "8555:8555/tcp"         # WebRTC TCP
      - "8555:8555/udp"         # WebRTC UDP

    environment:
      - FRIGATE_RTSP_PASSWORD=${FRIGATE_RTSP_PASS:-changeme}

    networks:
      - forgeos-internal

networks:
  forgeos-internal:
    external: true
FRIGATE

    # Generate base Frigate config
    cat > "${FRIGATE_DATA}/config/config.yml" << FRICONFIG
# ForgeOS Frigate NVR Configuration
# Documentation: https://docs.frigate.video
# Edit this file then restart: docker compose restart frigate

mqtt:
  enabled: false  # Enable if you have MQTT broker

detectors:
$(for i in $(seq 0 $(( coral_count - 1 ))); do
    echo "  coral${i}:"
    echo "    type: edgetpu"
    echo "    device: pci  # Uses /dev/apex_${i}"
done)

# Example camera (replace with your actual cameras):
# cameras:
#   driveway:
#     ffmpeg:
#       inputs:
#         - path: rtsp://admin:password@192.168.1.100:554/stream
#           roles:
#             - detect
#             - record
#     detect:
#       width: 1280
#       height: 720
#       fps: 5
#     record:
#       enabled: true
#       retain:
#         days: 7
#     snapshots:
#       enabled: true

database:
  path: /db/frigate.db

ffmpeg:
  hwaccel_args: preset-intel-vaapi  # Change: preset-nvidia or preset-amd-vaapi

logger:
  default: info
FRICONFIG

    # nginx vhost for Frigate
    if [[ -d /etc/nginx/forgeos.d ]]; then
        cat > /etc/nginx/forgeos.d/frigate.conf << NGINX
server {
    listen 443 ssl http2;
    server_name nvr.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    location / {
        proxy_pass         http://127.0.0.1:5001;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
    }
}
NGINX
        nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi

    local rtsp_pass; rtsp_pass=$(gen_password 16)
    forgenas_set "FRIGATE_RTSP_PASS" "$rtsp_pass"
    forgenas_set "FRIGATE_DIR"       "$FRIGATE_DIR"

    info "Frigate compose: ${FRIGATE_DIR}/docker-compose.yml"
    info "  Config:  ${FRIGATE_DATA}/config/config.yml  ← edit cameras here"
    info "  Media:   ${FRIGATE_DATA}/media"
    info "  Web UI:  https://nvr.${domain} (after: docker compose up -d)"
    info "  Start:   forgeos-coral frigate-start"
}

# ============================================================
# CLI
# ============================================================
install_coral_cli() {
    step "Installing forgeos-coral CLI"

    cat > /usr/local/bin/forgeos-coral << 'CORALCLI'
#!/usr/bin/env bash
# ForgeOS Coral TPU + Frigate Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true
FRIGATE_DIR="/opt/forgeos/apps/frigate"

case "$CMD" in
status)
    echo "=== Google Coral TPU Status ==="
    echo ""
    # PCI detection
    local pci_count; pci_count=$(lspci -nn 2>/dev/null | grep -c "089a" || echo "0")
    echo "  PCI detected:    ${pci_count} device(s) (ID: 1ac1:089a)"

    # Driver modules
    lsmod | grep -q gasket \
        && echo "  gasket module:   loaded" \
        || echo "  gasket module:   NOT LOADED (reboot may be needed)"
    lsmod | grep -q apex \
        && echo "  apex module:     loaded" \
        || echo "  apex module:     NOT LOADED"

    # Devices
    echo ""
    echo "  Apex devices:"
    local found=0
    for i in 0 1 2 3; do
        [[ -e "/dev/apex_${i}" ]] || continue
        local temp
        temp=$(cat "/sys/class/apex/apex_${i}/temp" 2>/dev/null \
               | awk '{printf "%.1f°C", $1/1000}' || echo "temp N/A")
        echo "    /dev/apex_${i}  — Edge TPU ${i}  ${temp}"
        (( found++ ))
    done
    [[ $found -eq 0 ]] && echo "    No /dev/apex_* devices found (need reboot?)"

    echo ""
    echo "  Frigate container:"
    docker ps --format '  {{.Names}}: {{.Status}}' 2>/dev/null | grep frigate || echo "  Not running"
    ;;

test)
    echo "Running Coral TPU inference test..."
    python3 -c "
import sys
try:
    from pycoral.utils.edgetpu import list_edge_tpus
    tpus = list_edge_tpus()
    print(f'  Edge TPUs found: {len(tpus)}')
    for t in tpus:
        print(f'    Type: {t[\"type\"]}  Path: {t.get(\"path\",\"N/A\")}')
except ImportError:
    # Fallback: check via file
    import os
    devs = [f for f in os.listdir('/dev') if f.startswith('apex_')]
    print(f'  /dev/apex_* devices: {len(devs)}  ({devs})')
    if devs:
        print('  PyCoral not installed but devices present — Frigate Docker will use them directly')
" 2>/dev/null || echo "  PyCoral test failed — check: ls /dev/apex_*"
    ;;

frigate-start)
    docker compose -f "${FRIGATE_DIR}/docker-compose.yml" pull 2>/dev/null || true
    docker compose -f "${FRIGATE_DIR}/docker-compose.yml" up -d
    echo "Frigate started"
    echo "  Web UI: https://nvr.$(grep ^DOMAIN /etc/forgeos/forgeos.conf | cut -d= -f2 | tr -d '\"')"
    echo "  Config: /srv/forgeos/frigate/config/config.yml"
    ;;
frigate-stop)
    docker compose -f "${FRIGATE_DIR}/docker-compose.yml" down
    ;;
frigate-logs)
    docker compose -f "${FRIGATE_DIR}/docker-compose.yml" logs --tail 50 -f
    ;;
frigate-config)
    "${EDITOR:-nano}" /srv/forgeos/frigate/config/config.yml
    docker compose -f "${FRIGATE_DIR}/docker-compose.yml" restart 2>/dev/null || true
    ;;

temp)
    for i in 0 1 2 3; do
        [[ -e "/sys/class/apex/apex_${i}/temp" ]] || continue
        local temp; temp=$(cat "/sys/class/apex/apex_${i}/temp" | awk '{printf "%.1f", $1/1000}')
        echo "  apex_${i}: ${temp}°C"
    done
    ;;

fix-aspm)
    echo "Applying pcie_aspm=off to GRUB (helps on some motherboards)"
    sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 pcie_aspm=off"/' \
        /etc/default/grub
    update-grub
    echo "Reboot required"
    ;;

rebuild-driver)
    echo "Rebuilding gasket-dkms for current kernel: $(uname -r)"
    dkms remove gasket/1.0 --all 2>/dev/null || true
    apt-get install -y linux-headers-$(uname -r) dkms git devscripts dh-dkms debhelper 2>/dev/null
    build_dir=$(mktemp -d)
    cd "$build_dir"
    git clone --depth=1 https://github.com/KyleGospo/gasket-dkms.git
    cd gasket-dkms
    debuild -us -uc -tc -b
    cd ..
    dpkg -i gasket-dkms_*.deb
    modprobe gasket; modprobe apex
    cd /; rm -rf "$build_dir"
    echo "Driver rebuilt. Check: ls /dev/apex_*"
    ;;

help|*)
    echo "ForgeOS Coral TPU + Frigate Manager"
    echo ""
    echo "  status              TPU detection + module status"
    echo "  test                Run inference test"
    echo "  temp                Read TPU temperature(s)"
    echo ""
    echo "  frigate-start       Start Frigate NVR"
    echo "  frigate-stop        Stop Frigate NVR"
    echo "  frigate-logs        Tail Frigate logs"
    echo "  frigate-config      Edit Frigate camera config"
    echo ""
    echo "  rebuild-driver      Rebuild gasket-dkms for current kernel"
    echo "  fix-aspm            Add pcie_aspm=off (if /dev/apex_* missing)"
    echo ""
    echo "  Single TPU: /dev/apex_0"
    echo "  Dual TPU:   /dev/apex_0 + /dev/apex_1"
    ;;
esac
CORALCLI
    chmod +x /usr/local/bin/forgeos-coral
}

# ============================================================
# MAIN
# ============================================================
detect_coral || {
    # No hardware detected — still install driver (user may add card later)
    # and generate Frigate compose with default 1-TPU config
    step "Installing Coral driver (no hardware now — ready for future install)"
    forgenas_set "CORAL_COUNT" "1"
}

install_gasket_dkms
install_edgetpu_runtime
configure_apex_system
configure_grub_for_coral
verify_coral
generate_frigate_compose
install_coral_cli

forgenas_set "MODULE_CORAL_DONE" "yes"
forgenas_set "FEATURE_CORAL" "yes"

info "Coral TPU module complete"
info "  Status:          forgeos-coral status"
info "  Start Frigate:   forgeos-coral frigate-start"
info "  Config cameras:  forgeos-coral frigate-config"
info "  Frigate UI:      https://nvr.$(forgenas_get DOMAIN nas.local)"
warn "  REBOOT REQUIRED for kernel modules to fully activate"
warn "  After reboot verify: ls /dev/apex_*"
warn "  If /dev/apex_* missing: forgeos-coral fix-aspm then reboot again"
