#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 16 - Cloud Storage
#
# MinIO    — self-hosted S3-compatible object storage
#            Any app that talks to AWS S3 works with MinIO.
#            Web console at https://s3.domain
#            API port 9000, Console port 9001
#            Data stored in /srv/nas/minio (on your RAID pool)
#
# Rclone   — already installed in module 15 (backup)
#            This module adds the SYNC workflow:
#            NAS → cloud providers (B2, S3, GCS, etc.)
#            Encrypted client-side before leaving the box.
#
# Use cases:
#   MinIO:    Replace AWS S3 for local apps (Immich, backups,
#             code repos, Docker registry)
#   Rclone:   Offsite copy of NAS shares to cloud
#             (Backblaze B2 is cheapest: ~$6/TB/month)
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

MINIO_DIR="/opt/forgeos/apps/minio"
MINIO_DATA="/srv/nas/minio"

mkdir -p "$MINIO_DIR" "$MINIO_DATA"

# ============================================================
# MINIO
# ============================================================
install_minio() {
    step "Installing MinIO S3"

    local arch; arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
    local minio_bin="/usr/local/bin/minio"

    if [[ ! -f "$minio_bin" ]]; then
        _progress "Downloading MinIO"
        curl -fsSL "https://dl.min.io/server/minio/release/linux-${arch}/minio" \
            -o "$minio_bin" >> "$FORGENAS_LOG" 2>&1 \
            || die "MinIO download failed"
        chmod +x "$minio_bin"
        _done
    fi

    # mc (MinIO client)
    if ! command -v mc &>/dev/null; then
        curl -fsSL "https://dl.min.io/client/mc/release/linux-${arch}/mc" \
            -o /usr/local/bin/mc >> "$FORGENAS_LOG" 2>&1 || warn "mc client download failed"
        chmod +x /usr/local/bin/mc 2>/dev/null || true
    fi

    # Generate credentials
    local root_user; root_user="minioadmin"
    local root_pass; root_pass=$(gen_password 24)
    forgenas_set "MINIO_ROOT_USER" "$root_user"
    forgenas_set "MINIO_ROOT_PASS" "$root_pass"

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    # systemd service
    cat > /etc/systemd/system/forgeos-minio.service << SVC
[Unit]
Description=ForgeOS MinIO S3
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${MINIO_DATA}

Environment="MINIO_ROOT_USER=${root_user}"
Environment="MINIO_ROOT_PASSWORD=${root_pass}"
Environment="MINIO_VOLUMES=${MINIO_DATA}"
Environment="MINIO_SITE_NAME=ForgeOS"
Environment="MINIO_DOMAIN=s3.${domain}"
Environment="MINIO_BROWSER_REDIRECT_URL=https://s3.${domain}"

ExecStart=/usr/local/bin/minio server \
    --address 127.0.0.1:9000 \
    --console-address 127.0.0.1:9001 \
    ${MINIO_DATA}

Restart=always
RestartSec=5
StandardOutput=journal
SyslogIdentifier=minio

# Resource limits
LimitNOFILE=1048576
LimitNPROC=65536

[Install]
WantedBy=multi-user.target
SVC

    systemctl daemon-reload
    enable_service forgeos-minio

    # Wait for MinIO to start
    if wait_for_port 127.0.0.1 9000 30; then
        # Configure mc client
        mc alias set forgeos "http://127.0.0.1:9000" "$root_user" "$root_pass" \
            >> "$FORGENAS_LOG" 2>&1 || true

        # Create default buckets
        for bucket in backups photos media documents; do
            mc mb "forgeos/${bucket}" >> "$FORGENAS_LOG" 2>&1 || true
        done

        # Set lifecycle policy on backups bucket (delete after 90 days)
        mc ilm add --expiry-days 90 "forgeos/backups" >> "$FORGENAS_LOG" 2>&1 || true

        info "MinIO: running, buckets: backups, photos, media, documents"
    else
        warn "MinIO not ready in 30s — check: journalctl -u forgeos-minio"
    fi

    # nginx proxy
    _configure_minio_nginx
}

_configure_minio_nginx() {
    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    [[ ! -d /etc/nginx/forgeos.d ]] && return 0

    cat > /etc/nginx/forgeos.d/minio.conf << NGINX
# MinIO S3 API
server {
    listen 443 ssl http2;
    server_name s3.${domain} *.s3.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    ignore_invalid_headers off;
    client_max_body_size   0;
    proxy_buffering        off;
    proxy_request_buffering off;

    location / {
        proxy_pass              http://127.0.0.1:9000;
        proxy_set_header        Host \$http_host;
        proxy_set_header        X-Real-IP \$remote_addr;
        proxy_set_header        X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header        X-Forwarded-Proto \$scheme;
        proxy_connect_timeout   300s;
        proxy_send_timeout      300s;
        proxy_read_timeout      300s;
        proxy_http_version      1.1;
        proxy_set_header        Connection "";
        chunked_transfer_encoding on;
    }
}

# MinIO Console
server {
    listen 443 ssl http2;
    server_name console.s3.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    location / {
        proxy_pass              http://127.0.0.1:9001;
        proxy_set_header        Host \$http_host;
        proxy_set_header        X-Real-IP \$remote_addr;
        proxy_set_header        X-Forwarded-Proto \$scheme;
        proxy_http_version      1.1;
        proxy_set_header        Upgrade \$http_upgrade;
        proxy_set_header        Connection "upgrade";
    }
}
NGINX

    nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || \
        warn "nginx MinIO config — verify after cert setup"

    info "MinIO proxy: s3.${domain} (API), console.s3.${domain} (UI)"
}

