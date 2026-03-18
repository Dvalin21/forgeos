#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 01 - Base System
# Runs first. Everything else depends on this.
#
# Does:
#   - Core package installation
#   - NAS-optimized kernel parameters (sysctl)
#   - Filesystem limits (open files, inotify watches)
#   - Hostname / timezone finalization
#   - Unattended security upgrades
#   - Admin user creation
#   - ForgeOS directory structure
#   - SSH hardening (key-only, no root password login)
#   - System journal configuration
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

# ============================================================
# CORE PACKAGES
# ============================================================
install_base_packages() {
    step "Installing base packages"

    apt_update

    # Essential tools every module expects
    apt_install \
        curl wget git gnupg2 ca-certificates lsb-release \
        apt-transport-https software-properties-common \
        build-essential python3 python3-pip python3-venv \
        sudo htop iotop iftop sysstat dstat \
        ncdu tree jq bc less nano vim \
        net-tools iputils-ping dnsutils traceroute \
        rsync pv mbuffer \
        unzip p7zip-full tar gzip bzip2 xz-utils \
        acl attr quota \
        cron logrotate \
        ntp chrony \
        openssh-server \
        tmux screen \
        lsof strace \
        dmidecode pciutils usbutils \
        "linux-headers-$(uname -r)" 2>/dev/null || apt_install linux-headers-generic

    # HWE kernel for newer hardware support (Intel Arc, etc.)
    if lsb_release -rs 2>/dev/null | grep -qE '^22'; then
        apt_install_optional linux-generic-hwe-22.04 linux-headers-generic-hwe-22.04
    elif lsb_release -rs 2>/dev/null | grep -qE '^24'; then
        apt_install_optional linux-generic-hwe-24.04
    fi

    info "Base packages installed"
}

# ============================================================
# NAS-OPTIMIZED KERNEL PARAMETERS
# These are tuned for a storage server, not a desktop or web server.
# Key differences: large inotify limits, VM dirty ratio for btrfs,
# network buffers for 10GbE, inode cache size.
# ============================================================
configure_sysctl() {
    step "Configuring kernel parameters (NAS-optimized)"

    cat > /etc/sysctl.d/90-forgeos-nas.conf << 'SYSCTL'
# ForgeOS NAS kernel parameters
# Tuned for storage server workloads

# ── VM / Memory ──────────────────────────────────────────────
# Reduce kernel swap aggression (NAS should stay in RAM)
vm.swappiness = 10

# btrfs write performance: allow more dirty pages before writeback
# Default is 20% — for NAS with large RAM, 40% is better
vm.dirty_ratio = 40
vm.dirty_background_ratio = 10

# Minimum free memory — prevent OOM on large rsync operations
vm.min_free_kbytes = 262144

# ── Filesystem ───────────────────────────────────────────────
# inotify limits — ForgeFileDB and monitoring watch thousands of files
fs.inotify.max_user_watches    = 1048576
fs.inotify.max_user_instances  = 1024
fs.inotify.max_queued_events   = 32768

# File descriptor limits — Samba + Docker + monitoring need many
fs.file-max = 2097152
fs.nr_open  = 2097152

# aio-max-nr — for Samba AIO (improves SMB3 throughput significantly)
fs.aio-max-nr = 1048576

# ── Network ──────────────────────────────────────────────────
# Large socket buffers for 10GbE NAS workloads
net.core.rmem_max           = 134217728
net.core.wmem_max           = 134217728
net.core.rmem_default       = 16777216
net.core.wmem_default       = 16777216
net.core.netdev_max_backlog = 300000
net.core.optmem_max         = 40960

net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_mem  = 786432 1048576 26777216

# BBR congestion control (better throughput on 10GbE)
net.core.default_qdisc    = fq
net.ipv4.tcp_congestion_control = bbr

# TIME_WAIT recycling — important for NFS/SMB connection reuse
net.ipv4.tcp_fin_timeout  = 15
net.ipv4.tcp_tw_reuse     = 1
net.ipv4.tcp_max_tw_buckets = 2000000

# Source routing / spoofing protection
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.rp_filter     = 1

# Syn flood protection
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 8096

# Disable ICMP redirects
net.ipv4.conf.all.accept_redirects    = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects    = 0

# ── Kernel ───────────────────────────────────────────────────
# Larger pid space — for Docker + lots of services
kernel.pid_max = 4194304

# Disable magic sysrq for security
kernel.sysrq = 0

# Kernel panic: auto-reboot after 10 seconds
kernel.panic = 10
kernel.panic_on_oops = 1
SYSCTL

    sysctl -p /etc/sysctl.d/90-forgeos-nas.conf >> "$FORGENAS_LOG" 2>&1 || \
        warn "Some sysctl params not applied (may need reboot)"

    info "Kernel parameters: NAS-optimized sysctl applied"
}

