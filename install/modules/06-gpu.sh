#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 06 - GPU Drivers
#
# Handles three GPU vendors automatically:
#   NVIDIA — ubuntu-drivers + CUDA toolkit + container toolkit
#   AMD    — ROCm 6.x + Mesa VA-API for transcoding
#   Intel  — i915/xe driver + Intel Media SDK (Arc support)
#
# Primary NAS use cases for GPU:
#   - Hardware video transcoding (Plex, Jellyfin, Immich AI)
#   - AI/ML inference (Immich face recognition, object detection)
#   - Stable Diffusion / LLM inference (advanced homelab)
#
# This module is OPTIONAL — ForgeOS runs fine without it.
# Only installs what the detected hardware needs.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

# ============================================================
# NVIDIA
# ============================================================
install_nvidia() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${GPU_NVIDIA:-false}" != "true" ]] && return 0

    step "Installing NVIDIA drivers"

    # ubuntu-drivers: auto-selects recommended driver version
    apt_install ubuntu-drivers-common

    # Get recommended driver version
    local recommended
    recommended=$(ubuntu-drivers devices 2>/dev/null \
        | awk '/recommended/{print $3}' | head -1 || echo "nvidia-driver-535")
    [[ -z "$recommended" ]] && recommended="nvidia-driver-535"

    apt_install "$recommended" \
        nvidia-cuda-toolkit \
        nvidia-utils-"${recommended##*-}" \
        2>/dev/null || apt_install "$recommended"

    # NVIDIA persistence daemon (keeps GPU initialized, reduces init latency)
    apt_install_optional nvidia-persistenced

    # CUDA symlinks expected by some ML frameworks
    ln -sf /usr/local/cuda /usr/local/cuda-current 2>/dev/null || true

    # Verify install (will work after reboot if kernel module not loaded yet)
    if nvidia-smi &>/dev/null; then
        local gpu_name; gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        info "NVIDIA: ${gpu_name:-detected} (driver: ${recommended})"
    else
        info "NVIDIA driver installed — GPU available after reboot"
    fi

    # nvidia-container-toolkit wired in module 04 if Docker present
    if command -v docker &>/dev/null; then
        _install_nvidia_container_toolkit
    fi

    forgenas_set "GPU_DRIVER_NVIDIA" "$recommended"

    # Enable hardware transcoding profile for Jellyfin/Plex
    _write_nvidia_compose_override
}

_install_nvidia_container_toolkit() {
    command -v nvidia-ctk &>/dev/null && return 0

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
        2>/dev/null || return 1

    curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list

    _apt_ready=false
    apt_install nvidia-container-toolkit || return 1
    nvidia-ctk runtime configure --runtime=docker >> "$FORGENAS_LOG" 2>&1 || true
    systemctl restart docker 2>/dev/null || true
    info "NVIDIA Container Toolkit: Docker GPU access enabled"
}

_write_nvidia_compose_override() {
    mkdir -p /opt/forgeos/apps/gpu-profiles
    cat > /opt/forgeos/apps/gpu-profiles/nvidia-transcoding.yml << 'NVTC'
# Paste this into any docker-compose.yml service that needs NVIDIA GPU
# (Jellyfin, Plex, Stable Diffusion, etc.)
#
# services:
#   jellyfin:
#     ...
#     runtime: nvidia
#     environment:
#       - NVIDIA_VISIBLE_DEVICES=all
#       - NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
#     devices:
#       - /dev/dri:/dev/dri
NVTC
}

