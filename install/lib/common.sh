#!/usr/bin/env bash
# ============================================================
# shellcheck disable=SC2034  # color vars used by sourcing scripts
# ForgeOS lib/common.sh — Shared functions for all modules
# Source this at the top of every module:
#   source "$(dirname "$0")/../lib/common.sh"
# ============================================================
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────
BOLD="\033[1m"
NC="\033[0m"
GREEN="\033[38;5;71m"
YELLOW="\033[38;5;214m"
RED="\033[38;5;196m"
ORANGE="\033[38;5;208m"
BLUE="\033[38;5;68m"
DIM="\033[2m"

# ── Paths ───────────────────────────────────────────────────
FORGENAS_CONFIG="${FORGENAS_CONFIG:-/etc/forgeos/forgeos.conf}"
FORGENAS_LOG="${FORGENAS_LOG:-/var/log/forgeos-install.log}"
FORGEOS_STATE="/var/lib/forgeos"
FORGEOS_MODULES_DONE="$FORGEOS_STATE/modules-done"

mkdir -p "$(dirname "$FORGENAS_LOG")" "$FORGEOS_STATE"
touch "$FORGENAS_LOG"

# ── Logging ─────────────────────────────────────────────────
_ts() { date '+%H:%M:%S'; }

step() {
    local msg="$1"
    echo -e "\n${ORANGE}▶${NC} ${BOLD}${msg}${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STEP: $msg" >> "$FORGENAS_LOG"
}

info() {
    echo -e "  ${GREEN}✓${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1" >> "$FORGENAS_LOG"
}

warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $1" >> "$FORGENAS_LOG"
}

die() {
    echo -e "\n  ${RED}✗ FATAL:${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FATAL: $1" >> "$FORGENAS_LOG"
    echo ""
    echo "  Log: $FORGENAS_LOG"
    exit 1
}

_progress() {
    local msg="$1"
    echo -ne "  ${DIM}${msg}...${NC}"
}

_done() {
    echo -e " ${GREEN}done${NC}"
}

# ── Root check ───────────────────────────────────────────────
require_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root."
}

# ── OS check ─────────────────────────────────────────────────
require_ubuntu_debian() {
    if ! command -v lsb_release &>/dev/null; then
        die "lsb_release not found — is this Ubuntu/Debian?"
    fi
    local id; id=$(lsb_release -is)
    [[ "$id" == "Ubuntu" || "$id" == "Debian" ]] \
        || die "ForgeOS requires Ubuntu or Debian. Found: $id"
    local ver; ver=$(lsb_release -rs | cut -d. -f1)
    if [[ "$id" == "Ubuntu" && "$ver" -lt 22 ]]; then
        die "ForgeOS requires Ubuntu 22.04+. Found: $(lsb_release -ds)"
    fi
    if [[ "$id" == "Debian" && "$ver" -lt 12 ]]; then
        die "ForgeOS requires Debian 12+. Found: $(lsb_release -ds)"
    fi
}

# ── apt wrapper ───────────────────────────────────────────────
_apt_ready=false
apt_update() {
    if ! $_apt_ready; then
        _progress "Updating apt cache"
        DEBIAN_FRONTEND=noninteractive apt-get update -qq >> "$FORGENAS_LOG" 2>&1
        _apt_ready=true
        _done
    fi
}

apt_install() {
    apt_update
    _progress "Installing: $*"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        --no-install-recommends "$@" >> "$FORGENAS_LOG" 2>&1 \
        || die "apt install failed: $*"
    _done
}

apt_install_optional() {
    apt_update
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        --no-install-recommends "$@" >> "$FORGENAS_LOG" 2>&1 \
        || warn "Optional package not available: $*"
}

# ── Config key=value store ────────────────────────────────────
forgenas_set() {
    local key="$1" val="$2"
    mkdir -p "$(dirname "$FORGENAS_CONFIG")"
    touch "$FORGENAS_CONFIG"
    if grep -q "^${key}=" "$FORGENAS_CONFIG" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$FORGENAS_CONFIG"
    else
        echo "${key}=\"${val}\"" >> "$FORGENAS_CONFIG"
    fi
}

forgenas_get() {
    local key="$1" default="${2:-}"
    source "$FORGENAS_CONFIG" 2>/dev/null || true
    echo "${!key:-$default}"
}

