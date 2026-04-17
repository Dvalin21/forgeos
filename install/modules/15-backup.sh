#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 15 - Backup
#
# Three complementary backup layers:
#
#   Layer 1 — btrfs Snapshots (Snapper)
#     Local. Instant. Near-zero space cost (copy-on-write).
#     Can restore individual files in seconds.
#     NOT a replacement for offsite backup.
#     Schedule: hourly + daily + weekly
#
#   Layer 2 — Restic (encrypted local + offsite)
#     Client-side AES-256-CTR encryption BEFORE leaving the box.
#     Stores to: local disk, external drive, AND cloud (B2/S3/GCS/SFTP)
#     Deduplication: only new chunks are uploaded.
#     Schedule: nightly at 02:00 + random delay
#     Retention: 7 daily, 4 weekly, 12 monthly, 2 yearly
#
#   Layer 3 — Rclone (raw cloud sync for media/shares)
#     For bulk media sync where the full file is needed in cloud.
#     Uses rclone crypt backend: AES-256-CTR + HMAC-SHA512
#     encrypted filenames so cloud provider sees gibberish.
#     Schedule: nightly at 04:30 + random delay
#
# Philosophy:
#   3-2-1 rule: 3 copies, 2 different media, 1 offsite.
#   Snapper + Restic local = copies 1+2
#   Restic/Rclone cloud    = copy 3 (offsite)
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

BACKUP_DIR="/opt/forgeos/backup"
BACKUP_LOG_DIR="/var/log/forgeos/backup"
RESTIC_REPO_LOCAL="/srv/forgeos/backups/restic"
RESTIC_KEY_DIR="/etc/forgeos/backup/keys"
RCLONE_CONF="/etc/forgeos/rclone/rclone.conf"

mkdir -p "$BACKUP_DIR"/{scripts,logs} "$BACKUP_LOG_DIR" "$RESTIC_KEY_DIR" \
         "$(dirname "$RCLONE_CONF")" "$RESTIC_REPO_LOCAL"

chmod 700 "$RESTIC_KEY_DIR"

# ============================================================
# RESTIC
# ============================================================
install_restic() {
    step "Installing Restic"

    # Use latest binary from GitHub (distro packages often outdated)
    local arch; arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
    local ver
    ver=$(curl -sf https://api.github.com/repos/restic/restic/releases/latest \
          | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))" 2>/dev/null \
          || echo "0.16.4")

    _progress "Downloading restic ${ver}"
    curl -sfL \
        "https://github.com/restic/restic/releases/download/v${ver}/restic_${ver}_linux_${arch}.bz2" \
        | bunzip2 > /usr/local/bin/restic \
        && chmod +x /usr/local/bin/restic \
        || { apt_install restic; }  # fallback to apt
    _done

    info "Restic $(restic version 2>/dev/null | head -1)"
}

