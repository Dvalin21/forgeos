#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 20 - Borg Backup
# Deduplicated, encrypted, compressed backups
#
# Does:
#   - BorgBackup installation
#   - Backup repository initialization
#   - Scheduled backup jobs
#   - One-click restore
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

BORG_REPO_LOCAL="/srv/forgeos/backups/borg"

# ============================================================
# INSTALL BORG
# ============================================================
install_borg() {
    step "Installing Borg Backup"
    
    if ! command -v borg &>/dev/null; then
        apt_update
        apt_install borgbackup
    fi
    
    info "Borg $(borg --version)"
}

# ============================================================
# CONFIGURE BORG
# ============================================================
configure_borg() {
    step "Configuring Borg backup repository"
    
    mkdir -p "$BORG_REPO_LOCAL"
    
    # Initialize repository if not exists
    if [[ ! -d "$BORG_REPO/local".config ]]; then
        info "Initializing Borg repository at $BORG_REPO_LOCAL"
        borg init --encryption=repokey "$BORG_REPO_LOCAL" 2>/dev/null || true
    fi
    
    # Create backup script
    cat > "$BACKUP_DIR/scripts/borg-backup.sh" << 'BORGSCRIPT'
#!/bin/bash
# Borg automated backup
set -euo pipefail

REPO="/srv/forgeos/backups/borg"
ARCHIVE="forgeos-$(date +%Y%m%d-%H%M%S)"
LOG="/var/log/forgeos/backup/borg-$(date +%Y%m%d).log"

# Source directories to backup
SOURCES=(
    "/home"
    "/etc/forgeos"
    "/var/www"
)

# Prune policy: keep 7 daily, 4 weekly, 6 monthly
borg create \
    --compression lz4 \
    --progress \
    "$REPO::$ARCHIVE" \
    "${SOURCES[@]}" \
    2>&1 | tee -a "$LOG"

borg prune \
    --prefix forgeos- \
    --keep-daily=7 \
    --keep-weekly=4 \
    --keep-monthly=6 \
    "$REPO" \
    2>&1 | tee -a "$LOG"

info "Borg backup complete"
BORGSCRIPT
    
    chmod +x "$BACKUP_DIR/scripts/borg-backup.sh"
    
    # Create systemd timer
    cat > /etc/systemd/system/forgeos-borg.timer << 'TIMER'
[Unit]
Description=ForgeOS Borg Backup Timer

[Timer]
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER

    cat > /etc/systemd/system/forgeos-borg.service << 'SERVICE'
[Unit]
Description=ForgeOS Borg Backup

[Service]
Type=oneshot
ExecStart=/srv/forgeos/scripts/borg-backup.sh
SERVICE

    systemctl daemon-reload
    # Don't enable by default - user must set Borg key first
    
    info "Borg backup configured"
}

# ============================================================
# MAIN
# ============================================================
if [[ "${FORGEOS_SKIP:-false}" != "true" ]]; then
    install_borg
    configure_borg
fi

info "Module 20 (Borg) complete"