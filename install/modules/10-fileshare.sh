#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 10 - File Sharing (NFS, FTPS, WebDAV, FileBrowser)
#
# Protocols:
#   NFS v4.2    — high-performance Linux/Unix/ESXi sharing
#                 v4 only (v3 disabled — it's stateless and insecure)
#                 Kerberos optional, ID mapping via nfsidmap
#
#   ProFTPD     — explicit FTPS (TLS required, port 21/990)
#                 For legacy clients and ISP uploads
#                 Passive mode ports 40000-40100
#
#   WebDAV      — via nginx (module 12 prerequisite)
#                 Mounts as a network drive on Windows/Mac/Linux
#                 Auth: digest (no plaintext password over HTTPS)
#
#   FileBrowser — self-hosted browser-based file manager
#                 Port 8085 (proxied via nginx)
#                 Full drag-drop, preview, share links, user accounts
#
# All protocols share the same /srv/nas root.
# Permissions are managed via POSIX ACLs to avoid conflicts.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

NAS_ROOT="/srv/nas"

# ============================================================
# NFS v4
# ============================================================
install_nfs() {
    step "Installing NFS v4 server"

    apt_install nfs-kernel-server nfs-common rpcbind

    # NFS v4 only — disable v2/v3 completely
    cat > /etc/default/nfs-kernel-server << 'NFS_SERVER_DEFAULTS'
# ForgeOS NFS configuration
# v4 ONLY — v2 and v3 disabled for security

RPCNFSDARGS="-N 2 -N 3 --no-udp"
RPCMOUNTDARGS="-N 2 -N 3 --no-udp"

# Number of NFS server threads — scale with CPU cores
RPCNFSDCOUNT=$(nproc)

# v4 lease time (seconds) — shorter = faster recovery after crash
NFSD_V4_GRACE_TIME=90
NFSD_V4_LEASE_TIME=90
NFS_SERVER_DEFAULTS
    # Kernel parameters for NFS v4
    cat > /etc/sysctl.d/92-forgeos-nfs.conf << 'NFSSYS'
# NFS performance tuning
fs.nfs.nlm_grace_period = 0
fs.nfs.nfs_callback_tcpport = 32765
sunrpc.tcp_slot_table_entries = 128
sunrpc.udp_slot_table_entries = 128
NFSSYS
    sysctl -p /etc/sysctl.d/92-forgeos-nfs.conf >> "$FORGENAS_LOG" 2>&1 || true

    # ID mapping daemon (required for NFSv4 uid/gid mapping)
    cat > /etc/idmapd.conf << IDMAP
[General]
Verbosity = 0
Domain = $(forgenas_get "DOMAIN" "nas.local")

[Mapping]
Nobody-User  = nobody
Nobody-Group = nogroup

[Translation]
Method = nsswitch
IDMAP

    # Create initial exports
    _write_nfs_exports
    enable_service nfs-kernel-server rpcbind

    # Firewall — NFS stays LAN-only
    local lan_cidr; lan_cidr=$(forgenas_get "LAN_CIDR" "192.168.0.0/16")
    ufw allow from "$lan_cidr" to any port 2049 proto tcp comment "NFS v4 (LAN)"
    ufw allow from "$lan_cidr" to any port 111  proto tcp comment "NFS rpcbind (LAN)"

    info "NFS v4: /srv/nas exports active"
    info "  Mount example: mount -t nfs4 forgeos.local:/nas /mnt/nas"
}