configure_restic() {
    step "Configuring Restic backup"

    # Generate master key (AES-256) — user can add cloud repos via Web UI
    local master_key; master_key=$(gen_password 32)
    echo "$master_key" > "${RESTIC_KEY_DIR}/master.key"
    chmod 400 "${RESTIC_KEY_DIR}/master.key"
    forgenas_set "RESTIC_KEY_FILE" "${RESTIC_KEY_DIR}/master.key"

    # Initialize local repository
    RESTIC_PASSWORD_FILE="${RESTIC_KEY_DIR}/master.key" \
        restic init --repo "$RESTIC_REPO_LOCAL" >> "$FORGENAS_LOG" 2>&1 \
        || warn "Restic local repo already initialized or failed"

    forgenas_set "RESTIC_REPO_LOCAL" "$RESTIC_REPO_LOCAL"

    # Write restic backup script
    cat > "$BACKUP_DIR/scripts/restic-backup.sh" << 'RESTICSCRIPT'
#!/usr/bin/env bash
# ForgeOS Restic Backup Runner
source /etc/forgeos/forgeos.conf

LOG="/var/log/forgeos/backup/restic-$(date +%Y%m%d).log"
START=$(date +%s)

export RESTIC_PASSWORD_FILE="${RESTIC_KEY_FILE:-/etc/forgeos/backup/keys/master.key}"

notify() {
    forgeos-notify "${1}" "Backup: ${2}" "${3}" 2>/dev/null || true
}

run_backup() {
    local repo="$1" label="$2"
    echo "=== Restic backup: $label $(date) ===" | tee -a "$LOG"

    # Backup all configured paths
    restic backup \
        --repo "$repo" \
        --tag forgeos \
        --tag "$(date +%Y-%m-%d)" \
        --exclude-caches \
        --exclude '/srv/nas/*/timemachine/**' \
        --exclude '/srv/nas/*/media/Movies/**' \
        --exclude '/proc/**' \
        --exclude '/sys/**' \
        --exclude '/dev/**' \
        --exclude '/run/**' \
        --exclude '/tmp/**' \
        --exclude '*.tmp' \
        --exclude '*.log' \
        /etc/forgeos \
        /srv/nas \
        /opt/forgeos \
        2>&1 | tee -a "$LOG"

    # Prune old backups (3-2-1 retention)
    restic forget \
        --repo "$repo" \
        --keep-daily   7 \
        --keep-weekly  4 \
        --keep-monthly 12 \
        --keep-yearly  2 \
        --prune \
        2>&1 | tee -a "$LOG"

    # Check repo integrity (every 7th day)
    if [[ $(( $(date +%d) % 7 )) -eq 0 ]]; then
        restic check --repo "$repo" 2>&1 | tee -a "$LOG"
    fi
}

# Backup to local repo
run_backup "$RESTIC_REPO_LOCAL" "local"
local_exit=$?

# Backup to cloud repos (if configured)
for repo_var in RESTIC_REPO_B2 RESTIC_REPO_S3 RESTIC_REPO_SFTP RESTIC_REPO_RCLONE; do
    repo="${!repo_var:-}"
    [[ -z "$repo" ]] && continue
    run_backup "$repo" "$repo_var"
done

ELAPSED=$(( $(date +%s) - START ))
SIZE=$(restic --repo "$RESTIC_REPO_LOCAL" stats --mode raw-data --json 2>/dev/null \
       | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('total_size',0)/1e9:.1f}GB\")" 2>/dev/null || echo "?")

if [[ $local_exit -eq 0 ]]; then
    notify "info" "Complete" "Backup finished in ${ELAPSED}s. Repo size: ${SIZE}"
else
    notify "warning" "Errors" "Backup completed with errors. Check $LOG"
fi
RESTICSCRIPT
    chmod +x "$BACKUP_DIR/scripts/restic-backup.sh"
}

# ============================================================
# RCLONE
# ============================================================
install_rclone() {
    step "Installing Rclone"

    if ! command -v rclone &>/dev/null; then
        curl -sf https://rclone.org/install.sh | bash >> "$FORGENAS_LOG" 2>&1 \
            || apt_install rclone
    fi

    info "Rclone $(rclone --version 2>/dev/null | head -1)"
}