# ============================================================
# SYSTEM LIMITS
# ============================================================
configure_limits() {
    step "Configuring system limits"

    # Increase file descriptor and process limits for root + forgeos user
    cat > /etc/security/limits.d/90-forgeos.conf << 'LIMITS'
# ForgeOS system limits
# Applied to: root, forgeos service user, and all users

*         soft  nofile    1048576
*         hard  nofile    1048576
root      soft  nofile    1048576
root      hard  nofile    1048576
*         soft  nproc     65536
*         hard  nproc     65536

# Large stack for btrfs + mdadm operations
*         soft  stack     65536
*         hard  stack     65536
LIMITS

    # PAM limits
    grep -q 'pam_limits.so' /etc/pam.d/common-session 2>/dev/null || \
        echo 'session required pam_limits.so' >> /etc/pam.d/common-session

    # systemd limits (overrides /etc/security/limits.conf for services)
    mkdir -p /etc/systemd/system.conf.d
    cat > /etc/systemd/system.conf.d/forgeos-limits.conf << 'SYSD'
[Manager]
DefaultLimitNOFILE=1048576
DefaultLimitNPROC=65536
DefaultTasksMax=infinity
SYSD

    systemctl daemon-reexec 2>/dev/null || true
    info "System limits: 1M open files, 65K processes"
}

# ============================================================
# HOSTNAME + TIMEZONE
# ============================================================
configure_hostname_tz() {
    step "Configuring hostname and timezone"
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"

    local hostname="${HOSTNAME:-forgeos}"
    local domain="${DOMAIN:-nas.local}"
    local tz="${TIMEZONE:-UTC}"

    hostnamectl set-hostname "$hostname" 2>/dev/null || hostname "$hostname"

    # /etc/hosts entry
    local ip; ip=$(ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1 | head -1 || echo "127.0.1.1")
    grep -q "$hostname" /etc/hosts || \
        echo "${ip}  ${hostname}.${domain}  ${hostname}" >> /etc/hosts

    # Timezone
    timedatectl set-timezone "$tz" 2>/dev/null || ln -sf "/usr/share/zoneinfo/${tz}" /etc/localtime

    # NTP sync
    timedatectl set-ntp true 2>/dev/null || true

    info "Hostname: ${hostname}.${domain}  Timezone: ${tz}"
}

# ============================================================
# ADMIN USER
# ============================================================
setup_admin_user() {
    step "Setting up admin user"
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local user="${ADMIN_USER:-forgeos}"

    if ! id "$user" &>/dev/null; then
        useradd -m -s /bin/bash -G sudo,adm "$user"
        local pass; pass=$(gen_password 20)
        echo "${user}:${pass}" | chpasswd
        forgenas_set "ADMIN_PASS" "$pass"
        info "Created user: $user (password saved to forgeos.conf)"
    else
        # Ensure in right groups
        usermod -aG sudo,adm "$user" 2>/dev/null || true
        info "Admin user $user already exists — groups updated"
    fi

    # Create users group for Samba
    getent group users &>/dev/null || groupadd users
    id "$user" | grep -q "users" || usermod -aG users "$user" 2>/dev/null || true

    # sudo without password for forgeos admin (NAS use case)
    echo "${user} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/${user}"
    chmod 440 "/etc/sudoers.d/${user}"
}

# ============================================================
# SSH HARDENING
# ============================================================
harden_ssh() {
    step "Hardening SSH"

    # Backup original config
    cp /etc/ssh/sshd_config "/etc/ssh/sshd_config.bak.$(date +%Y%m%d)" 2>/dev/null || true

    cat > /etc/ssh/sshd_config.d/90-forgeos.conf << 'SSH'
# ForgeOS SSH hardening
# Applied on top of default sshd_config

# Protocol
Protocol 2

# Authentication
PermitRootLogin prohibit-password
PasswordAuthentication yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitEmptyPasswords no
MaxAuthTries 4
LoginGraceTime 30s

# Performance
UseDNS no
GSSAPIAuthentication no
GSSAPICleanupCredentials no

# Sessions
ClientAliveInterval 300
ClientAliveCountMax 3
MaxSessions 20
MaxStartups 10:30:100

# Security
X11Forwarding no
AllowAgentForwarding yes
AllowTcpForwarding yes
PrintLastLog yes
Banner none

# Ciphers — modern only
Ciphers aes256-gcm@openssh.com,chacha20-poly1305@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512
SSH

    sshd -t >> "$FORGENAS_LOG" 2>&1 || warn "SSH config test warning — check manually"
    systemctl reload sshd 2>/dev/null || systemctl restart ssh 2>/dev/null || true
    info "SSH hardened: modern ciphers, no root password auth"
}