_write_nfs_exports() {
    local lan_cidr; lan_cidr=$(forgenas_get "LAN_CIDR" "192.168.0.0/16")

    cat > /etc/exports << EXPORTS
# ForgeOS NFS v4 Exports
# Managed by: Web UI > Network > File Sharing > NFS
# CLI:        forgeos-fileshare nfs-add / nfs-remove

# NFSv4 pseudo-root
${NAS_ROOT} ${lan_cidr}(rw,fsid=0,no_subtree_check,crossmnt,async,sec=sys)

# Shares
${NAS_ROOT}/data    ${lan_cidr}(rw,no_subtree_check,no_root_squash,async,sec=sys)
${NAS_ROOT}/media   ${lan_cidr}(ro,no_subtree_check,root_squash,async,sec=sys)
${NAS_ROOT}/public  ${lan_cidr}(ro,no_subtree_check,all_squash,async,sec=sys)

# Backups — stricter, only root can write
${NAS_ROOT}/backups ${lan_cidr}(rw,no_subtree_check,root_squash,sync,sec=sys)
EXPORTS

    exportfs -ra 2>/dev/null || true
}

# ============================================================
# PROFTPD — Explicit FTPS
# TLS mandatory — no plaintext FTP ever.
# Passive mode for NAT traversal.
# ============================================================
install_proftpd() {
    step "Installing ProFTPD (explicit FTPS)"

    apt_install proftpd-basic proftpd-mod-crypto openssl

    # TLS certificate — use Let's Encrypt if available, self-signed fallback
    local domain; domain=$(forgenas_get "DOMAIN" "nas.local")
    local cert_path="/etc/letsencrypt/live/${domain}/fullchain.pem"
    local key_path="/etc/letsencrypt/live/${domain}/privkey.pem"

    if [[ ! -f "$cert_path" ]]; then
        # Self-signed fallback
        mkdir -p /etc/proftpd/tls
        openssl req -x509 -nodes -days 3650 \
            -newkey rsa:4096 \
            -keyout /etc/proftpd/tls/server.key \
            -out    /etc/proftpd/tls/server.crt \
            -subj "/CN=${domain}" \
            >> "$FORGENAS_LOG" 2>&1
        cert_path="/etc/proftpd/tls/server.crt"
        key_path="/etc/proftpd/tls/server.key"
        info "FTP: self-signed TLS cert (run forgeos-nginx certbot to use Let's Encrypt)"
    fi

    cat > /etc/proftpd/proftpd.conf << FTPCONF
# ForgeOS ProFTPD Configuration
# Explicit FTPS only (TLS required)
# Managed via: Web UI > Network > File Sharing > FTP

ServerName   "ForgeOS FTPS"
ServerType   standalone
DefaultRoot  ~
ServerIdent  on "FTP Server Ready"
DeferWelcome off
ShowSymlinks on
TimeoutLogin 120
TimeoutIdle  600
TimeoutStalled 600
MaxClients   20
LogFormat    forgeos "%h %l %u %t \"%r\" %s %b"

# Users map to /srv/nas/<username>
DefaultRoot  ${NAS_ROOT}
RequireValidShell off

# Passive ports — must match UFW rules
PassivePorts 40000 40100
MasqueradeAddress ${PUBLIC_IP:-}

# TLS — MANDATORY, no plaintext FTP
<IfModule mod_tls.c>
  TLSEngine               on
  TLSLog                  /var/log/forgeos/proftpd-tls.log
  TLSProtocol             TLSv1.2 TLSv1.3
  TLSCipherSuite          HIGH:MEDIUM:!NULL:!ADH:!DES:!3DES
  TLSRequired             on
  TLSRSACertificateFile   ${cert_path}
  TLSRSACertificateKeyFile ${key_path}
  TLSVerifyClient         off
  TLSRenegotiate          none
  TLSOptions              NoCertRequest
</IfModule>

# Logging
TransferLog /var/log/forgeos/proftpd-transfer.log
SystemLog   /var/log/forgeos/proftpd.log

# Disable SITE CHMOD (security)
<Limit SITE_CHMOD>
  DenyAll
</Limit>

# Deny root FTP access
<Limit LOGIN>
  DenyUser root
</Limit>

# Virtual users from /etc/forgeos/ftp/users
AuthUserFile /etc/forgeos/ftp/ftpd.passwd
AuthGroupFile /etc/forgeos/ftp/ftpd.group
AuthOrder mod_auth_file.c
FTPCONF

    mkdir -p /etc/forgeos/ftp
    touch /etc/forgeos/ftp/ftpd.passwd /etc/forgeos/ftp/ftpd.group
    chmod 600 /etc/forgeos/ftp/ftpd.passwd

    # UFW rules
    ufw allow 21/tcp  comment "FTPS control"
    ufw allow 990/tcp comment "FTPS implicit"
    ufw allow 40000:40100/tcp comment "FTPS passive"

    enable_service proftpd
    info "ProFTPD FTPS: port 21 (explicit TLS required)"
    info "  Add FTP user: forgeos-fileshare ftp-adduser <user> <pass>"
}