configure_rclone() {
    step "Configuring Rclone encrypted sync"

    # Template config — user fills in credentials via Web UI
    [[ -f "$RCLONE_CONF" ]] || cat > "$RCLONE_CONF" << 'RCLONECONF'
# ForgeOS Rclone Configuration
# Configure cloud providers via Web UI > Backup > Cloud Sync
# Or run: rclone config
#
# ForgeOS uses a "crypt" remote layered over any cloud remote.
# This means ALL data is encrypted client-side BEFORE upload.
# The cloud provider (B2, S3, GCS, etc.) never sees plaintext.
# Encryption: AES-256-CTR, authenticated with HMAC-SHA512.
# Filenames are also encrypted — provider sees random strings.

# Example Backblaze B2 setup:
# [b2]
# type = b2
# account = YOUR_ACCOUNT_ID
# key = YOUR_APPLICATION_KEY
#
# [b2-crypt]
# type = crypt
# remote = b2:your-bucket-name/forgeos
# filename_encryption = standard
# directory_name_encryption = true
# password = YOUR_RCLONE_CRYPT_PASSWORD
# password2 = YOUR_RCLONE_CRYPT_SALT

# Example AWS S3:
# [s3]
# type = s3
# provider = AWS
# access_key_id = YOUR_KEY
# secret_access_key = YOUR_SECRET
# region = us-east-1
#
# [s3-crypt]
# type = crypt
# remote = s3:your-bucket/forgeos
# filename_encryption = standard
# directory_name_encryption = true
# password = YOUR_CRYPT_PASSWORD
# password2 = YOUR_CRYPT_SALT
RCLONECONF

    chmod 600 "$RCLONE_CONF"

    # Rclone sync script
    cat > "$BACKUP_DIR/scripts/rclone-sync.sh" << 'RCLONESCRIPT'
#!/usr/bin/env bash
# ForgeOS Rclone Cloud Sync
source /etc/forgeos/forgeos.conf

LOG="/var/log/forgeos/backup/rclone-$(date +%Y%m%d).log"
CONF="/etc/forgeos/rclone/rclone.conf"

notify() { forgeos-notify "${1}" "Cloud Sync: ${2}" "${3}" 2>/dev/null || true; }

# Check if any crypt remote is configured
if ! rclone --config "$CONF" listremotes 2>/dev/null | grep -q "crypt"; then
    echo "No rclone crypt remote configured — skipping cloud sync"
    echo "Configure via Web UI > Backup > Cloud Sync"
    exit 0
fi

echo "=== Rclone sync $(date) ===" | tee -a "$LOG"
START=$(date +%s)

# Sync each configured crypt remote
for remote in $(rclone --config "$CONF" listremotes | grep "crypt"); do
    echo "--- Syncing to $remote ---" | tee -a "$LOG"
    rclone sync \
        --config "$CONF" \
        /srv/nas \
        "${remote%:}/nas" \
        --exclude '/timemachine/**' \
        --fast-list \
        --transfers 4 \
        --checkers 8 \
        --stats 60s \
        --log-level INFO \
        --log-file "$LOG" \
        --backup-dir "${remote%:}/nas-deleted-$(date +%Y%m)" \
        2>&1 | tee -a "$LOG"
done

ELAPSED=$(( $(date +%s) - START ))
notify "info" "Complete" "Cloud sync finished in ${ELAPSED}s"
RCLONESCRIPT
    chmod +x "$BACKUP_DIR/scripts/rclone-sync.sh"
}

# ============================================================
# SYSTEMD TIMERS
# ============================================================
install_timers() {
    step "Installing backup timers"

    # Restic backup — nightly 02:00 + up to 1h random delay
    cat > /etc/systemd/system/forgeos-backup-restic.service << SVC
[Unit]
Description=ForgeOS Restic Encrypted Backup
After=network.target

[Service]
Type=oneshot
ExecStart=${BACKUP_DIR}/scripts/restic-backup.sh
Nice=15
IOSchedulingClass=idle
StandardOutput=journal
SyslogIdentifier=forgeos-backup
SVC

    cat > /etc/systemd/system/forgeos-backup-restic.timer << TIMER
[Unit]
Description=ForgeOS Restic Backup Timer
[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
TIMER

    # Rclone cloud sync — nightly 04:30 + random delay
    cat > /etc/systemd/system/forgeos-backup-rclone.service << SVC
[Unit]
Description=ForgeOS Rclone Cloud Sync
After=network.target

[Service]
Type=oneshot
ExecStart=${BACKUP_DIR}/scripts/rclone-sync.sh
Nice=15
IOSchedulingClass=idle
StandardOutput=journal
SyslogIdentifier=forgeos-rclone
SVC

    cat > /etc/systemd/system/forgeos-backup-rclone.timer << TIMER
[Unit]
Description=ForgeOS Rclone Cloud Sync Timer
[Timer]
OnCalendar=*-*-* 04:30:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
TIMER

    systemctl daemon-reload
    systemctl enable forgeos-backup-restic.timer
    systemctl enable forgeos-backup-rclone.timer

    info "Timers: Restic nightly 02:00, Rclone sync 04:30"
}

# ============================================================
# BACKUP CLI
# ============================================================
create_backup_cli() {
    step "Installing forgeos-backup CLI"

    cat > /usr/local/bin/forgeos-backup << 'BACKCLI'
#!/usr/bin/env bash
# ForgeOS Backup Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
export RESTIC_PASSWORD_FILE="${RESTIC_KEY_FILE:-/etc/forgeos/backup/keys/master.key}"
CMD="${1:-help}"; shift || true

case "$CMD" in
run)
    echo "Starting Restic backup now..."
    /opt/forgeos/backup/scripts/restic-backup.sh
    ;;
sync)
    echo "Starting Rclone cloud sync now..."
    /opt/forgeos/backup/scripts/rclone-sync.sh
    ;;