# ── Service helpers ───────────────────────────────────────────
enable_service() {
    local svc="$1"
    systemctl enable "$svc" >> "$FORGENAS_LOG" 2>&1 || warn "Could not enable $svc"
    systemctl start  "$svc" >> "$FORGENAS_LOG" 2>&1 || warn "Could not start $svc"
}

restart_service() {
    local svc="$1"
    systemctl restart "$svc" >> "$FORGENAS_LOG" 2>&1 || warn "Could not restart $svc"
}

# ── Module tracking ───────────────────────────────────────────
module_mark_done() {
    echo "$1" >> "$FORGEOS_MODULES_DONE"
}

module_is_done() {
    grep -qxF "$1" "$FORGEOS_MODULES_DONE" 2>/dev/null
}

module_skip_if_done() {
    local name="$1"
    if module_is_done "$name"; then
        info "Module '$name' already installed — skipping (use --force to reinstall)"
        return 0
    fi
    return 1
}

# ── Internet check ────────────────────────────────────────────
check_internet() {
    if ! curl -sf --max-time 5 https://deb.debian.org/debian/ > /dev/null 2>&1; then
        die "No internet connection. ForgeOS installer requires internet access."
    fi
}

# ── Interactive prompt helpers ────────────────────────────────
ask() {
    # Usage: ask "Question" default_value → sets REPLY
    local prompt="$1" default="${2:-}"
    echo -ne "  ${BOLD}${prompt}${NC}"
    [[ -n "$default" ]] && echo -ne " ${DIM}[${default}]${NC}"
    echo -ne ": "
    read -r REPLY
    REPLY="${REPLY:-$default}"
}

ask_yn() {
    # Returns 0 for yes, 1 for no
    local prompt="$1" default="${2:-n}"
    local hint
    [[ "$default" == "y" ]] && hint="Y/n" || hint="y/N"
    echo -ne "  ${BOLD}${prompt}${NC} ${DIM}(${hint})${NC}: "
    read -r _ans
    _ans="${_ans:-$default}"
    [[ "${_ans,,}" == "y" ]]
}

# ── Docker Compose helper ─────────────────────────────────────
docker_compose_up() {
    local dir="$1" file="${2:-docker-compose.yml}"
    docker compose -f "${dir}/${file}" up -d >> "$FORGENAS_LOG" 2>&1 \
        || warn "docker compose up failed for ${file}"
}

docker_compose_pull() {
    local dir="$1" file="${2:-docker-compose.yml}"
    docker compose -f "${dir}/${file}" pull >> "$FORGENAS_LOG" 2>&1 \
        || warn "docker compose pull failed for ${file}"
}

# ── Firewall helper ───────────────────────────────────────────
ufw_allow() {
    ufw allow "$@" >> "$FORGENAS_LOG" 2>&1 || true
}

# ── Wait for service ──────────────────────────────────────────
wait_for_port() {
    local host="${1:-127.0.0.1}" port="$2" tries="${3:-30}"
    local i=0
    while ! nc -z "$host" "$port" 2>/dev/null; do
        (( i++ )) ; [[ $i -ge $tries ]] && return 1
        sleep 1
    done
    return 0
}

wait_for_service() {
    local svc="$1" tries="${2:-30}"
    local i=0
    while ! systemctl is-active --quiet "$svc" 2>/dev/null; do
        (( i++ )) ; [[ $i -ge $tries ]] && return 1
        sleep 1
    done
    return 0
}

# ── Generate random password ──────────────────────────────────
gen_password() {
    local len="${1:-24}"
    openssl rand -base64 "$len" | tr -d '/+=' | head -c "$len"
}

# ── Version compare ───────────────────────────────────────────
ver_ge() {
    # ver_ge "1.20" "1.9" → true (1.20 >= 1.9)
    printf '%s\n%s\n' "$2" "$1" | sort -V | head -1 | grep -qF "$2"
}

# ── Detect system disk (exclude from storage wizard) ──────────
get_system_disk() {
    lsblk -no pkname "$(findmnt -n -o SOURCE /)" 2>/dev/null \
        | head -1 | sed 's/[0-9]*$//' \
        | xargs -I{} echo "/dev/{}"
}
