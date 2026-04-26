#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 22 - System Imaging (FOG)
# Network-based system imaging and deployment
#
# Does:
#   - FOG Project installation
#   - Web management interface
#   - PXE boot configuration
#   - Image capture/deploy workflow
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

FOG_DIR="/opt/fog"

# ============================================================
# INSTALL FOG
# ============================================================
install_fog() {
    step "Installing FOG Project (Network Imaging)"
    
    # Check if already installed
    if [[ -d "$FOG_DIR" ]]; then
        info "FOG already installed at $FOG_DIR"
        return 0
    fi
    
    # Install dependencies
    apt_update
    apt_install \
        apache2 mysql-server mysql-client \
        php php-mysql php-gd php-curl php-cli php-fpm \
        libapache2-mod-php \
        wget pxelinux syslinux syslinux-common \
        tftp-hpa xinetd \
        isolinux syslinux-common pxelinux
    
    # Clone FOG
    info "Downloading FOG Project..."
    git clone --depth 1 https://github.com/FOGProject/fogproject.git "$FOG_DIR"
    
    # Run FOG installation (unattended)
    cd "$FOG_DIR/bin"
    
    # Set FOG to use external database if available, or SQLite
    export FOG_IP="${FOG_IP:-$(hostname -I | awk '{print $1}}"
    export FOG_WEBROOT="/var/www/html/fog"
    export FOG_TFTP_IP="${FOG_IP}"
    
    # Run installer non-interactively
    yes | ./installfog.sh << 'FOGINSTALL'
y
y
n
y
y
n
n
y
y
n
FOGINSTALL
    
    info "FOG Project installed"
}

# ============================================================
# CONFIGURE FOG
# ============================================================
configure_fog() {
    step "Configuring FOG"
    
    # Enable and start FOG services
    systemctl enable fogapache 2>/dev/null || true
    systemctl start fogapache 2>/dev/null || true
    
    # Configure firewall
    if command -v ufw &>/dev/null; then
        ufw allow 80/tcp comment "FOG Web"
        ufw allow 443/tcp comment "FOG Web HTTPS"
        ufw allow 69/udp comment "FOG PXE"
    fi
    
    info "FOG configured at http://${FOG_IP:-$(hostname -I | awk '{print $1}')}/fog"
}

# ============================================================
# FOG API FOR FORGEOS
# ============================================================
configure_fog_api() {
    step "Configuring FOG API endpoints"
    
    # Add FOG status to ForgeOS API
    cat > /var/www/html/fog/api/forgeos-status.php << 'FOGAPI'
<?php
// ForgeOS FOG Status API
header('Content-Type: application/json');

// Check if FOG is running
$running = shell_exec('systemctl is-active fogapache') ?: 'inactive';
$running = trim($running) === 'active';

// Get image count
$imageCount = 0;
if (file_exists('/opt/fog/logs')) {
    $logDir = '/opt/fog/logs';
    if (is_dir($logDir)) {
        $imageCount = count(glob("$logDir/*"));
    }
}

echo json_encode([
    'running' => $running,
    'images' => $imageCount,
    'url' => '/fog'
]);
FOGAPI
    
    info "FOG API configured"
}

# ============================================================
# MAIN
# ============================================================
if [[ "${FORGEOS_SKIP:-false}" != "true" ]]; then
    install_fog
    configure_fog
    configure_fog_api
fi

info "Module 22 (FOG Imaging) complete"