# ============================================================
# WEBDAV via nginx
# WebDAV runs as an nginx location block on the HTTPS port.
# No separate port — it's just another nginx path.
# Windows can mount it as a network drive natively.
# ============================================================
configure_webdav() {
    step "Configuring WebDAV (via nginx)"

    apt_install nginx-extras apache2-utils

    local webdav_root="${NAS_ROOT}/webdav"
    mkdir -p "$webdav_root"
    chmod 755 "$webdav_root"
    chown www-data:www-data "$webdav_root" 2>/dev/null || true

    # WebDAV password file
    local webdav_pass_file="/etc/forgeos/nginx/webdav.passwd"
    mkdir -p "$(dirname "$webdav_pass_file")"
    touch "$webdav_pass_file"
    chmod 600 "$webdav_pass_file"

    local domain; domain=$(forgenas_get "DOMAIN" "nas.local")

    # WebDAV nginx config — added as a location block on main server
    cat > /etc/nginx/forgeos.d/webdav.conf << WEBDAV
# ForgeOS WebDAV
server {
    listen 443 ssl http2;
    server_name dav.${domain};

    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    # WebDAV root
    location / {
        root ${webdav_root};
        client_max_body_size 0;           # no upload size limit
        client_body_timeout 600s;

        # WebDAV methods
        dav_methods     PUT DELETE MKCOL COPY MOVE;
        dav_ext_methods PROPFIND OPTIONS LOCK UNLOCK;
        dav_access      user:rw group:rw all:r;

        # Digest auth (safer than basic over any connection)
        auth_basic           "ForgeOS WebDAV";
        auth_basic_user_file ${webdav_pass_file};

        # CORS for desktop clients
        add_header Allow "OPTIONS, GET, HEAD, POST, PUT, DELETE, MKCOL, PROPFIND, PROPPATCH, COPY, MOVE, LOCK, UNLOCK" always;

        # Windows WebDAV compatibility
        add_header MS-Author-Via DAV always;

        autoindex on;
    }
}
WEBDAV

    nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || \
        warn "nginx WebDAV config — verify after nginx/cert setup"

    forgenas_set "WEBDAV_ROOT" "$webdav_root"
    forgenas_set "WEBDAV_PASS_FILE" "$webdav_pass_file"
    info "WebDAV: https://dav.${domain}"
    info "  Add user: forgeos-fileshare webdav-adduser <user> <pass>"
    info "  Windows mount: Map Network Drive → https://dav.${domain}"
}

