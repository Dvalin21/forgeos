#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 99 - Finalize
# Installs API backend, wires all modules, prints summary
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

# ============================================================
# INSTALL PYTHON API BACKEND
# ============================================================
install_api_backend() {
    step "Installing ForgeOS API backend"

    apt_install python3 python3-pip python3-venv

    # Create virtualenv
    python3 -m venv /opt/forgeos/venv >> "$FORGENAS_LOG" 2>&1

    /opt/forgeos/venv/bin/pip install --quiet \
        fastapi \
        uvicorn[standard] \
        python-jose[cryptography] \
        passlib[bcrypt] \
        psutil \
        pydantic \
        python-multipart \
        >> "$FORGENAS_LOG" 2>&1 \
        || die "Python package install failed"

    # Copy API to final location
    cp "$(dirname "$0")/forgeos-api.py" /opt/forgeos/forgeos-api.py
    chmod 700 /opt/forgeos/forgeos-api.py

    # Generate JWT secret
    local jwt_secret; jwt_secret=$(openssl rand -base64 48 | tr -d '\n/')
    forgenas_set "FORGEOS_JWT_SECRET" "$jwt_secret"

    # Create initial admin user
    local admin_pass; admin_pass=$(openssl rand -base64 12 | tr -d '/')
    python3 << PYINIT
from passlib.context import CryptContext, json
ctx = CryptContext(schemes=['bcrypt'], deprecated='auto')
users = {"admin": {"hash": ctx.hash("${admin_pass}"), "role": "admin"}}
import json
open('/etc/forgeos/api-users.json','w').write(json.dumps(users, indent=2))
PYINIT
    chmod 600 /etc/forgeos/api-users.json
    forgenas_set "WEBUI_ADMIN_PASS" "$admin_pass"

    # systemd service
    cat > /etc/systemd/system/forgeos-api.service << SVC
[Unit]
Description=ForgeOS Web UI API Backend
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/forgeos
Environment="FORGEOS_JWT_SECRET=${jwt_secret}"
ExecStart=/opt/forgeos/venv/bin/python /opt/forgeos/forgeos-api.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=forgeos-api

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/etc/forgeos /var/log/forgeos /opt/forgeos /srv

[Install]
WantedBy=multi-user.target
SVC

    systemctl daemon-reload
    enable_service forgeos-api

    info "ForgeOS API running on http://127.0.0.1:5080"
    info "  Admin password: ${admin_pass} (save this!)"
}