# ============================================================
# AMD ROCm
# AMD cards work natively for transcoding via VA-API.
# ROCm is for compute/AI workloads (optional heavy install ~4GB).
# ============================================================
install_amd() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${GPU_AMD:-false}" != "true" ]] && return 0

    step "Installing AMD GPU drivers (VA-API + ROCm)"

    # VA-API drivers — needed for hardware transcoding (Jellyfin/Plex)
    apt_install \
        mesa-va-drivers \
        mesa-vdpau-drivers \
        va-driver-all \
        vainfo \
        libva2 \
        libva-drm2

    # Add current user to render/video groups for GPU access
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local user="${ADMIN_USER:-forgeos}"
    usermod -aG render,video "$user" 2>/dev/null || true

    # Verify VA-API
    if vainfo &>/dev/null; then
        info "AMD VA-API: hardware transcoding available"
    else
        info "AMD VA-API drivers installed — verify with: vainfo"
    fi

    # ROCm (optional — only if ROCM=yes set, it's a large install)
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    if [[ "${ROCM:-no}" == "yes" ]]; then
        _install_rocm
    else
        info "AMD ROCm: skipped (set ROCM=yes to install for AI/ML workloads)"
        info "  ROCm is ~4GB and needed only for GPU compute, not transcoding"
    fi

    forgenas_set "GPU_DRIVER_AMD" "mesa+vaapi"
}

_install_rocm() {
    step "Installing AMD ROCm (GPU compute)"

    # AMD ROCm official repo
    wget -qO - https://repo.radeon.com/rocm/rocm.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/rocm.gpg 2>/dev/null || {
        warn "ROCm GPG key fetch failed — skipping ROCm"
        return 1
    }

    local codename; codename=$(lsb_release -cs)
    cat > /etc/apt/sources.list.d/rocm.list << ROCM
deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] \
https://repo.radeon.com/rocm/apt/latest ${codename} main
ROCM

    _apt_ready=false
    apt_install rocm-hip-libraries rocm-opencl-runtime 2>/dev/null \
        || warn "ROCm install failed — check AMD support for your GPU model"

    # ROCm env vars
    cat > /etc/profile.d/rocm.sh << 'ROCMENV'
export ROCM_PATH=/opt/rocm
export PATH=$PATH:/opt/rocm/bin:/opt/rocm/hip/bin
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/opencl/lib/x86_64
ROCMENV

    info "AMD ROCm installed — GPU compute ready"
}

# ============================================================
# INTEL ARC / QUICK SYNC
# Intel Arc (DG2+) and older iGPUs via i915/xe driver.
# HWE kernel 6.8+ required for Arc discrete GPU support.
# ============================================================
install_intel() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${GPU_INTEL:-false}" != "true" ]] && return 0

    step "Installing Intel GPU drivers (i915/xe + Quick Sync)"

    # Intel media stack
    apt_install \
        intel-media-va-driver-non-free \
        intel-gpu-tools \
        vainfo \
        i965-va-driver \
        libva2 \
        libva-drm2 \
        libigdgmm12 \
        2>/dev/null || apt_install \
        mesa-va-drivers \
        vainfo \
        libva2

    # Intel Arc discrete GPU needs newer kernel (6.8+) and xe driver
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    if [[ "${GPU_INTEL_ARC:-false}" == "true" ]]; then
        _install_intel_arc
    fi

    # Add user to render/video groups
    local user="${ADMIN_USER:-forgeos}"
    usermod -aG render,video "$user" 2>/dev/null || true

    if vainfo 2>/dev/null | grep -qi "intel"; then
        info "Intel Quick Sync: VA-API hardware transcoding ready"
    else
        info "Intel GPU drivers installed"
        info "  Verify with: vainfo  (may need reboot first)"
    fi

    forgenas_set "GPU_DRIVER_INTEL" "i915+vaapi"
}

