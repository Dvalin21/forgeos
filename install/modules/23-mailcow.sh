#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 23 - MailCow
# Docker-based full-featured mail server
# ALTERNATIVE to module 14 (traditional stack)
#
# Does:
#   - MailCow Docker installation
#   - Web management interface
#   - ActiveSync for mobile
#   - SOGo webmail included
#
# Note: Use EITHER module 14 OR module 23, not both
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

MAILCOW_DIR="/opt/mailcow"

# ============================================================
# INSTALL MAILCOW
# ============================================================
install_mailcow() {
    step "Installing MailCow"
    
    # Check if already installed
    if [[ -d "$MAILCOW_DIR" ]]; then
        info "MailCow already installed at $MAILCOW_DIR"
        return 0
    fi
    
    # Install Docker if not present
    if ! command -v docker &>/dev/null; then
        apt_update
        apt_install docker.io docker-compose
    fi
    
    # Clone MailCow
    info "Downloading MailCow..."
    git clone https://github.com/mailcow/docker-mailcow.git "$MAILCOW_DIR"
    
    # Copy configuration template
    cp "$MAILCOW_DIR/mailcow.conf" "$MAILCOW_DIR/mailcow.conf.bak" 2>/dev/null || true
    cp -n "$MAILCOW_DIR/mailcow.conf.sample" "$MAILCOW_DIR/mailcow.conf"
    
    # Configure MailCow
    info "Configuring MailCow..."
    
    # Set timezone
    sed -i "s|^#TZ=Europe/Berlin|TZ=${FORGEOS_TIMEZONE:-America/Chicago}|" "$MAILCOW_DIR/mailcow.conf"
    
    # Set hostname
    sed -i "s|^#MAILCOW_SMTP_HOSTNAME=mail.example.com|MAILCOW_SMTP_HOSTNAME=${FORGEOS_HOSTNAME}.${FORGEOS_DOMAIN}|" "$MAILCOW_DIR/mailcow.conf"
    
    # Generate API key
    API_KEY=$(openssl rand -hex 32)
    sed -i "s|^#API_KEY=|API_KEY=$API_KEY|" "$MAILCOW_DIR/mailcow.conf"
    
    # Start MailCow
    cd "$MAILCOW_DIR"
    docker-compose up -d
    
    info "MailCow installed and running"
}

# ============================================================
# CONFIGURE MAILCOW
# ============================================================
configure_mailcow() {
    step "Configuring MailCow integration"
    
    # Wait for MailCow to be ready
    sleep 10
    
    # Get MailCow ports
    MAILCOW_HTTP=$(grep "^#MAILCOW_HTTP_PORT" "$MAILCOW_DIR/mailcow.conf" | cut -d= -f2 || echo "80")
    MAILCOW_HTTPS=$(grep "^#MAILCOW_HTTPS_PORT" "$MAILCOW_DIR/mailcow.conf" | cut -d= -f2 || echo "443")
    
    # Configure nginx proxy if enabled
    if [[ "${FORGEOS_ENABLE_NGINX:-true}" == "true" ]]; then
        info "MailCow available at https://mail.${FORGEOS_DOMAIN:-localhost}"
    fi
    
    # Enable firewall ports (if using ufw)
    if command -v ufw &>/dev/null; then
        ufw allow ${MAILCOW_HTTPS}/tcp comment "MailCow HTTPS"
    fi
    
    info "MailCow configured"
}

# ============================================================
# MAILCOW API FOR FORGEOS
# ============================================================
configure_mailcow_api() {
    step "Adding MailCow to ForgeOS API"
    
    # Add endpoint to check MailCow status
    # This would be integrated into forgeos-api.py
    cat > /var/www/html/api/mailcow-status.php << 'MAILCOWAPI'
<?php
// ForgeOS MailCow Status API
header('Content-Type: application/json');

$mailcowDir = '/opt/mailcow';
$running = false;
$queue = 0;

if (file_exists($mailcowDir)) {
    // Check if containers are running
    $output = shell_exec("cd $mailcowDir && docker-compose ps -q postfix");
    $running = !empty(trim($output));
    
    // Get queue count
    if ($running) {
        $queueOutput = shell_exec("docker exec mailcow_postfix-mailcow_1 mailq 2>/dev/null | tail -1");
        if (preg_match('/(\d+)/', $queueOutput ?? '', $matches)) {
            $queue = intval($matches[1]);
        }
    }
}

echo json_encode([
    'running' => $running,
    'queue' => $queue,
    'url' => '/SOGo'
]);
MAILCOWAPI
    
    info "MailCow API configured"
}

# ============================================================
# MAIN
# ============================================================
if [[ "${FORGEOS_SKIP:-false}" != "true" ]]; then
    install_mailcow
    configure_mailcow
    configure_mailcow_api
fi

info "Module 23 (MailCow) complete"