status)
    echo "=== Restic Snapshots (local) ==="
    restic --repo "$RESTIC_REPO_LOCAL" snapshots --compact 2>/dev/null | tail -20
    echo ""
    echo "=== Timer Status ==="
    systemctl status forgeos-backup-restic.timer --no-pager -l | head -8
    systemctl status forgeos-backup-rclone.timer --no-pager -l | head -8
    ;;
restore)
    # Args: <snapshot_id_or_latest> <path> [target_dir]
    local snap="${1:-latest}" path="${2:-/}" target="${3:-/tmp/forgeos-restore}"
    echo "Restoring snapshot $snap: $path → $target"
    restic --repo "$RESTIC_REPO_LOCAL" restore "$snap" --target "$target" --include "$path"
    echo "Restored to: $target"
    ;;
check)
    echo "Checking Restic repository integrity..."
    restic --repo "$RESTIC_REPO_LOCAL" check
    ;;
stats)
    restic --repo "$RESTIC_REPO_LOCAL" stats --mode restore-size
    ;;
key-show)
    echo "Master key file: $RESTIC_KEY_FILE"
    echo "WARNING: Keep this safe — data is unrecoverable without it."
    ;;
add-cloud)
    # Interactive: add a cloud backend
    echo "=== Add Cloud Backup Backend ==="
    echo "1. Backblaze B2"
    echo "2. AWS S3"
    echo "3. Cloudflare R2"
    echo "4. SFTP server"
    echo "5. Any rclone remote (advanced)"
    echo ""
    echo "Run 'rclone config' to set up the remote, then:"
    echo "  forgeos-backup add-cloud-manual <restic_repo_url>"
    ;;
help|*)
    echo "ForgeOS Backup Manager"
    echo "  run           Run Restic backup now"
    echo "  sync          Run Rclone cloud sync now"
    echo "  status        Backup status + timers"
    echo "  restore <snap> <path> [target]  Restore from snapshot"
    echo "  check         Verify repository integrity"
    echo "  stats         Repository storage statistics"
    echo "  key-show      Show encryption key location"
    echo "  add-cloud     Add a cloud backup backend"
    ;;
esac
BACKCLI
    chmod +x /usr/local/bin/forgeos-backup
}

# ============================================================
# MAIN
# ============================================================
install_restic
configure_restic
install_rclone
configure_rclone
install_timers
create_backup_cli

forgenas_set "FEATURE_BACKUP" "yes"
forgenas_set "BACKUP_RESTIC_LOCAL" "$RESTIC_REPO_LOCAL"

info "Backup module complete"
info "  Restic key:    ${RESTIC_KEY_DIR}/master.key  ← BACK THIS UP"
info "  Manual backup: forgeos-backup run"
info "  Cloud sync:    forgeos-backup sync"
info "  Status:        forgeos-backup status"
info "  Cloud config:  Web UI > Backup > Cloud Sync"
warn "  IMPORTANT: Copy the Restic master key to a safe offline location."
warn "  Without it, encrypted backups cannot be restored."
