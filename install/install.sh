#!/usr/bin/env bash
# ============================================================
# ForgeOS — Master Installer
# Usage:  sudo bash install.sh [--unattended] [--modules all|base,storage,...]
#
# This installer is intentionally simple. It:
#  1. Collects configuration (interactive or from env vars)
#  2. Runs selected modules in order
#  3. Each module is idempotent — safe to re-run
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/detect.sh"

# ── Args ─────────────────────────────────────────────────────
UNATTENDED=false
FORCE=false
SELECTED_MODULES=""
for arg in "$@"; do
    case "$arg" in
        --unattended) UNATTENDED=true ;;
        --force)      FORCE=true ;;
        --modules=*)  SELECTED_MODULES="${arg#--modules=}" ;;
    esac
done

# ── Header ───────────────────────────────────────────────────
clear
echo -e "${ORANGE}"
cat << 'LOGO'
     ___                 ___  ____
    / __\___  _ __ __ _ / _ \/ ___|
   / _\ / _ \| '__/ _` | | | \___ \
  / /  | (_) | | | (_| | |_| |___) |
  \/    \___/|_|  \__, |\___/|____/
                  |___/
LOGO
echo -e "${NC}"
echo -e "  ${BOLD}ForgeOS Installer v1.0${NC}"
echo -e "  ${DIM}NAS & Home Server Platform for Ubuntu/Debian${NC}"
echo ""

# ── Pre-flight ───────────────────────────────────────────────
require_root
require_ubuntu_debian
check_internet

mkdir -p /etc/forgeos
chmod 700 /etc/forgeos
touch "$FORGENAS_CONFIG"
chmod 600 "$FORGENAS_CONFIG"

forgenas_set "FORGEOS_VERSION"  "1.0"
forgenas_set "INSTALL_STARTED"  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── Hardware detection ───────────────────────────────────────
step "Detecting hardware"
detect_all
detect_print_summary

# ── Interactive configuration ─────────────────────────────────
step "Configuration"

if ! $UNATTENDED; then
    echo ""
    echo -e "  ${DIM}Press Enter to accept defaults shown in [brackets]${NC}"
    echo ""

    # Hostname
    ask "Hostname" "$(hostname -s)"
    FORGEOS_HOSTNAME="$REPLY"
    hostnamectl set-hostname "$FORGEOS_HOSTNAME" 2>/dev/null || true
    forgenas_set "HOSTNAME" "$FORGEOS_HOSTNAME"

    # Domain / DDNS
    ask "Domain (e.g. home.mydomain.com or nas.local for LAN-only)" "nas.local"
    FORGEOS_DOMAIN="$REPLY"
    forgenas_set "DOMAIN" "$FORGEOS_DOMAIN"

    # Email for Let's Encrypt
    if [[ "$FORGEOS_DOMAIN" != "nas.local" && "$FORGEOS_DOMAIN" != "localhost" ]]; then
        ask "Email for Let's Encrypt cert" "admin@${FORGEOS_DOMAIN}"
        forgenas_set "ACME_EMAIL" "$REPLY"
    fi

    # Timezone
    current_tz=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "UTC")
    ask "Timezone" "$current_tz"
    timedatectl set-timezone "$REPLY" 2>/dev/null || true
    forgenas_set "TIMEZONE" "$REPLY"

    # Admin user
    ask "Admin username (will be created if not exists)" "forgeos"
    FORGEOS_ADMIN_USER="$REPLY"
    forgenas_set "ADMIN_USER" "$FORGEOS_ADMIN_USER"

    echo ""
    echo -e "  ${BOLD}Module Selection${NC}"
    echo -e "  ${DIM}Select which features to install:${NC}"
    echo ""

    FEAT_STORAGE=true
    FEAT_DOCKER=true
    FEAT_GPU=false
    FEAT_SECURITY=true
    FEAT_MONITORING=true
    FEAT_FILESHARE=true
    FEAT_VPN=false
    FEAT_PROXY=true
    FEAT_LDAP=false
    FEAT_MAIL=false
    FEAT_BACKUP=true
    FEAT_CLOUD=false
    FEAT_HIPAA=false
    FEAT_APPS=false

    ask_yn "Install ForgeRAID storage (mdadm+btrfs)"   y && FEAT_STORAGE=true   || FEAT_STORAGE=false
    ask_yn "Install Docker CE + Incus containers"       y && FEAT_DOCKER=true    || FEAT_DOCKER=false
    ask_yn "Install GPU drivers (NVIDIA/AMD/Intel Arc)" n && FEAT_GPU=true       || FEAT_GPU=false
    ask_yn "Install security (UFW, Fail2ban, CrowdSec)" y && FEAT_SECURITY=true  || FEAT_SECURITY=false
    ask_yn "Install monitoring (Grafana + Prometheus)"  y && FEAT_MONITORING=true || FEAT_MONITORING=false
    ask_yn "Install file sharing (Samba/NFS/FTPS/DAV)"  y && FEAT_FILESHARE=true || FEAT_FILESHARE=false
    ask_yn "Install VPN (WireGuard + Netbird)"          n && FEAT_VPN=true       || FEAT_VPN=false
    ask_yn "Install nginx reverse proxy + certs"        y && FEAT_PROXY=true     || FEAT_PROXY=false
    ask_yn "Install LDAP/OIDC auth (lldap + Authentik)" n && FEAT_LDAP=true      || FEAT_LDAP=false
    ask_yn "Install mail server (Postfix+Dovecot+SOGo)" n && FEAT_MAIL=true      || FEAT_MAIL=false
    ask_yn "Install backup (Restic+Rclone+Snapper)"     y && FEAT_BACKUP=true    || FEAT_BACKUP=false
    ask_yn "Install cloud storage (MinIO S3)"           n && FEAT_CLOUD=true     || FEAT_CLOUD=false
    ask_yn "Install media apps (Immich, OnlyOffice)"    n && FEAT_APPS=true      || FEAT_APPS=false
    ask_yn "Enable HIPAA compliance mode"               n && FEAT_HIPAA=true     || FEAT_HIPAA=false

    echo ""
    echo -e "  ${BOLD}Ready to install.${NC}"
    ask_yn "Begin installation?" y || { echo "Aborted."; exit 0; }

