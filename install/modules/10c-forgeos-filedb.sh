#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 10c - ForgeFileDB
# Open-source file-based database coordinator.
#
# Solves:
#   1. Corruption prevention for ElevateDB, DBISAM, dBase,
#      Access, FoxPro, NexusDB, SQLite, Firebird over SMB
#   2. 20-30+ concurrent users without proprietary software
#   3. Versioned snapshots with point-in-time restore
#   4. mDNS broadcast for network discovery
#   5. Web UI at http://forgeos.local:12010
#
# Why NOT an ElevateDB Server clone:
#   ElevateDB Server uses a proprietary binary TCP wire protocol
#   that is fully undocumented. We cannot implement a compatible
#   server without reverse engineering it (legally risky).
#   What we CAN do — and what ForgeFileDB does — is solve the
#   ACTUAL problems (corruption + concurrency) at the SMB/OS
#   layer, which is more robust and works for ALL file-based
#   databases, not just ElevateDB.
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

FILEDB_DIR="/opt/forgeos/filedb"
FILEDB_WEB="/opt/forgeos/filedb/web"
FILEDB_BIN="$FILEDB_DIR/forgeos-filedb.py"
FILEDB_SNAP="/srv/forgeos/filedb/snapshots"
FILEDB_CONF="/etc/forgeos/filedb/filedb.conf"
# shellcheck disable=SC2034
# shellcheck disable=SC2034
FILEDB_LOG="/var/log/forgeos/filedb.log"

mkdir -p "$FILEDB_DIR" "$FILEDB_WEB" "$FILEDB_SNAP" "$(dirname "$FILEDB_CONF")"
chmod 700 "$(dirname "$FILEDB_CONF")"

# ============================================================
# DEPENDENCIES
# ============================================================
install_filedb_deps() {
    step "Installing ForgeFileDB dependencies"

    apt_install \
        python3 python3-pip python3-venv \
        avahi-daemon avahi-utils libnss-mdns \
        inotify-tools

    # Python venv (shared with forgeos-api if possible)
    if [[ ! -d /opt/forgeos/venv ]]; then
        python3 -m venv /opt/forgeos/venv >> "$FORGENAS_LOG" 2>&1
    fi

    /opt/forgeos/venv/bin/pip install --quiet \
        fastapi \
        "uvicorn[standard]" \
        inotify \
        >> "$FORGENAS_LOG" 2>&1 \
        || warn "Some Python packages failed (inotify will fall back to polling)"

    # Avahi config — enable mDNS broadcasting
    sed -i 's/^#\?use-ipv4=.*/use-ipv4=yes/' /etc/avahi/avahi-daemon.conf 2>/dev/null || true
    sed -i 's/^#\?use-ipv6=.*/use-ipv6=yes/' /etc/avahi/avahi-daemon.conf 2>/dev/null || true
    sed -i 's/^#\?enable-dbus=.*/enable-dbus=yes/' /etc/avahi/avahi-daemon.conf 2>/dev/null || true
    enable_service avahi-daemon

    info "ForgeFileDB dependencies installed"
}