# ============================================================
# RCLONE CLOUD SYNC SETUP
# Module 15 installed rclone. This module adds:
#   - B2/S3/GCS provider wizard output
#   - Encrypted crypt remote templates
#   - Sync targets for /srv/nas → cloud
#   - forgeos-cloud CLI
# ============================================================
configure_rclone_cloud() {
    step "Configuring Rclone cloud sync"

    # Rclone should already be installed by module 15
    command -v rclone &>/dev/null || {
        curl -sf https://rclone.org/install.sh | bash >> "$FORGENAS_LOG" 2>&1 || \
        apt_install rclone
    }

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    # Generate crypt passwords for cloud encryption
    local crypt_pass; crypt_pass=$(gen_password 32)
    local crypt_salt; crypt_salt=$(gen_password 32)
    forgenas_set "RCLONE_CRYPT_PASS" "$crypt_pass"
    forgenas_set "RCLONE_CRYPT_SALT" "$crypt_salt"

    # Obscure passwords for rclone config
    local obs_pass; obs_pass=$(rclone obscure "$crypt_pass" 2>/dev/null || echo "$crypt_pass")
    local obs_salt; obs_salt=$(rclone obscure "$crypt_salt" 2>/dev/null || echo "$crypt_salt")

    cat > /etc/forgeos/rclone/rclone.conf << RCLONECONF
# ForgeOS Rclone Configuration
# Edit via: Web UI > Storage > Cloud Sync
# Or:       rclone config

# ── MinIO (local S3 — already configured) ────────────────────
[minio]
type = s3
provider = Minio
access_key_id = ${MINIO_ROOT_USER:-minioadmin}
secret_access_key = ${MINIO_ROOT_PASS}
endpoint = http://127.0.0.1:9000
location_constraint =
server_side_encryption =

# ── Backblaze B2 template ─────────────────────────────────────
# Uncomment and fill in your B2 credentials:
# [b2]
# type = b2
# account = YOUR_ACCOUNT_ID
# key = YOUR_APPLICATION_KEY
#
# [b2-crypt]
# type = crypt
# remote = b2:YOUR-BUCKET/forgeos
# filename_encryption = standard
# directory_name_encryption = true
# password = ${obs_pass}
# password2 = ${obs_salt}

# ── AWS S3 template ──────────────────────────────────────────
# [s3]
# type = s3
# provider = AWS
# access_key_id = YOUR_KEY_ID
# secret_access_key = YOUR_SECRET
# region = us-east-1
#
# [s3-crypt]
# type = crypt
# remote = s3:YOUR-BUCKET/forgeos
# filename_encryption = standard
# directory_name_encryption = true
# password = ${obs_pass}
# password2 = ${obs_salt}

# ── Cloudflare R2 template ──────────────────────────────────
# [r2]
# type = s3
# provider = Cloudflare
# access_key_id = YOUR_R2_ACCESS_KEY
# secret_access_key = YOUR_R2_SECRET
# endpoint = https://ACCOUNT_ID.r2.cloudflarestorage.com
#
# [r2-crypt]
# type = crypt
# remote = r2:YOUR-BUCKET/forgeos
# filename_encryption = standard
# directory_name_encryption = true
# password = ${obs_pass}
# password2 = ${obs_salt}

# ── SFTP/SSH remote ─────────────────────────────────────────
# [sftp]
# type = sftp
# host = backup.example.com
# user = backup
# key_file = /etc/forgeos/backup/ssh/backup_key
RCLONECONF

    chmod 600 /etc/forgeos/rclone/rclone.conf
    info "Rclone config: /etc/forgeos/rclone/rclone.conf"
    info "  Encryption keys saved to forgeos.conf (back up /etc/forgeos)"
    info "  Uncomment a provider section and run: forgeos-cloud test"
}

# ============================================================
# CLOUD CLI
# ============================================================
install_cloud_cli() {
    step "Installing forgeos-cloud CLI"

    cat > /usr/local/bin/forgeos-cloud << 'CLOUDCLI'
#!/usr/bin/env bash
# ForgeOS Cloud Storage Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true
RCONF="/etc/forgeos/rclone/rclone.conf"

case "$CMD" in
status)
    echo "=== MinIO S3 ==="
    systemctl is-active forgeos-minio &>/dev/null \
        && echo "  ✓ MinIO running" \
        || echo "  ✗ MinIO stopped"
    mc ls forgeos 2>/dev/null | awk '{printf "  bucket: %s (%s)\n", $5, $4}' || true
    echo ""
    echo "=== Cloud Remotes ==="
    rclone --config "$RCONF" listremotes 2>/dev/null | while read r; do
        echo "  $r"
    done
    ;;
