#!/usr/bin/env bash
# ============================================================
# ForgeOS lib/common.sh — Shared functions for all modules
# Source this at the top of every module:
#   source "$(dirname "$0")/../lib/common.sh"
# ============================================================
set -euEo pipefail   # -E (errtrace): ERR trap must fire inside functions too

# ── Colors ──────────────────────────────────────────────────
BOLD="\033[1m"
NC="\033[0m"
GREEN="\033[38;5;71m"
YELLOW="\033[38;5;214m"
RED="\033[38;5;196m"
ORANGE="\033[38;5;208m"
# shellcheck disable=SC2034
BLUE="\033[38;5;68m"  # reserved for future use
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
    _FORGEOS_DYING=1
    echo -e "\n  ${RED}✗ FATAL:${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FATAL: $1" >> "$FORGENAS_LOG"
    echo ""
    echo "  Log: $FORGENAS_LOG"
    exit 1
}

# ── Error trap (IH-001) ──────────────────────────────────────
# Without this, any unguarded non-zero return under `set -euo pipefail`
# kills the installer SILENTLY — no message, the log just stops. That
# made a real Proxmox-LXC failure undiagnosable (died mid hardware
# detection with no error line). This trap turns every such death into a
# logged FATAL with the exact file, line, command, and exit code.
#
# Guards against recursion and against firing on an intentional `exit 1`
# from die() (which sets _FORGEOS_DYING=1 first).
_FORGEOS_DYING=0
_forgeos_err_trap() {
    local exit_code=$?
    local line_no=${1:-?}
    local cmd=${2:-?}
    [[ "$_FORGEOS_DYING" == "1" ]] && return        # die() already handled it
    [[ "$exit_code" -eq 0 ]] && return
    echo -e "\n  ${RED}✗ FATAL:${NC} installer aborted unexpectedly" >&2
    echo -e "    ${DIM}at ${BASH_SOURCE[1]:-?}:${line_no}, command: ${cmd}${NC}" >&2
    echo -e "    ${DIM}exit code: ${exit_code}${NC}" >&2
    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FATAL: aborted at ${BASH_SOURCE[1]:-?}:${line_no}"
        echo "    command: ${cmd}"
        echo "    exit code: ${exit_code}"
    } >> "$FORGENAS_LOG"
}
# Arm it. $LINENO and BASH_COMMAND are captured at trap time.
trap '_forgeos_err_trap "$LINENO" "$BASH_COMMAND"' ERR

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
# Supported (as of 2026):
#   Ubuntu 24.04 LTS or newer
#   Debian 12 (bookworm) or newer
#
# Rationale: pyproject.toml declares requires-python = ">=3.11", which
# rules out Ubuntu 22.04 (ships Python 3.10). Ubuntu 24.04 LTS (Apr 2024)
# ships Python 3.12 and is supported by Canonical through 2029. Debian 12
# (Jun 2023) ships Python 3.11.
#
# Reads /etc/os-release directly (always present on systemd) — lsb_release
# is not always installed on minimal images.
require_ubuntu_debian() {
    if [[ ! -r /etc/os-release ]]; then
        die "Cannot read /etc/os-release — this installer requires a systemd-based Linux (Ubuntu 24.04+ or Debian 12+)."
    fi
    # shellcheck source=/dev/null
    . /etc/os-release
    local id="${ID:-unknown}"
    # VERSION_ID is "24.04" on Ubuntu, "12" on Debian
    local ver_major
    ver_major="${VERSION_ID%%.*}"

    case "$id" in
        ubuntu)
            if [[ "$ver_major" -lt 24 ]]; then
                die "ForgeOS requires Ubuntu 24.04 LTS or newer. Found: ${PRETTY_NAME:-Ubuntu $VERSION_ID}.

  Ubuntu 22.04 ships Python 3.10; ForgeOS requires Python 3.11+
  (see pyproject.toml). Either upgrade to 24.04 or install
  Python 3.11+ from deadsnakes PPA and re-run with PYTHON=python3.11."
            fi
            ;;
        debian)
            if [[ "$ver_major" -lt 12 ]]; then
                die "ForgeOS requires Debian 12 (bookworm) or newer. Found: ${PRETTY_NAME:-Debian $VERSION_ID}."
            fi
            ;;
        *)
            die "ForgeOS requires Ubuntu 24.04+ or Debian 12+. Detected ID=$id (${PRETTY_NAME:-unknown})."
            ;;
    esac
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
    # Secrets (JWT secret, DB passwords, admin creds) are written here.
    # Keep it root-only so they are never world/group-readable at rest,
    # including the window before 99-finalize tightens perms.
    chmod 600 "$FORGENAS_CONFIG"
}