else
    # Unattended defaults — install everything sensible
    FORGEOS_HOSTNAME="${FORGEOS_HOSTNAME:-$(hostname -s)}"
    FORGEOS_DOMAIN="${FORGEOS_DOMAIN:-nas.local}"
    FORGEOS_ADMIN_USER="${FORGEOS_ADMIN_USER:-forgeos}"
    FEAT_STORAGE="${FEAT_STORAGE:-true}"
    FEAT_DOCKER="${FEAT_DOCKER:-true}"
    FEAT_GPU="${FEAT_GPU:-false}"
    FEAT_SECURITY="${FEAT_SECURITY:-true}"
    FEAT_MONITORING="${FEAT_MONITORING:-true}"
    FEAT_FILESHARE="${FEAT_FILESHARE:-true}"
    FEAT_VPN="${FEAT_VPN:-false}"
    FEAT_PROXY="${FEAT_PROXY:-true}"
    FEAT_LDAP="${FEAT_LDAP:-false}"
    FEAT_MAIL="${FEAT_MAIL:-false}"
    FEAT_BACKUP="${FEAT_BACKUP:-true}"
    FEAT_CLOUD="${FEAT_CLOUD:-false}"
    FEAT_APPS="${FEAT_APPS:-false}"
    FEAT_HIPAA="${FEAT_HIPAA:-false}"

    forgenas_set "HOSTNAME"    "$FORGEOS_HOSTNAME"
    forgenas_set "DOMAIN"      "$FORGEOS_DOMAIN"
    forgenas_set "ADMIN_USER"  "$FORGEOS_ADMIN_USER"
fi

forgenas_set "FEATURE_STORAGE"    "$FEAT_STORAGE"
forgenas_set "FEATURE_DOCKER"     "$FEAT_DOCKER"
forgenas_set "FEATURE_GPU"        "$FEAT_GPU"
forgenas_set "FEATURE_SECURITY"   "$FEAT_SECURITY"
forgenas_set "FEATURE_MONITORING" "$FEAT_MONITORING"
forgenas_set "FEATURE_FILESHARE"  "$FEAT_FILESHARE"
forgenas_set "FEATURE_VPN"        "$FEAT_VPN"
forgenas_set "FEATURE_PROXY"      "$FEAT_PROXY"
forgenas_set "FEATURE_LDAP"       "$FEAT_LDAP"
forgenas_set "FEATURE_MAIL"       "$FEAT_MAIL"
forgenas_set "FEATURE_BACKUP"     "$FEAT_BACKUP"
forgenas_set "FEATURE_CLOUD"      "$FEAT_CLOUD"
forgenas_set "FEATURE_APPS"       "$FEAT_APPS"
forgenas_set "FEATURE_HIPAA"      "$FEAT_HIPAA"