test)
    echo "Testing cloud remotes..."
    rclone --config "$RCONF" listremotes 2>/dev/null | grep crypt | while read r; do
        echo -n "  Testing $r ... "
        rclone --config "$RCONF" ls "$r" --max-depth 1 &>/dev/null \
            && echo "OK" || echo "FAILED (check credentials)"
    done
    ;;
sync)
    remote="${1:-}"
    [[ -z "$remote" ]] && {
        remotes=$(rclone --config "$RCONF" listremotes | grep crypt)
        [[ -z "$remotes" ]] && { echo "No crypt remotes configured. Edit $RCONF"; exit 1; }
        remote=$(echo "$remotes" | head -1)
    }
    echo "Syncing /srv/nas → $remote"
    rclone sync /srv/nas "${remote}nas" \
        --config "$RCONF" \
        --exclude '/timemachine/**' \
        --transfers 4 --checkers 8 \
        --stats 60s --log-level INFO \
        --progress \
        --backup-dir "${remote}nas-deleted-$(date +%Y%m)"
    ;;
mount)
    remote="${1:?remote}" mountpoint="${2:?mountpoint}"
    mkdir -p "$mountpoint"
    rclone mount "$remote" "$mountpoint" \
        --config "$RCONF" \
        --vfs-cache-mode writes \
        --vfs-cache-max-size 5G \
        --daemon
    echo "Mounted $remote → $mountpoint"
    ;;
minio-create-bucket)
    mc mb "forgeos/${1:?bucket}" && echo "Bucket created: $1"
    ;;
minio-list)
    mc ls forgeos 2>/dev/null || echo "MinIO not running"
    ;;
minio-credentials)
    echo "MinIO credentials:"
    echo "  API:      http://localhost:9000 (or https://s3.${DOMAIN:-nas.local})"
    echo "  Console:  https://console.s3.${DOMAIN:-nas.local}"
    echo "  User:     ${MINIO_ROOT_USER:-minioadmin}"
    echo "  Password: ${MINIO_ROOT_PASS:-<check forgeos.conf>}"
    echo ""
    echo "  Connect with AWS CLI:"
    echo "    aws --endpoint-url http://localhost:9000 s3 ls"
    ;;
add-b2)
    echo "=== Add Backblaze B2 ==="
    read -rp "  B2 Account ID:  " account
    read -rp "  B2 App Key:     " appkey
    read -rp "  B2 Bucket name: " bucket
    local obs_pass; obs_pass=$(rclone obscure "${RCLONE_CRYPT_PASS}" 2>/dev/null)
    local obs_salt; obs_salt=$(rclone obscure "${RCLONE_CRYPT_SALT}" 2>/dev/null)
    cat >> "$RCONF" << B2CONF

[b2]
type = b2
account = ${account}
key = ${appkey}

[b2-crypt]
type = crypt
remote = b2:${bucket}/forgeos
filename_encryption = standard
directory_name_encryption = true
password = ${obs_pass}
password2 = ${obs_salt}
B2CONF
    echo "  B2 remote added. Test with: forgeos-cloud test"
    ;;
help|*)
    echo "ForgeOS Cloud Storage Manager"
    echo ""
    echo "MinIO (local S3):"
    echo "  status              MinIO + cloud status"
    echo "  minio-credentials   Show access credentials"
    echo "  minio-list          List buckets"
    echo "  minio-create-bucket <n>  Create bucket"
    echo ""
    echo "Cloud sync (rclone):"
    echo "  test                Test all configured remotes"
    echo "  sync [remote]       Sync NAS → cloud (encrypted)"
    echo "  mount <remote> <mountpoint>  Mount cloud as filesystem"
    echo ""
    echo "Setup wizards:"
    echo "  add-b2              Interactive Backblaze B2 setup"
    echo "  (For S3/R2/GCS: edit /etc/forgeos/rclone/rclone.conf)"
    ;;
esac
CLOUDCLI
    chmod +x /usr/local/bin/forgeos-cloud
}

# ============================================================
# MAIN
# ============================================================
install_minio
configure_rclone_cloud
install_cloud_cli

forgenas_set "MODULE_CLOUD_DONE" "yes"
forgenas_set "FEATURE_CLOUD"     "yes"

source "$FORGENAS_CONFIG"
info "Cloud storage module complete"
info "  MinIO S3:      https://s3.${DOMAIN:-nas.local}"
info "  MinIO Console: https://console.s3.${DOMAIN:-nas.local}"
info "  Credentials:   forgeos-cloud minio-credentials"
info "  Add B2 cloud:  forgeos-cloud add-b2"
info "  Cloud sync:    forgeos-cloud sync"
warn "  Encryption keys in /etc/forgeos/forgeos.conf — back this up."