_install_intel_arc() {
    step "Configuring Intel Arc GPU support"

    local kernel_ver; kernel_ver=$(uname -r | cut -d. -f1-2)
    # Arc requires kernel 6.2+ for basic support, 6.8+ for full xe driver
    if ! awk "BEGIN{exit !($kernel_ver >= 6.2)}"; then
        # Install HWE kernel
        apt_install_optional linux-generic-hwe-22.04 linux-headers-generic-hwe-22.04
        info "Intel Arc: HWE kernel queued — reboot required for full Arc support"
    fi

    # Intel Graphics repo for latest firmware/drivers
    wget -qO - https://repositories.intel.com/graphics/intel-graphics.key \
        | gpg --dearmor -o /usr/share/keyrings/intel-graphics.gpg 2>/dev/null || {
        warn "Intel graphics repo key failed — using default Mesa drivers"
        return 0
    }

    local codename; codename=$(lsb_release -cs)
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/intel-graphics.gpg] \
https://repositories.intel.com/graphics/ubuntu ${codename} arc" \
        > /etc/apt/sources.list.d/intel-arc.list

    _apt_ready=false
    apt_install \
        intel-opencl-icd \
        intel-level-zero-gpu \
        intel-media-va-driver-non-free \
        libmfx1 libmfxgen1 libvpl2 \
        2>/dev/null || warn "Some Intel Arc packages unavailable — basic driver active"

    # Arc-specific kernel module parameters
    cat > /etc/modprobe.d/intel-arc.conf << 'ARCMOD'
# Intel Arc GPU optimizations
options i915 enable_guc=3
options i915 enable_fbc=1
options xe force_probe=*
ARCMOD

    # Enable GuC/HuC firmware (required for Arc hardware encode/decode)
    cat > /etc/dracut.conf.d/intel-arc.conf << 'DRACUT'
add_drivers+=" xe i915 "
DRACUT

    update-initramfs -u >> "$FORGENAS_LOG" 2>&1 || true

    info "Intel Arc: xe driver configured, GuC/HuC firmware enabled"
    info "  Reboot required for full hardware transcoding"
}

# ============================================================
# TRANSCODING HELPER — writes Docker env for Jellyfin/Plex
# Makes hardware transcoding a one-liner to enable.
# ============================================================
write_transcoding_profiles() {
    step "Writing hardware transcoding profiles"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local profile_dir="/opt/forgeos/apps/gpu-profiles"
    mkdir -p "$profile_dir"

    # Jellyfin compose with auto-detected GPU
    cat > "${profile_dir}/jellyfin-gpu.yml" << JELLY
version: "3.8"
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: forgeos-jellyfin
    restart: unless-stopped
    network_mode: host
    volumes:
      - /srv/forgeos/jellyfin/config:/config
      - /srv/forgeos/jellyfin/cache:/cache
      - /srv/nas/media:/media:ro
    devices:
      - /dev/dri:/dev/dri        # VA-API (AMD/Intel)
    environment:
      - JELLYFIN_PublishedServerUrl=https://media.${DOMAIN:-nas.local}
$(
[[ "${GPU_NVIDIA:-false}" == "true" ]] && cat << NVIDENV
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
NVIDENV
)
JELLY

    info "Transcoding profiles written to ${profile_dir}/"
    info "  Start Jellyfin with GPU: docker compose -f ${profile_dir}/jellyfin-gpu.yml up -d"
}

# ============================================================
# VERIFY + REPORT
# ============================================================
gpu_report() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    echo ""
    echo "  ── GPU Status ─────────────────────────────────────"
    [[ "${GPU_NVIDIA:-false}" == "true" ]] && \
        echo "  NVIDIA: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1 || echo 'installed (needs reboot)')"
    [[ "${GPU_AMD:-false}"    == "true" ]] && \
        echo "  AMD:    $(vainfo 2>/dev/null | awk '/Driver version/{print $NF}' || echo 'installed')"
    [[ "${GPU_INTEL:-false}"  == "true" ]] && \
        echo "  Intel:  $(vainfo 2>/dev/null | awk '/VA-API version/{print $NF}' || echo 'installed')"
    [[ "${GPU_NVIDIA:-false}" != "true" && \
       "${GPU_AMD:-false}"    != "true" && \
       "${GPU_INTEL:-false}"  != "true" ]] && \
        echo "  No GPU detected — CPU transcoding only"
    echo ""
}

# ============================================================
# MAIN
# ============================================================
install_nvidia
install_amd
install_intel
write_transcoding_profiles
gpu_report

forgenas_set "MODULE_GPU_DONE" "yes"
info "GPU module complete"