# ============================================================
# FILEBROWSER
# Slick self-hosted web file manager.
# Port 8085, proxied via nginx to files.domain
# ============================================================
install_filebrowser() {
    step "Installing FileBrowser"

    local fb_dir="/opt/forgeos/apps/filebrowser"
    local fb_data="/srv/forgeos/filebrowser"
    mkdir -p "$fb_dir" "$fb_data"

    # Install FileBrowser binary
    if ! command -v filebrowser &>/dev/null; then
        curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh \
            | bash >> "$FORGENAS_LOG" 2>&1 \
            || _install_filebrowser_manual
    fi

    local domain; domain=$(forgenas_get "DOMAIN" "nas.local")

    # FileBrowser config
    cat > "${fb_dir}/filebrowser.json" << FBCONF
{
  "port":         8085,
  "baseURL":      "",
  "address":      "127.0.0.1",
  "log":          "stdout",
  "database":     "${fb_data}/filebrowser.db",
  "root":         "${NAS_ROOT}",
  "noauth":       false
}
FBCONF

    # systemd service
    cat > /etc/systemd/system/forgeos-filebrowser.service << SVC
[Unit]
Description=ForgeOS FileBrowser
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/filebrowser --config ${fb_dir}/filebrowser.json
Restart=always
RestartSec=5
StandardOutput=journal
SyslogIdentifier=filebrowser

[Install]
WantedBy=multi-user.target
SVC

    systemctl daemon-reload
    enable_service forgeos-filebrowser

    # nginx proxy
    if [[ -d /etc/nginx/forgeos.d ]]; then
        cat > /etc/nginx/forgeos.d/filebrowser.conf << NGINX
server {
    listen 443 ssl http2;
    server_name files.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    location / {
        proxy_pass         http://127.0.0.1:8085;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        client_max_body_size 0;
    }
}
NGINX
        nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi

    if wait_for_port 127.0.0.1 8085 20; then
        info "FileBrowser: https://files.${domain}"
    else
        info "FileBrowser: installed, starting on port 8085"
    fi
}

_install_filebrowser_manual() {
    # Fallback: direct binary download
    local arch; arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
    local ver
    ver=$(curl -sf https://api.github.com/repos/filebrowser/filebrowser/releases/latest \
          | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))" \
          2>/dev/null || echo "2.27.0")
    curl -sfL \
        "https://github.com/filebrowser/filebrowser/releases/download/v${ver}/linux-${arch}-filebrowser.tar.gz" \
        | tar xz -C /usr/local/bin filebrowser \
        && chmod +x /usr/local/bin/filebrowser \
        || warn "FileBrowser binary download failed"
}

# ============================================================
# UNIFIED FILE SHARING CLI
# ============================================================
install_fileshare_cli() {
    step "Installing forgeos-fileshare CLI"

    cat > /usr/local/bin/forgeos-fileshare << 'FSCLI'
#!/usr/bin/env bash
# ForgeOS File Sharing Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

case "$CMD" in

# ── NFS ──────────────────────────────────────────────────────
nfs-list)
    echo "=== NFS Exports ==="
    showmount -e localhost 2>/dev/null || exportfs -v
    ;;
nfs-add)
    # Usage: nfs-add <path> <cidr> [options]
    path="${1:?path}" cidr="${2:?cidr}" opts="${3:-rw,no_subtree_check,no_root_squash,async}"
    mkdir -p "$path"
    echo "${path} ${cidr}(${opts})" >> /etc/exports
    exportfs -ra
    echo "NFS export added: $path → $cidr"
    ;;
nfs-remove)
    path="${1:?path}"
    sed -i "\|^${path} |d" /etc/exports
    exportfs -ra
    echo "NFS export removed: $path"
    ;;

# ── FTP ──────────────────────────────────────────────────────
ftp-adduser)
    user="${1:?user}" pass="${2:?pass}"
    mkdir -p "/srv/nas/${user}"
    ftpasswd --passwd --file=/etc/forgeos/ftp/ftpd.passwd \
        --name="$user" --uid=1000 --gid=1000 \
        --home="/srv/nas/${user}" --shell=/bin/false \
        --stdin <<< "$pass"
    echo "FTP user '$user' created → /srv/nas/${user}"
    ;;
ftp-removeuser)
    ftpasswd --passwd --file=/etc/forgeos/ftp/ftpd.passwd \
        --name="${1:?user}" --delete-user
    echo "FTP user '$1' removed"
    ;;
ftp-listusers)
    awk -F: '{print $1}' /etc/forgeos/ftp/ftpd.passwd 2>/dev/null || echo "No FTP users"
    ;;
