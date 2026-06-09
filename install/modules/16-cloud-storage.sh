#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 16 - Cloud Storage
#
# RustFS   — self-hosted S3-compatible object storage (Rust).
#            Drop-in MinIO replacement; any app that talks to
#            AWS S3 works with RustFS. Apache-2.0 licensed.
#            Web console at https://console.s3.domain
#            API port 9000, Console port 9001
#            Data stored in /srv/nas/rustfs (on your RAID pool)
#
# Rclone   — already installed in module 15 (backup)
#            This module adds the SYNC workflow:
#            NAS → cloud providers (B2, S3, GCS, etc.)
#            Encrypted client-side before leaving the box.
#
# Use cases:
#   RustFS:   Replace AWS S3 for local apps (Immich, backups,
#             code repos, Docker registry). The ForgeOS web API
#             (rustfs_api.py) manages buckets/objects against it.
#   Rclone:   Offsite copy of NAS shares to cloud
#             (Backblaze B2 is cheapest: ~$6/TB/month)
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

RUSTFS_DIR="/opt/forgeos/apps/rustfs"
RUSTFS_DATA="/srv/nas/rustfs"

mkdir -p "$RUSTFS_DIR" "$RUSTFS_DATA"

# ============================================================
# RUSTFS  (S3-compatible object storage, MinIO replacement)
# ============================================================
install_rustfs() {
    step "Installing RustFS S3"

    local arch_tag
    case "$(uname -m)" in
        x86_64)  arch_tag="x86_64" ;;
        aarch64) arch_tag="aarch64" ;;
        *) die "RustFS: unsupported architecture $(uname -m)" ;;
    esac

    local rustfs_bin="/usr/local/bin/rustfs"

    if [[ ! -f "$rustfs_bin" ]]; then
        _progress "Downloading RustFS"
        local zip="/tmp/rustfs-${arch_tag}.zip"
        # musl static build = maximum compatibility, no glibc dependency.
        curl -fsSL \
            "https://dl.rustfs.com/artifacts/rustfs/release/rustfs-linux-${arch_tag}-musl-latest.zip" \
            -o "$zip" >> "$FORGENAS_LOG" 2>&1 \
            || die "RustFS download failed"
        # The zip contains the 'rustfs' binary; extract just that.
        local tmpd; tmpd=$(mktemp -d)
        unzip -o "$zip" -d "$tmpd" >> "$FORGENAS_LOG" 2>&1 || die "RustFS unzip failed"
        local found; found=$(find "$tmpd" -type f -name rustfs | head -1)
        [[ -n "$found" ]] || die "RustFS binary not found in archive"
        install -m 0755 "$found" "$rustfs_bin"
        rm -rf "$tmpd" "$zip"
        _done
    fi

    # Generate credentials (S3 access/secret keys).
    local access_key; access_key="forgeosadmin"
    local secret_key; secret_key=$(gen_password 32)
    forgenas_set "RUSTFS_ACCESS_KEY" "$access_key"
    forgenas_set "RUSTFS_SECRET_KEY" "$secret_key"
    # Keep the MINIO_* keys as aliases for one release so anything still
    # reading them (older rclone.conf, docs) doesn't break. Same values.
    forgenas_set "MINIO_ROOT_USER" "$access_key"
    forgenas_set "MINIO_ROOT_PASS" "$secret_key"

    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    # Dedicated unprivileged service user owning the data dir.
    if ! id rustfs &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin rustfs \
            >> "$FORGENAS_LOG" 2>&1 || true
    fi
    chown -R rustfs:rustfs "$RUSTFS_DATA" 2>/dev/null || true
    mkdir -p "$RUSTFS_DIR/logs"
    chown -R rustfs:rustfs "$RUSTFS_DIR" 2>/dev/null || true

    # systemd service. RustFS is configured entirely via RUSTFS_* env vars;
    # the data volume is also passed as the final positional arg.
    cat > /etc/systemd/system/forgeos-rustfs.service << SVC
[Unit]
Description=ForgeOS RustFS S3
After=network.target

[Service]
Type=simple
User=rustfs
Group=rustfs
WorkingDirectory=${RUSTFS_DATA}

Environment="RUSTFS_ACCESS_KEY=${access_key}"
Environment="RUSTFS_SECRET_KEY=${secret_key}"
Environment="RUSTFS_VOLUMES=${RUSTFS_DATA}"
Environment="RUSTFS_ADDRESS=127.0.0.1:9000"
Environment="RUSTFS_CONSOLE_ENABLE=true"
Environment="RUSTFS_CONSOLE_ADDRESS=127.0.0.1:9001"
Environment="RUSTFS_OBS_LOG_DIRECTORY=${RUSTFS_DIR}/logs"
Environment="RUST_LOG=error"

ExecStart=/usr/local/bin/rustfs ${RUSTFS_DATA}

Restart=always
RestartSec=5
StandardOutput=journal
SyslogIdentifier=rustfs

# Resource limits
LimitNOFILE=1048576
LimitNPROC=65536

[Install]
WantedBy=multi-user.target
SVC

    systemctl daemon-reload
    enable_service forgeos-rustfs

    # Wait for RustFS, then create default buckets via the S3 API.
    if wait_for_port 127.0.0.1 9000 30; then
        _create_default_buckets "$access_key" "$secret_key"
        info "RustFS: running, buckets: backups, photos, media, documents"
    else
        warn "RustFS not ready in 30s — check: journalctl -u forgeos-rustfs"
    fi

    # nginx proxy
    _configure_rustfs_nginx
}