# ── Module runner ────────────────────────────────────────────
# SELECTED_MODULES: comma-separated list from --modules= flag.
# When set, only modules whose script/name contains one of the
# listed tokens are run. e.g. --modules=storage,docker,vpn
# Base (01) and finalize (99) always run regardless of filter.
run_module() {
    local num="$1" name="$2" script="$3"
    local feat="${4:-true}"

    # Feature flag gate
    [[ "$feat" == "false" ]] && return 0

    # --modules= filter gate
    if [[ -n "$SELECTED_MODULES" ]]; then
        local matched=false token
        IFS=',' read -ra _mod_tokens <<< "$SELECTED_MODULES"
        for token in "${_mod_tokens[@]}"; do
            token="${token// /}"
            [[ "$script" == *"$token"* || "$name" == *"$token"* ]] && matched=true && break
        done
        [[ "$script" == "01-base.sh" || "$script" == "99-finalize.sh" ]] && matched=true
        [[ "$matched" == "false" ]] && return 0
    fi

    echo ""
    echo -e "${ORANGE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${ORANGE}  Module ${num}: ${name}${NC}"
    echo -e "${ORANGE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if ! $FORCE && module_is_done "$script"; then
        info "Already installed — skipping. (--force to reinstall)"
        return 0
    fi

    local module_path="$SCRIPT_DIR/modules/${script}"
    if [[ ! -f "$module_path" ]]; then
        warn "Module not found: $module_path — skipping"
        return 0
    fi

    bash "$module_path" || {
        warn "Module $name reported an error (check $FORGENAS_LOG)"
        if ! $UNATTENDED; then
            ask_yn "Continue to next module despite error?" y || exit 1
        fi
    }

    module_mark_done "$script"
}

# ── Run modules in order ─────────────────────────────────────
run_module  "01" "Base System"            "01-base.sh"           "true"
run_module  "02" "Network"                "02-network.sh"        "true"
run_module  "03" "ForgeRAID Storage"      "03-storage.sh"        "$FEAT_STORAGE"
run_module "03b" "Hot-Swap & SMART"       "03-storage-hotswap.sh" "$FEAT_STORAGE"
run_module  "04" "Docker + Incus"         "04-docker.sh"         "$FEAT_DOCKER"
run_module  "06" "GPU Drivers"            "06-gpu.sh"            "$FEAT_GPU"
run_module  "07" "Security"              "07-security.sh"        "$FEAT_SECURITY"
run_module  "09" "Monitoring"             "09-monitoring.sh"     "$FEAT_MONITORING"
run_module "10a" "File Sharing Core"      "10-fileshare.sh"      "$FEAT_FILESHARE"
run_module "10b" "Samba + Database"       "10b-samba-db.sh"      "$FEAT_FILESHARE"
run_module  "11" "VPN"                    "11-vpn.sh"            "$FEAT_VPN"
run_module  "12" "Reverse Proxy"          "12-reverse-proxy.sh"  "$FEAT_PROXY"
run_module  "13" "LDAP + OIDC Auth"       "13-ldap-oidc.sh"      "$FEAT_LDAP"
run_module  "14" "Mail Server"            "14-mail.sh"           "$FEAT_MAIL"
run_module  "15" "Backup"                 "15-backup.sh"         "$FEAT_BACKUP"
run_module  "16" "Cloud Storage"          "16-cloud-storage.sh"  "$FEAT_CLOUD"
run_module  "17" "HIPAA Compliance"       "17-hipaa.sh"          "$FEAT_HIPAA"
run_module  "99" "Finalize"              "99-finalize.sh"        "true"

echo ""
echo -e "${GREEN}${BOLD}  ForgeOS installation complete!${NC}"
echo ""
