#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 04 - Docker CE + Incus
#
# Docker CE — official repo, not snap or distro package
# Incus     — LXC/LXD successor (via Zabbly repo)
#             Used for lightweight Linux containers (VMs without overhead)
#
# Docker is used by: monitoring stack, mail, Gotify, MinIO, databases
# Incus is used by: running Windows/Linux VMs, testing, isolation
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

# ============================================================
# DOCKER CE
# ============================================================
install_docker() {
    step "Installing Docker CE (official repo)"

    # Remove snap/distro docker if present
    for pkg in docker docker-engine docker.io containerd runc docker-compose; do
        DEBIAN_FRONTEND=noninteractive apt-get remove -y -q "$pkg" \
            >> "$FORGENAS_LOG" 2>&1 || true
    done

    # Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc 2>/dev/null \
        || curl -fsSL https://download.docker.com/linux/debian/gpg \
           -o /etc/apt/keyrings/docker.asc 2>/dev/null \
        || die "Could not download Docker GPG key"
    chmod a+r /etc/apt/keyrings/docker.asc

    # Docker repo
    local distro; distro=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
    local codename; codename=$(lsb_release -cs)
    # Ubuntu 24.04 (noble) → use jammy repo (Docker hasn't released noble yet)
    [[ "$codename" == "noble" ]] && codename="jammy"

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/${distro} ${codename} stable" \
        > /etc/apt/sources.list.d/docker.list

    _apt_ready=false  # force re-update
    apt_install \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    # Docker daemon config — optimized for NAS
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json << 'DOCKER'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "live-restore": true,
  "userland-proxy": false,
  "metrics-addr": "127.0.0.1:9323",
  "experimental": false,
  "ipv6": false,
  "default-address-pools": [
    {"base": "172.16.0.0/12", "size": 24}
  ],
  "data-root": "/var/lib/docker"
}
DOCKER

    enable_service docker

    # Add admin user to docker group
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local user="${ADMIN_USER:-forgeos}"
    usermod -aG docker "$user" 2>/dev/null || true

    # Create ForgeOS internal Docker network
    docker network create forgeos-internal \
        --driver bridge \
        --subnet 172.20.0.0/16 \
        >> "$FORGENAS_LOG" 2>&1 || true  # already exists is OK

    info "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
    info "  docker compose: $(docker compose version --short 2>/dev/null)"
}

# ============================================================
# DOCKER COMPOSE WRAPPER
# Ensures 'docker-compose' (v1 style) still works for older scripts
# ============================================================
install_compose_shim() {
    if ! command -v docker-compose &>/dev/null; then
        cat > /usr/local/bin/docker-compose << 'SHIM'
#!/usr/bin/env bash
exec docker compose "$@"
SHIM
        chmod +x /usr/local/bin/docker-compose
    fi
}

# ============================================================
# INCUS
# LXD successor — system containers and VMs.
# Zabbly is the official maintained repo for Incus on Ubuntu/Debian.
# ============================================================
install_incus() {
    step "Installing Incus (LXC/LXD successor)"

    # Zabbly repo
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.zabbly.com/key.asc \
        -o /etc/apt/keyrings/zabbly.asc >> "$FORGENAS_LOG" 2>&1 \
        || { warn "Could not reach Zabbly repo — Incus install skipped"; return 0; }

    local codename; codename=$(lsb_release -cs)
    cat > /etc/apt/sources.list.d/zabbly-incus-stable.list << INCUS
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/zabbly.asc] \
https://pkgs.zabbly.com/incus/stable $(lsb_release -cs) main
INCUS

    _apt_ready=false
    apt_install incus incus-ui-canonical 2>/dev/null \
        || apt_install incus \
        || { warn "Incus not available — skipping (Docker only)"; return 0; }

    # Initialize Incus with minimal configuration
    cat > /tmp/incus-init.yaml << 'INCUSINIT'
config: {}
networks:
- config:
    ipv4.address: 192.168.200.1/24
    ipv4.nat: "true"
    ipv6.address: none
  description: ""
  name: incusbr0
  type: bridge
storage_pools:
- config:
    size: 50GiB
  description: ""
  driver: btrfs
  name: default
profiles:
- config: {}
  description: Default profile
  devices:
    eth0:
      name: eth0
      network: incusbr0
      type: nic
    root:
      path: /
      pool: default
      type: disk
  name: default
INCUSINIT

    incus admin init --preseed < /tmp/incus-init.yaml >> "$FORGENAS_LOG" 2>&1 \
        || warn "Incus auto-init failed — run 'sudo incus admin init' manually"
    rm -f /tmp/incus-init.yaml

    # Add admin user to incus-admin group
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local user="${ADMIN_USER:-forgeos}"
    usermod -aG incus-admin "$user" 2>/dev/null || true

    enable_service incus incus.socket 2>/dev/null || true

    info "Incus $(incus --version 2>/dev/null || echo 'installed')"
    info "  LAN bridge: incusbr0 (192.168.200.1/24)"
    info "  Storage:    50GB btrfs pool"
}

# ============================================================
# NVIDIA CONTAINER TOOLKIT (if NVIDIA GPU detected)
# ============================================================
install_nvidia_container_toolkit() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${GPU_NVIDIA:-false}" != "true" ]] && return 0

    step "Installing NVIDIA Container Toolkit"

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
        >> "$FORGENAS_LOG" 2>&1 || { warn "NVIDIA toolkit GPG failed"; return 0; }

    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >> "$FORGENAS_LOG" 2>&1

    _apt_ready=false
    apt_install nvidia-container-toolkit || { warn "NVIDIA container toolkit install failed"; return 0; }

    # Configure Docker to use NVIDIA runtime
    nvidia-ctk runtime configure --runtime=docker >> "$FORGENAS_LOG" 2>&1 || true
    systemctl restart docker 2>/dev/null || true

    info "NVIDIA Container Toolkit: Docker can now use GPU"
}

# ============================================================
# PORTAINER (lightweight Docker UI, optional)
# Disabled by default — ForgeOS has its own container view
# Set PORTAINER=yes to enable
# ============================================================
install_portainer() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${PORTAINER:-no}" != "yes" ]] && return 0

    step "Installing Portainer (Docker UI)"

    docker volume create portainer_data >> "$FORGENAS_LOG" 2>&1 || true
    docker run -d \
        --name portainer \
        --restart always \
        -p 127.0.0.1:9443:9443 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v portainer_data:/data \
        portainer/portainer-ce:latest \
        >> "$FORGENAS_LOG" 2>&1 || warn "Portainer install failed"

    info "Portainer available at https://127.0.0.1:9443"
}

# ============================================================
# MAIN
# ============================================================
install_docker
install_compose_shim
install_incus
install_nvidia_container_toolkit
install_portainer

# Verify
docker run --rm hello-world >> "$FORGENAS_LOG" 2>&1 \
    && info "Docker test: ✓ hello-world" \
    || warn "Docker test failed — check: journalctl -u docker"

forgenas_set "MODULE_DOCKER_DONE" "yes"
forgenas_set "DOCKER_INSTALLED" "yes"
info "Docker + Incus module complete"