# Create default buckets over the S3 API. RustFS ships no bundled 'mc',
# so we use boto3 from the API venv (already present after finalize) — a
# guaranteed-correct S3 client. Falls back to a warning if unavailable;
# the web UI (rustfs_api.py) can create buckets on demand regardless.
_create_default_buckets() {
    local ak="$1" sk="$2"
    local py="/opt/forgeos/venv/bin/python"
    [[ -x "$py" ]] || py="python3"

    "$py" - "$ak" "$sk" >> "$FORGENAS_LOG" 2>&1 << 'PYBUCKETS' || \
        warn "Default bucket creation deferred (create via Web UI > Storage)"
import sys
try:
    import boto3
    from botocore.client import Config
except Exception:
    sys.exit("boto3 unavailable; deferring bucket creation")
ak, sk = sys.argv[1], sys.argv[2]
s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:9000",
                  aws_access_key_id=ak, aws_secret_access_key=sk,
                  config=Config(signature_version="s3v4"), region_name="us-east-1")
for b in ("backups", "photos", "media", "documents"):
    try:
        s3.create_bucket(Bucket=b)
    except Exception as e:
        # already-exists or transient — keep going
        print(f"bucket {b}: {e}")
PYBUCKETS
}

_configure_rustfs_nginx() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    [[ ! -d /etc/nginx/forgeos.d ]] && return 0

    cat > /etc/nginx/forgeos.d/rustfs.conf << NGINX
# RustFS S3 API
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

# RustFS Console
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
        warn "nginx RustFS config — verify after cert setup"

    info "RustFS proxy: s3.${domain} (API), console.s3.${domain} (UI)"
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

    # shellcheck source=/dev/null
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

# ── RustFS (local S3 — already configured) ───────────────────
[rustfs]
type = s3
provider = Other
access_key_id = ${RUSTFS_ACCESS_KEY:-forgeosadmin}
secret_access_key = ${RUSTFS_SECRET_KEY}
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
    echo "=== RustFS S3 ==="
    systemctl is-active forgeos-rustfs &>/dev/null \
        && echo "  ✓ RustFS running" \
        || echo "  ✗ RustFS stopped"
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
rustfs-create-bucket)
    BUCKET="${1:?bucket}"
    PY="/opt/forgeos/venv/bin/python"; [[ -x "$PY" ]] || PY="python3"
    "$PY" - "$BUCKET" << 'PYMB'
import sys, boto3
from botocore.client import Config
ak=__import__("subprocess").check_output(["bash","-c","grep ^RUSTFS_ACCESS_KEY /etc/forgeos/forgeos.conf|cut -d= -f2|tr -d '\"'"]).decode().strip()
sk=__import__("subprocess").check_output(["bash","-c","grep ^RUSTFS_SECRET_KEY /etc/forgeos/forgeos.conf|cut -d= -f2|tr -d '\"'"]).decode().strip()
s3=boto3.client("s3",endpoint_url="http://127.0.0.1:9000",aws_access_key_id=ak,aws_secret_access_key=sk,config=Config(signature_version="s3v4"),region_name="us-east-1")
s3.create_bucket(Bucket=sys.argv[1]); print("Bucket created:", sys.argv[1])
PYMB
    ;;
rustfs-list)
    PY="/opt/forgeos/venv/bin/python"; [[ -x "$PY" ]] || PY="python3"
    "$PY" - << 'PYLS'
import boto3, subprocess
from botocore.client import Config
ak=subprocess.check_output(["bash","-c","grep ^RUSTFS_ACCESS_KEY /etc/forgeos/forgeos.conf|cut -d= -f2|tr -d '\"'"]).decode().strip()
sk=subprocess.check_output(["bash","-c","grep ^RUSTFS_SECRET_KEY /etc/forgeos/forgeos.conf|cut -d= -f2|tr -d '\"'"]).decode().strip()
s3=boto3.client("s3",endpoint_url="http://127.0.0.1:9000",aws_access_key_id=ak,aws_secret_access_key=sk,config=Config(signature_version="s3v4"),region_name="us-east-1")
try:
    for b in s3.list_buckets().get("Buckets",[]): print("  bucket:", b["Name"])
except Exception as e: print("RustFS not reachable:", e)
PYLS
    ;;
rustfs-credentials)
    echo "RustFS credentials:"
    echo "  API:      http://localhost:9000 (or https://s3.${DOMAIN:-nas.local})"
    echo "  Console:  https://console.s3.${DOMAIN:-nas.local}"
    echo "  Access:   ${RUSTFS_ACCESS_KEY:-forgeosadmin}"
    echo "  Secret:   ${RUSTFS_SECRET_KEY:-<check forgeos.conf>}"
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
    echo "RustFS (local S3):"
    echo "  status                     RustFS + cloud status"
    echo "  rustfs-credentials         Show access credentials"
    echo "  rustfs-list                List buckets"
    echo "  rustfs-create-bucket <n>   Create bucket"
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
install_rustfs
configure_rclone_cloud
install_cloud_cli

forgenas_set "MODULE_CLOUD_DONE" "yes"
forgenas_set "FEATURE_CLOUD"     "yes"

# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"
info "Cloud storage module complete"
info "  RustFS S3:      https://s3.${DOMAIN:-nas.local}"
info "  RustFS Console: https://console.s3.${DOMAIN:-nas.local}"
info "  Credentials:    forgeos-cloud rustfs-credentials"
info "  Add B2 cloud:   forgeos-cloud add-b2"
info "  Cloud sync:     forgeos-cloud sync"
warn "  Encryption keys in /etc/forgeos/forgeos.conf — back this up."