# ============================================================
# DIRECTORY STRUCTURE
# ============================================================
create_directory_structure() {
    step "Creating ForgeOS directory structure"

    local dirs=(
        /etc/forgeos
        /etc/forgeos/backup/keys
        /etc/forgeos/samba/shares
        /etc/forgeos/filedb
        /etc/forgeos/nginx
        /etc/forgeos/notifications
        /etc/forgeos/rclone
        /opt/forgeos
        /opt/forgeos/apps
        /opt/forgeos/scripts
        /opt/forgeos/web
        /opt/forgeos/backup/scripts
        /srv/nas
        /srv/nas/data
        /srv/nas/media
        /srv/nas/public
        /srv/nas/backups
        /srv/nas/timemachine
        /srv/forgeos
        /srv/forgeos/databases
        /srv/forgeos/backups/restic
        /srv/forgeos/filedb/snapshots
        /srv/forgeos/monitoring
        /var/log/forgeos
        /var/log/forgeos/samba
        /var/log/forgeos/backup
        /var/lib/forgeos
    )

    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
    done

    # Permissions
    chmod 700 /etc/forgeos /etc/forgeos/backup/keys
    chmod 755 /srv/nas /opt/forgeos
    chmod 777 /srv/nas/public   # world-readable public share
    chmod 1777 /srv/nas/timemachine  # sticky bit

    # Set group ownership for NAS shares
    getent group users &>/dev/null && chown -R :users /srv/nas 2>/dev/null || true
    chmod -R g+w /srv/nas 2>/dev/null || true

    info "Directory structure created under /etc/forgeos, /opt/forgeos, /srv/nas"
}

# ============================================================
# UNATTENDED SECURITY UPGRADES
# ============================================================
configure_auto_updates() {
    step "Configuring automatic security updates"

    apt_install unattended-upgrades apt-listchanges

    cat > /etc/apt/apt.conf.d/50forgeos-unattended-upgrades << 'APT'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Package-Blacklist {};
Unattended-Upgrade::DevRelease "false";
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
Unattended-Upgrade::SyslogEnable "true";
APT

    cat > /etc/apt/apt.conf.d/20auto-upgrades << 'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
APT

    enable_service unattended-upgrades
    info "Automatic security upgrades: enabled (no auto-reboot)"
}

# ============================================================
# JOURNAL CONFIG
# ============================================================
configure_journal() {
    step "Configuring systemd journal"

    mkdir -p /etc/systemd/journald.conf.d
    cat > /etc/systemd/journald.conf.d/forgeos.conf << 'JOURNAL'
[Journal]
SystemMaxUse=2G
SystemKeepFree=500M
MaxRetentionSec=90day
Compress=yes
Storage=persistent
RateLimitBurst=10000
RateLimitIntervalSec=30s
JOURNAL

    systemctl restart systemd-journald 2>/dev/null || true
    info "Journal: 2GB max, 90-day retention, compressed"
}

# ============================================================
# LOGROTATE
# ============================================================
configure_logrotate() {
    cat > /etc/logrotate.d/forgeos << 'LR'
/var/log/forgeos/*.log
/var/log/forgeos/**/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    sharedscripts
    postrotate
        systemctl reload rsyslog 2>/dev/null || true
    endscript
}
LR
}

# ============================================================
# MOTD
# ============================================================
configure_motd() {
    cat > /etc/motd << 'MOTD'

  ╔══════════════════════════════════════════════════════╗
  ║  ForgeOS — NAS & Server Platform                    ║
  ║  Web UI:  https://nas.local                         ║
  ║  Docs:    forgeos-ctl help                          ║
  ╚══════════════════════════════════════════════════════╝

MOTD

    # Disable Ubuntu's dynamic MOTD (it's slow and noisy)
    chmod -x /etc/update-motd.d/* 2>/dev/null || true
}

# ============================================================
# MAIN
# ============================================================
require_root
require_ubuntu_debian

install_base_packages
configure_sysctl
configure_limits
configure_hostname_tz
setup_admin_user
harden_ssh
create_directory_structure
configure_auto_updates
configure_journal
configure_logrotate
configure_motd

forgenas_set "MODULE_BASE_DONE" "yes"
info "Base module complete"