# ============================================================
# INSTALL WEB UI FILES
# ============================================================
install_webui() {
    step "Installing ForgeOS Web UI"

    mkdir -p /opt/forgeos/web/wallpapers

    # Copy web files from installer package
    local web_src
    web_src="$(dirname "$0")/../web"

    if [[ -d "$web_src" ]]; then
        cp -r "$web_src"/* /opt/forgeos/web/
        info "Web UI installed from installer package"
    else
        warn "Web UI source not found at $web_src — install manually"
    fi

    chown -R root:root /opt/forgeos/web
    chmod -R 644 /opt/forgeos/web
    find /opt/forgeos/web -type d -exec chmod 755 {} \;
}

# ============================================================
# FORGEOS-CTL CLI
# ============================================================
install_ctl() {
    step "Installing forgeos-ctl CLI"

    cat > /usr/local/bin/forgeos-ctl << 'CTL'
#!/usr/bin/env bash
# ForgeOS Control CLI
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

case "$CMD" in
status)
    echo "══════════════════════════════════════"
    echo "  ForgeOS ${FORGEOS_VERSION:-1.0} — $(hostname -f)"
    echo "══════════════════════════════════════"
    for svc in forgeos-api nginx smbd nmbd mariadb postgresql redis-server smartd auditd fail2ban; do
        systemctl is-active "$svc" &>/dev/null \
            && printf "  ✓ %-20s\n" "$svc" \
            || printf "  ✗ %-20s\n" "$svc"
    done
    echo ""
    echo "  Uptime: $(uptime -p)"
    echo "  Load:   $(cat /proc/loadavg | awk '{print $1,$2,$3}')"
    ;;
restart-all)
    for svc in forgeos-api nginx smbd mariadb postgresql redis-server; do
        systemctl restart "$svc" 2>/dev/null && echo "  ↺ $svc" || echo "  ✗ $svc"
    done
    ;;
backup-now)    forgeos-storage snapshot; echo "Snapshot done" ;;
snapshot-now)  forgeos-storage snapshot ;;
pool-status)   forgeos-pool-status | python3 -m json.tool ;;
smart-check)
    for disk in $(lsblk -d -o NAME,TYPE | awk '/disk/{print "/dev/"$1}'); do
        echo "--- $disk ---"
        smartctl -H "$disk" 2>/dev/null | grep -E 'result:|SMART Health'
    done
    ;;
logs)
    tail -50 /var/log/forgeos/smart-alerts.log 2>/dev/null
    tail -20 /var/log/forgeos/hotswap.log 2>/dev/null
    ;;
update)
    apt update -qq && apt upgrade -y
    /opt/forgeos/venv/bin/pip install --quiet --upgrade fastapi uvicorn python-jose passlib psutil
    systemctl restart forgeos-api
    echo "ForgeOS updated"
    ;;
open)
    source /etc/forgeos/forgeos.conf 2>/dev/null || true
    echo "ForgeOS Web UI: https://${DOMAIN:-localhost}"
    ;;
version)
    echo "ForgeOS ${FORGEOS_VERSION:-1.0}"
    echo "Python API: $(/opt/forgeos/venv/bin/python --version 2>&1)"
    echo "nginx: $(nginx -v 2>&1 | grep -oP '[\d.]+')"
    echo "Kernel: $(uname -r)"
    ;;
help|*)
    echo "forgeos-ctl — ForgeOS Control"
    echo "  status         All service status"
    echo "  restart-all    Restart all services"
    echo "  backup-now     Create snapshot + run backup"
    echo "  snapshot-now   btrfs snapshot all pools"
    echo "  pool-status    Show pool + drive health (JSON)"
    echo "  smart-check    Quick SMART check on all drives"
    echo "  logs           Recent alerts and hotswap events"
    echo "  update         Update system and ForgeOS components"
    echo "  open           Show Web UI URL"
    echo "  version        Version info"
    ;;
esac
CTL
    chmod +x /usr/local/bin/forgeos-ctl
    info "forgeos-ctl installed"
}

# ============================================================
# POST-INSTALL SUMMARY
# ============================================================
print_summary() {
    source "$FORGENAS_CONFIG"
    local d="${DOMAIN:-$(hostname -f)}"

    echo ""
    echo -e "\033[38;5;208m"
    cat << 'LOGO'
    ___                 ___  ____
   / __\___  _ __ __ _ / _ \/ ___|
  / _\ / _ \| '__/ _` | | | \___ \
 / /  | (_) | | | (_| | |_| |___) |
 \/    \___/|_|  \__, |\___/|____/
                 |___/
LOGO
    echo -e "\033[0m"
    echo "  ══════════════════════════════════════════════════"
    echo "  ForgeOS Installation Complete"
    echo "  ══════════════════════════════════════════════════"
    echo ""
    echo "  Web UI:       https://${d}"
    echo "  Username:     admin"
    echo "  Password:     ${WEBUI_ADMIN_PASS:-<see /etc/forgeos/forgeos.conf>}"
    echo ""
    echo "  ── Installed Modules ──────────────────────────────"
    [[ "${FEATURE_STORAGE:-}"    == "yes" ]] && echo "  ✓ ForgeRAID Storage (mdadm+btrfs, hot-swap, SMART)"
    [[ "${FEATURE_DOCKER:-}"     == "yes" ]] && echo "  ✓ Docker CE + Incus"
    [[ "${FEATURE_SECURITY:-}"   == "yes" ]] && echo "  ✓ Security (UFW, Fail2ban, CrowdSec, AppArmor)"
    [[ "${FEATURE_MONITORING:-}" == "yes" ]] && echo "  ✓ Monitoring (Prometheus, Grafana, Alertmanager)"
    [[ "${FEATURE_FILESHARE:-}"  == "yes" ]] && echo "  ✓ File Sharing (Samba, NFS, FTPS, WebDAV)"
    [[ "${FEATURE_VPN:-}"        == "yes" ]] && echo "  ✓ VPN (WireGuard + Netbird)"
    [[ "${PROXY:-}"              == "nginx" ]] && echo "  ✓ Reverse Proxy (nginx + Let's Encrypt)"
    [[ "${FEATURE_MAIL:-}"       == "yes" ]] && echo "  ✓ Mail Server (Postfix+Dovecot+Rspamd+SOGo)"
    [[ "${FEATURE_BACKUP:-}"     == "yes" ]] && echo "  ✓ Backup (Restic+Rclone+Snapper)"
    [[ "${FEATURE_CLOUD:-}"      == "yes" ]] && echo "  ✓ Cloud Storage (MinIO S3 + rclone crypt)"
    [[ "${HIPAA_ENABLED:-}"      == "yes" ]] && echo "  ✓ HIPAA Compliance Mode"
    echo ""
    echo "  ── Subdomains ─────────────────────────────────────"
    echo "    grafana.${d}   — Metrics dashboard"
    echo "    photos.${d}    — Immich photo library"
    echo "    mail.${d}      — SOGo webmail"
    echo "    auth.${d}      — Authentik SSO"
    echo "    s3.${d}        — MinIO S3 console"
    echo "    files.${d}     — FileBrowser"
    echo "    push.${d}      — Gotify notifications"
    echo ""
    echo "  ── Quick Commands ─────────────────────────────────"
    echo "    forgeos-ctl status          All service health"
    echo "    forgeos-ctl pool-status     Drive health grouped by pool"
    echo "    forgeos-ctl smart-check     Quick SMART scan"
    echo "    forgeos-samba edb-info      ElevateDB/database share setup"
    echo "    forgeos-db status           Database engines"
    echo "    forgeos-nginx list          All proxy vhosts"
    echo "    forgeos-hipaa check         HIPAA compliance scan (if enabled)"
    echo ""
    echo "  ── Log Files ──────────────────────────────────────"
    echo "    /var/log/forgeos-install.log"
    echo "    /var/log/forgeos/smart-alerts.log"
    echo "    /var/log/forgeos/hotswap.log"
    echo ""
    echo "  ══════════════════════════════════════════════════"
    echo ""

    # Homelab vs business reminder
    echo -e "  \033[38;5;208mForgeOS is designed for both homelab AND small business.\033[0m"
    echo "  HIPAA mode, ElevateDB support, and enterprise Samba"
    echo "  features are optional — enable only what you need."
    echo ""
}

# ============================================================
# MAIN
# ============================================================
install_webui
install_api_backend
install_ctl
print_summary

forgenas_set "FORGEOS_VERSION" "1.0"
forgenas_set "INSTALL_COMPLETE" "yes"
forgenas_set "INSTALL_DATE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