forgenas_get() {
    local key="$1" default="${2:-}"
    # shellcheck source=/dev/null
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
# A connectivity preflight that false-negatives bricks the whole install,
# so this is deliberately forgiving:
#   - Tries several well-known hosts; ANY one succeeding means "online".
#   - Each probe retries once and uses a short *connect* timeout (not just
#     a total timeout), so a single slow/dead endpoint can't burn the
#     whole budget.
#   - Hosts that dual-stack to IPv6 (e.g. deb.debian.org via Fastly) would
#     otherwise stall on containers with no IPv6 route until the timeout
#     expired. We probe an explicit mix and let curl fall back fast.
# Override the host list with FORGEOS_NET_CHECK_HOSTS (space-separated)
# or skip entirely (air-gapped mirrors) with FORGEOS_SKIP_NET_CHECK=1.
check_internet() {
    if [[ "${FORGEOS_SKIP_NET_CHECK:-0}" == "1" ]]; then
        warn "Skipping internet check (FORGEOS_SKIP_NET_CHECK=1)"
        return 0
    fi

    local hosts="${FORGEOS_NET_CHECK_HOSTS:-\
https://deb.debian.org/debian/ \
https://cloudflare.com/cdn-cgi/trace \
https://www.google.com/generate_204 \
http://archive.ubuntu.com/ubuntu/}"

    local url
    for url in $hosts; do
        # Two attempts per host:
        #   1. Default (honors IPv6 if the host has a working v6 route).
        #   2. --ipv4 forced, for IPv4-only hosts whose mirror resolves to
        #      IPv6-only records (e.g. deb.debian.org via Fastly) — without
        #      this, the doomed v6 connect burns the timeout and the whole
        #      preflight false-negatives. This was the original bug.
        # --connect-timeout caps the TCP/TLS handshake (the part that stalls
        # on a dead route); --max-time caps the whole probe.
        if curl -sf --connect-timeout 4 --max-time 8 \
                "$url" > /dev/null 2>&1; then
            return 0
        fi
        if curl -sf --ipv4 --connect-timeout 4 --max-time 8 \
                "$url" > /dev/null 2>&1; then
            return 0
        fi
    done

    die "No internet connection (tried multiple hosts). ForgeOS installer \
requires internet access. If your network is fine but this still fails, your \
mirror may be IPv6-only on an IPv4-only host; set \
FORGEOS_NET_CHECK_HOSTS to a reachable URL, or FORGEOS_SKIP_NET_CHECK=1 to \
bypass. Log: $FORGENAS_LOG"
}

# ── IPv4 preference for broken-IPv6 hosts ─────────────────────
# Many containers (notably Proxmox LXCs) have NO working IPv6 route, yet
# Debian/Ubuntu mirrors (Fastly) frequently resolve to IPv6-only records.
# Result: every apt fetch first tries IPv6, stalls until timeout, then
# falls back — turning a 2-minute install into a crawl, or failing on
# stricter timeouts. We already work around this in check_internet for
# the probe; this does the same for apt, but ONLY when IPv6 is actually
# broken here, so hosts with working IPv6 are left untouched.
ensure_ipv4_apt_if_needed() {
    # If a quick IPv6-forced probe to a known dual-stack host succeeds,
    # IPv6 works — leave everything alone.
    if curl -sf --ipv6 --connect-timeout 3 --max-time 5 \
            https://deb.debian.org/debian/ > /dev/null 2>&1; then
        return 0
    fi
    # IPv6 is unavailable/broken. Tell apt to prefer IPv4 for this system
    # so package fetches don't stall on doomed v6 connects. Idempotent.
    local conf="/etc/apt/apt.conf.d/99forgeos-force-ipv4"
    if [[ ! -f "$conf" ]]; then
        echo 'Acquire::ForceIPv4 "true";' > "$conf"
        warn "No working IPv6 detected — set apt to prefer IPv4 ($conf)"
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
    local root_dev
    root_dev="$(findmnt -n -o SOURCE / 2>/dev/null)" || return 1
    # pkname gives the kernel name of the parent device.
    # For NVMe (nvme0n1p2 → nvme0n1) and SATA (sda2 → sda) this is correct.
    local parent
    parent="$(lsblk -no pkname "$root_dev" 2>/dev/null | head -1)" || return 1
    [[ -n "$parent" ]] || return 1
    echo "/dev/$parent"
}