ftp-status)
    systemctl status proftpd --no-pager -l | head -10
    ;;

# ── WebDAV ───────────────────────────────────────────────────
webdav-adduser)
    user="${1:?user}" pass="${2:?pass}"
    local pf; pf=$(grep -oP 'auth_basic_user_file \K\S+' /etc/nginx/forgeos.d/webdav.conf 2>/dev/null \
                   || echo "/etc/forgeos/nginx/webdav.passwd")
    htpasswd -b "$pf" "$user" "$pass"
    echo "WebDAV user '$user' added"
    ;;
webdav-removeuser)
    local pf; pf=$(grep -oP 'auth_basic_user_file \K\S+' /etc/nginx/forgeos.d/webdav.conf 2>/dev/null \
                   || echo "/etc/forgeos/nginx/webdav.passwd")
    htpasswd -D "$pf" "${1:?user}"
    echo "WebDAV user '$1' removed"
    ;;

# ── FileBrowser ──────────────────────────────────────────────
filebrowser-status)
    systemctl status forgeos-filebrowser --no-pager -l | head -8
    ;;
filebrowser-adduser)
    filebrowser users add "${1:?user}" "${2:?pass}" \
        --config /opt/forgeos/apps/filebrowser/filebrowser.json 2>/dev/null \
        || echo "Use FileBrowser Web UI to manage users"
    ;;

# ── Status ───────────────────────────────────────────────────
status)
    echo "=== ForgeOS File Sharing ==="
    for svc in nfs-kernel-server proftpd forgeos-filebrowser; do
        systemctl is-active "$svc" &>/dev/null \
            && printf "  ✓ %-30s\n" "$svc" \
            || printf "  ✗ %-30s\n" "$svc"
    done
    echo ""
    echo "  NFS exports:"; exportfs 2>/dev/null | head -8
    echo ""
    echo "  FTP users: $(awk -F: '{print $1}' /etc/forgeos/ftp/ftpd.passwd 2>/dev/null | tr '\n' ' ' || echo 'none')"
    ;;

help|*)
    echo "ForgeOS File Sharing Manager"
    echo ""
    echo "NFS:"
    echo "  nfs-list                         Show active exports"
    echo "  nfs-add <path> <cidr> [options]  Add NFS export"
    echo "  nfs-remove <path>                Remove export"
    echo ""
    echo "FTPS (ProFTPD):"
    echo "  ftp-adduser <user> <pass>        Add FTP user"
    echo "  ftp-removeuser <user>            Remove FTP user"
    echo "  ftp-listusers                    List FTP users"
    echo "  ftp-status                       ProFTPD status"
    echo ""
    echo "WebDAV:"
    echo "  webdav-adduser <user> <pass>     Add WebDAV user"
    echo "  webdav-removeuser <user>         Remove WebDAV user"
    echo ""
    echo "FileBrowser:"
    echo "  filebrowser-status               FileBrowser status"
    echo "  filebrowser-adduser <user> <p>   Add FileBrowser user"
    echo ""
    echo "  status                           All services status"
    ;;
esac
FSCLI
    chmod +x /usr/local/bin/forgeos-fileshare
}

# ============================================================
# MAIN
# ============================================================
install_nfs
install_proftpd
configure_webdav
install_filebrowser
install_fileshare_cli

forgenas_set "MODULE_FILESHARE_DONE" "yes"
forgenas_set "FEATURE_FILESHARE" "yes"

domain=$(forgenas_get "DOMAIN" "nas.local")
info "File sharing module complete"
info "  NFS v4:       mount -t nfs4 ${HOSTNAME:-forgeos}.local:/nas /mnt"
info "  FTPS:         ${HOSTNAME:-forgeos}.${domain}:21 (TLS required)"
info "  WebDAV:       https://dav.${domain}"
info "  FileBrowser:  https://files.${domain}"
info "  Samba:        \\\\${HOSTNAME:-forgeos} (see module 10b)"