# ============================================================
# INSTALL DAEMON + WEB UI
# ============================================================
install_filedb() {
    step "Installing ForgeFileDB daemon"

    # Copy daemon script
    cp "$(dirname "$0")/../src/forgeos-filedb.py" "$FILEDB_BIN" 2>/dev/null \
        || cp "$(dirname "$0")/forgeos-filedb.py" "$FILEDB_BIN" 2>/dev/null \
        || warn "Daemon source not found — download from ForgeOS repo"
    chmod 700 "$FILEDB_BIN"

    # Copy web UI
    local web_src; web_src="$(dirname "$0")/../web"
    [[ -d "$web_src" ]] && cp -r "$web_src"/* "$FILEDB_WEB/" || true

    # Default config
    cat > "$FILEDB_CONF" << CONF
# ForgeFileDB Configuration
SNAPSHOT_DEBOUNCE="30"
MAX_SNAPSHOTS="48"
WRITE_THRESHOLD="100"
WATCH_ROOT="/srv/nas"
API_PORT="12010"
SNAPSHOT_ROOT="/srv/forgeos/filedb/snapshots"
CONF
    chmod 600 "$FILEDB_CONF"

    # systemd service
    cat > /etc/systemd/system/forgeos-filedb.service << SVC
[Unit]
Description=ForgeFileDB — File-Based Database Coordinator
Documentation=https://forgeos.local/docs/filedb
After=network.target samba-ad-dc.service smbd.service avahi-daemon.service
Wants=avahi-daemon.service

[Service]
Type=simple
User=root
EnvironmentFile=-/etc/forgeos/filedb/filedb.conf
ExecStart=/opt/forgeos/venv/bin/python ${FILEDB_BIN}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=forgeos-filedb

# Resource limits — be a good NAS citizen
CPUQuota=30%
MemoryLimit=256M
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=5

# Security
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/etc/forgeos /var/log/forgeos /opt/forgeos /srv /etc/avahi

[Install]
WantedBy=multi-user.target
SVC

    systemctl daemon-reload
    enable_service forgeos-filedb

    if wait_for_port 0.0.0.0 12010 30; then
        info "ForgeFileDB running on port 12010"
    else
        warn "ForgeFileDB may not have started — check: journalctl -u forgeos-filedb"
    fi
}

# ============================================================
# NGINX VHOST
# Proxy /filedb → ForgeFileDB UI
# Also add to main ForgeOS reverse proxy
# ============================================================
configure_nginx_vhost() {
    step "Configuring nginx proxy for ForgeFileDB"

    local domain; domain=$(forgenas_get "DOMAIN" "nas.local")

    cat > /etc/nginx/forgeos.d/filedb.conf << NGINX
# ForgeFileDB Web UI
server {
    listen 443 ssl http2;
    server_name filedb.${domain};

    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:12010;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX

    nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || \
        warn "nginx config test failed — check manually"

    forgeos-nginx add-vhost filedb "filedb.${domain}" 12010 acme none yes \
        >> "$FORGENAS_LOG" 2>&1 || true

    info "ForgeFileDB available at https://filedb.${domain}"
}

# ============================================================
# FIREWALL RULES
# Port 12010: ForgeFileDB API + Web UI (LAN only)
# ============================================================
configure_firewall() {
    step "Configuring ForgeFileDB firewall rules"

    # LAN access only (no public internet access for DB coordinator)
    local lan_cidr
    lan_cidr=$(ip route | awk '/src/ && !/^default/{print $1}' | head -1 || echo "192.168.0.0/16")

    ufw allow from "$lan_cidr" to any port 12010 proto tcp comment "ForgeFileDB LAN" 2>/dev/null || true
    ufw deny 12010 2>/dev/null || true  # block from internet

    info "ForgeFileDB port 12010: LAN-only (${lan_cidr})"
}

# ============================================================
# CLI
# ============================================================
install_filedb_cli() {
    step "Installing forgeos-filedb CLI"

    cat > /usr/local/bin/forgeos-filedb << 'FDBCLI'
#!/usr/bin/env bash
# ForgeFileDB Control CLI
CMD="${1:-help}"; shift || true
BASE="http://localhost:12010/api"

curl_j() { curl -sf -H "Content-Type: application/json" "$@"; }

case "$CMD" in
status)
    curl_j "${BASE}/status" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'  Clients:   {d[\"connected_clients\"]}')
print(f'  Open DBs:  {d[\"open_databases\"]}')
print(f'  Snaps/day: {d[\"snapshots_today\"]}')
print(f'  Conflicts: {d[\"total_conflicts\"]} (serialized safely)')
" 2>/dev/null || systemctl status forgeos-filedb --no-pager -l | head -8 ;;
clients)
    curl_j "${BASE}/clients" | python3 -c "
import sys,json
for c in json.load(sys.stdin).get('clients',[]):
    files = ', '.join(f['name'] for f in c['files'])
    print(f'  {c[\"ip\"]:20s}  {files or \"(no open files)\"}')
" ;;
databases)
    curl_j "${BASE}/databases" | python3 -c "
import sys,json
for g in json.load(sys.stdin).get('databases',[]):
    print(f\"\n  {g['dir']}\")
    for f in g['files']:
        print(f\"    {f['name']:40s} {f['db_type']:20s}\")
" ;;
snapshot)
    dir="${1:-/srv/nas}"
    curl_j -X POST "${BASE}/snapshots" \
        -d "{\"db_dir\":\"${dir}\",\"reason\":\"manual:cli\"}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ts','error'))"
    ;;
snapshots)
    curl_j "${BASE}/snapshots" | python3 -c "
import sys,json
for s in json.load(sys.stdin).get('snapshots',[])[:20]:
    print(f\"  {s['ts']}  {s['db_dir'].split('/')[-1]:30s}  {s['method']}  {s['reason']}\")
" ;;
restore)
    ts="${1:?snapshot_ts}" dir="${2:?db_dir}" target="${3:-}"
    curl_j -X POST "${BASE}/snapshots/restore" \
        -d "{\"snap_ts\":\"${ts}\",\"db_dir\":\"${dir}\",\"target_dir\":\"${target:-null}\"}"
    ;;
logs)   curl_j "${BASE}/log?lines=50" | python3 -c "import sys,json; [print(l) for l in json.load(sys.stdin)['lines']]" ;;
restart) systemctl restart forgeos-filedb; echo "Restarted" ;;
web)    echo "Web UI: http://localhost:12010   or   https://filedb.$(hostname -f)" ;;
help|*)
    echo "ForgeFileDB — File-Based Database Coordinator"
    echo ""
    echo "  status               Live status"
    echo "  clients              Connected SMB clients"
    echo "  databases            Discovered database files"
    echo "  snapshot [dir]       Create snapshot (default: /srv/nas)"
    echo "  snapshots            List recent snapshots"
    echo "  restore <ts> <dir> [target]  Restore snapshot"
    echo "  logs                 Recent daemon log"
    echo "  restart              Restart daemon"
    echo "  web                  Show Web UI URL"
    echo ""
    echo "  Supported: ElevateDB, DBISAM, dBase, Access, FoxPro,"
    echo "             NexusDB, SQLite, Firebird, Paradox, TurboDB"
    ;;
esac
FDBCLI
    chmod +x /usr/local/bin/forgeos-filedb
}

# ============================================================
# MAIN
# ============================================================
install_filedb_deps
install_filedb
configure_nginx_vhost
configure_firewall
install_filedb_cli

forgenas_set "FEATURE_FILEDB" "yes"
forgenas_set "FILEDB_URL" "http://localhost:12010"

info "ForgeFileDB installed"
info "  Web UI:    https://filedb.$(forgenas_get DOMAIN nas.local)"
info "  CLI:       forgeos-filedb help"
info "  Status:    forgeos-filedb status"
info "  Snapshots: forgeos-filedb snapshots"
info "  Port:      12010 (LAN only, mDNS: _forgeos-filedb._tcp)"
info ""
warn "  NOTE: ForgeFileDB is NOT an ElevateDB Server clone."
warn "  It solves the same problems (corruption + concurrency)"
warn "  by coordinating at the SMB/OS level, not via the EDB protocol."
warn "  ElevateDB clients in 'Local' session mode work transparently."
warn "  For 'Remote' (C/S) mode, EDB Server license is still required."
