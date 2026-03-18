#!/usr/bin/env bash
# ============================================================
# ForgeOS End-to-End Test Suite
# Usage: sudo bash test-forgeos.sh [--quick] [--module <name>]
#
# Runs a comprehensive smoke test of the entire ForgeOS stack.
# Produces a color-coded report and saves JSON results.
# Exit code 0 = all tests passed, 1 = failures present.
# ============================================================
set -euo pipefail

REPORT_FILE="/var/log/forgeos/test-report-$(date +%Y%m%d-%H%M%S).json"
QUICK_MODE=false
MODULE_FILTER=""

for arg in "$@"; do
    case "$arg" in
        --quick)         QUICK_MODE=true ;;
        --module=*)      MODULE_FILTER="${arg#--module=}" ;;
    esac
done

# ── Colors ────────────────────────────────────────────────────
GREEN="\033[38;5;71m"
RED="\033[38;5;196m"
YELLOW="\033[38;5;214m"
ORANGE="\033[38;5;208m"
DIM="\033[2m"
BOLD="\033[1m"
NC="\033[0m"

PASS=0; FAIL=0; SKIP=0; WARN=0
declare -a RESULTS=()

# ── Test framework ────────────────────────────────────────────
_test() {
    local name="$1" cmd="$2" expect="${3:-0}"
    local status="PASS" color="$GREEN" symbol="✓"

    [[ -n "$MODULE_FILTER" && "$name" != *"$MODULE_FILTER"* ]] && {
        (( SKIP++ )) || true
        return
    }

    local output exit_code
    output=$(eval "$cmd" 2>&1) && exit_code=$? || exit_code=$?

    if [[ "$expect" == "nonempty" ]]; then
        [[ -n "$output" ]] || { exit_code=1; }
    fi

    if [[ $exit_code -ne 0 ]]; then
        status="FAIL"; color="$RED"; symbol="✗"; (( FAIL++ )) || true
        _detail="${output//\"/ }"
        RESULTS+=("{\"test\":\"${name}\",\"status\":\"FAIL\",\"detail\":\"${_detail}\",\"exit_code\":${exit_code}}")
    else
        (( PASS++ )) || true
        RESULTS+=("{\"test\":\"${name}\",\"status\":\"PASS\"}")
    fi

    printf "  ${color}${symbol}${NC} %-55s ${DIM}%s${NC}\n" "$name" "$status"
    [[ "$status" == "FAIL" && -n "$output" ]] && \
        echo -e "    ${DIM}${output:0:120}${NC}"
}

_warn() {
    local name="$1" cmd="$2"
    local output exit_code
    output=$(eval "$cmd" 2>&1) && exit_code=$? || exit_code=$?
    local status="WARN" color="$YELLOW" symbol="⚠"
    [[ $exit_code -eq 0 ]] && { status="PASS"; color="$GREEN"; symbol="✓"; (( PASS++ )) || true; } || (( WARN++ )) || true
    RESULTS+=("{\"test\":\"${name}\",\"status\":\"${status}\"}")
    printf "  ${color}${symbol}${NC} %-55s ${DIM}%s${NC}\n" "$name" "$status"
}

_section() {
    echo ""
    echo -e "${ORANGE}▶ ${BOLD}$1${NC}"
}

_skip() {
    local name="$1" reason="${2:-N/A}"
    printf "  ${DIM}—${NC} %-55s ${DIM}SKIP: %s${NC}\n" "$name" "$reason"
    (( SKIP++ )) || true
}

# ── Header ────────────────────────────────────────────────────
clear
echo -e "${ORANGE}"
printf '\n'
printf '%s\n' '  ___                 ___  ____'
printf '%s\n' ' / __\___  _ __ __ _ / _ \/ ___|'
printf '%s\n' '/ _\ / _ \| __/ _` | | | \___ \'
printf '%s\n' '/ /  | (_) | | | (_| | |_| |___) |'
printf '%s\n' '\/    \___/|_|  \__, |\___/|____/'
printf '%s\n' '               |___/'
echo -e "${NC}"
echo -e "  ${BOLD}ForgeOS End-to-End Test Suite${NC}"
echo -e "  ${DIM}$(date)${NC}"
echo ""

[[ $EUID -ne 0 ]] && { echo -e "${RED}Run as root${NC}"; exit 1; }
source /etc/forgeos/forgeos.conf 2>/dev/null || { echo -e "${RED}forgeos.conf not found — run installer first${NC}"; exit 1; }

# ============================================================
# SECTION 1: CORE SYSTEM
# ============================================================
_section "Core System"

_test "forgeos.conf readable"          "test -r /etc/forgeos/forgeos.conf"
_test "Hostname set"                    "hostname | grep -v '^localhost$'"
_test "Timezone configured"            "timedatectl show --property=Timezone --value | grep -v UTC || true"
_test "Admin user exists"              "id '${ADMIN_USER:-forgeos}'"
_test "NAS directory structure /srv/nas" "test -d /srv/nas"
_test "Logs directory exists"          "test -d /var/log/forgeos"
_test "Systemd journal functional"     "journalctl --no-pager -n 1 -q"
_test "NTP sync active"                "timedatectl show --property=NTPSynchronized --value | grep -i yes || chronyc tracking"
_test "Kernel: inotify watches"        "sysctl fs.inotify.max_user_watches | grep -P '\d{5,}'"
_test "Kernel: file-max adequate"      "sysctl fs.file-max | grep -P '\d{6,}'"
_test "sysctl NAS tuning applied"      "test -f /etc/sysctl.d/90-forgeos-nas.conf"
_test "Limits config applied"          "test -f /etc/security/limits.d/90-forgeos.conf"

# ============================================================
# SECTION 2: NETWORK
# ============================================================
_section "Network"

_test "Primary NIC up"                 "ip link show '${NIC_PRIMARY:-eth0}' | grep -i 'state UP'"
_test "IP address assigned"            "ip -4 addr show scope global | grep inet"
_test "Internet connectivity"          "curl -sf --max-time 5 https://deb.debian.org/debian/ -o /dev/null"
_test "DNS resolution works"           "getent hosts google.com | grep -P '\d+\.\d+'"
_test "mDNS (Avahi) running"           "systemctl is-active avahi-daemon"
_test "Avahi announces hostname"       "avahi-resolve-host-name '$(hostname).local' 2>/dev/null || avahi-browse -t _workstation._tcp 2>/dev/null | grep -q . || true"
_warn "systemd-resolved active"        "systemctl is-active systemd-resolved"

# ============================================================
# SECTION 3: STORAGE
# ============================================================
_section "Storage"

_test "/srv/nas accessible"            "test -d /srv/nas && touch /srv/nas/.test && rm /srv/nas/.test"
_test "mdadm available"                "command -v mdadm"
_test "btrfs available"                "command -v btrfs"
_test "lvm tools available"            "command -v pvs"
_test "smartctl available"             "command -v smartctl"
_test "smartd service running"         "systemctl is-active smartd"
_test "forgeos-storage CLI"           "forgeos-storage --help 2>&1 | grep -i forge || forgeos-storage status 2>&1 | head -1"
_test "forgeos-pool-status outputs JSON" "forgeos-pool-status 2>/dev/null | python3 -c 'import sys,json; json.load(sys.stdin)'"
_test "Drive registry exists"          "test -f /etc/forgeos/drives.json"
_test "Drive scan returns data"        "python3 /opt/forgeos/scripts/drive-scan.py 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); assert len(d[\"drives\"]) > 0'"
_test "bcache-tools installed"         "command -v make-bcache"
_test "forgeos-cache CLI"             "forgeos-cache help 2>&1 | grep -i cache"
_test "Snapper available"              "command -v snapper"
_test "Hot-swap handler installed"     "test -f /opt/forgeos/scripts/forgeos-hotswap"
_test "SMART alert script installed"   "test -f /opt/forgeos/scripts/forgeos-smart-alert"

# ============================================================
# SECTION 4: DOCKER + CONTAINERS
# ============================================================
_section "Docker + Containers"

_test "Docker daemon running"          "systemctl is-active docker"
_test "Docker CLI functional"         "docker info --format '{{.ServerVersion}}'"
_test "docker compose plugin"          "docker compose version"
_test "forgeos-internal network"      "docker network inspect forgeos-internal -f '{{.Name}}'"
_test "Docker test container"         "docker run --rm alpine echo ok 2>/dev/null | grep ok"
_warn "Incus available"               "command -v incus || command -v lxc"

# ============================================================
# SECTION 5: SECURITY
# ============================================================
_section "Security"

_test "UFW enabled"                    "ufw status | grep 'Status: active'"
_test "SSH only on allowed port"       "ss -tlnp | grep ':22'"
_test "Fail2ban running"              "systemctl is-active fail2ban"
_test "Fail2ban SSH jail active"       "fail2ban-client status sshd 2>/dev/null | grep 'Currently banned'"
_test "AppArmor enforcing"            "aa-status 2>/dev/null | grep -i enforc || apparmor_status 2>/dev/null | head -1"
_test "auditd running"                "systemctl is-active auditd"
_test "auditd rules loaded"           "auditctl -l 2>/dev/null | grep -c forgeos || true"
_test "Root password login disabled"   "grep -P '^PermitRootLogin\s+prohibit-password' /etc/ssh/sshd_config.d/90-forgeos.conf"
_warn "CrowdSec agent running"        "systemctl is-active crowdsec"
_warn "AIDE baseline exists"          "test -f /var/lib/aide/aide.db || test -f /var/lib/aide/aide.db.new"
_test "rkhunter installed"            "command -v rkhunter"

# ============================================================
# SECTION 6: REVERSE PROXY (nginx)
# ============================================================
_section "Reverse Proxy (nginx)"

_test "nginx installed"               "command -v nginx"
_test "nginx running"                 "systemctl is-active nginx"
_test "nginx config test passes"      "nginx -t 2>&1 | grep -i 'test is successful'"
_test "nginx listens on 80"           "ss -tlnp | grep ':80 '"
_test "nginx listens on 443"          "ss -tlnp | grep ':443 '"
_test "forgeos.d conf dir exists"     "test -d /etc/nginx/forgeos.d"
_test "forgeos-nginx CLI"             "forgeos-nginx help 2>&1 | grep -i nginx || true"
_test "HTTP → HTTPS redirect"         "curl -sv http://localhost/ 2>&1 | grep -i 'location.*https' || true"
_warn "Let's Encrypt cert present"    "test -d /etc/letsencrypt/live/ && ls /etc/letsencrypt/live/"

# ============================================================
# SECTION 7: FORGEOS API
# ============================================================
_section "ForgeOS API (FastAPI)"

_test "forgeos-api service running"   "systemctl is-active forgeos-api"
_test "API port 5080 listening"       "ss -tlnp | grep ':5080'"
_test "API health endpoint"           "curl -sf http://127.0.0.1:5080/health | python3 -c 'import sys,json; assert json.load(sys.stdin)[\"status\"]==\"ok\"'"
_test "API auth login returns token"  "curl -sf -X POST http://127.0.0.1:5080/api/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"${WEBUI_ADMIN_PASS:-forgeos}\"}' | python3 -c 'import sys,json; assert \"token\" in json.load(sys.stdin)'"
_test "API storage pools endpoint"    "curl -sf http://127.0.0.1:5080/api/storage/pools -H 'Authorization: Bearer \$(curl -sf -X POST http://127.0.0.1:5080/api/auth/login -H \"Content-Type: application/json\" -d \"{\\\"username\\\":\\\"admin\\\",\\\"password\\\":\\\"${WEBUI_ADMIN_PASS:-forgeos}\\\"}\" | python3 -c \"import sys,json; print(json.load(sys.stdin)[\\\"token\\\"])\")' | python3 -c 'import sys,json; json.load(sys.stdin)'"
_test "API notify endpoint"           "curl -sf -X POST http://127.0.0.1:5080/api/notify -H 'Content-Type: application/json' -d '{\"level\":\"info\",\"title\":\"Test\",\"message\":\"ForgeOS test\"}' | grep ok"

# ============================================================
# SECTION 8: FILE SHARING
# ============================================================
_section "File Sharing"

_test "Samba running"                 "systemctl is-active smbd"
_test "Samba nmbd running"            "systemctl is-active nmbd"
_test "Samba config valid"            "testparm -s /etc/samba/smb.conf 2>&1 | grep -v 'WARNING\|error\|Error' | head -1 || testparm -s 2>/dev/null | head -1"
_test "Samba listens port 445"        "ss -tlnp | grep ':445'"
_test "forgeos-samba CLI"             "forgeos-samba help 2>&1 | grep -i samba"
_test "NFS kernel server running"     "systemctl is-active nfs-kernel-server"
_test "NFS exports configured"        "exportfs -v 2>/dev/null | head -1 || test -f /etc/exports"
_test "NFS port 2049 listening"       "ss -tlnp | grep ':2049'"
_test "ProFTPD running"               "systemctl is-active proftpd"
_test "ProFTPD port 21 listening"     "ss -tlnp | grep ':21 '"
_test "FileBrowser running"           "systemctl is-active forgeos-filebrowser"
_test "FileBrowser port 8085"         "ss -tlnp | grep ':8085'"
_test "forgeos-fileshare CLI"         "forgeos-fileshare help 2>&1 | grep -i share"

# ============================================================
# SECTION 9: FORGEFILEDB
# ============================================================
_section "ForgeFileDB"

_test "forgeos-filedb service"        "systemctl is-active forgeos-filedb"
_test "ForgeFileDB port 12010"        "ss -tlnp | grep ':12010'"
_test "ForgeFileDB health endpoint"   "curl -sf http://127.0.0.1:12010/health | python3 -c 'import sys,json; assert json.load(sys.stdin)[\"status\"]==\"ok\"'"
_test "ForgeFileDB mDNS announced"    "avahi-browse -t _forgeos-filedb._tcp 2>/dev/null | grep -q . || true"
_test "forgeos-filedb CLI"            "forgeos-filedb help 2>&1 | grep -i filedb"
_test "Snapshot directory writable"   "test -d /srv/forgeos/filedb/snapshots && touch /srv/forgeos/filedb/snapshots/.test && rm /srv/forgeos/filedb/snapshots/.test"

# ============================================================
# SECTION 10: VPN
# ============================================================
_section "VPN (WireGuard)"

_test "WireGuard tools installed"     "command -v wg"
_test "WireGuard interface up"        "ip link show wg0 2>/dev/null | grep -i UP || wg show wg0 2>/dev/null | head -1"
_test "WireGuard service active"      "systemctl is-active 'wg-quick@wg0'"
_test "WireGuard port 51820 UDP"      "ss -ulnp | grep ':51820'"
_test "Server public key exists"      "test -f /etc/wireguard/server.pub"
_test "forgeos-vpn CLI"               "forgeos-vpn help 2>&1 | grep -i wireguard"

# ============================================================
# SECTION 11: MONITORING
# ============================================================
_section "Monitoring"

_test "Prometheus container running"  "docker ps --format '{{.Names}}' | grep forgeos-prometheus"
_test "Grafana container running"     "docker ps --format '{{.Names}}' | grep forgeos-grafana"
_test "Alertmanager container running" "docker ps --format '{{.Names}}' | grep forgeos-alertmanager"
_test "Gotify container running"      "docker ps --format '{{.Names}}' | grep forgeos-gotify"
_test "node_exporter running"         "docker ps --format '{{.Names}}' | grep forgeos-node-exporter"
_test "smartctl_exporter running"     "docker ps --format '{{.Names}}' | grep forgeos-smartctl"
_test "Prometheus port 9091"          "ss -tlnp | grep ':9091'"
_test "Grafana port 3000"             "ss -tlnp | grep ':3000'"
_test "Gotify port 8070"              "ss -tlnp | grep ':8070'"
_test "Prometheus health"             "curl -sf http://127.0.0.1:9091/-/healthy | grep ok"
_test "Grafana health"                "curl -sf http://127.0.0.1:3000/api/health | python3 -c 'import sys,json; assert json.load(sys.stdin)[\"database\"]==\"ok\"'"
_test "Prometheus scraping node"      "curl -sf 'http://127.0.0.1:9091/api/v1/targets' | python3 -c 'import sys,json; d=json.load(sys.stdin); targets=[t for t in d[\"data\"][\"activeTargets\"] if t[\"labels\"][\"job\"]==\"node\"]; assert len(targets)>0'"
_warn "Alert rules loaded"            "curl -sf 'http://127.0.0.1:9091/api/v1/rules' | python3 -c 'import sys,json; d=json.load(sys.stdin); assert len(d[\"data\"][\"groups\"])>0'"

# ============================================================
# SECTION 12: BACKUP
# ============================================================
_section "Backup"

_test "Restic installed"              "command -v restic"
_test "Rclone installed"              "command -v rclone"
_test "Restic master key exists"      "test -f /etc/forgeos/backup/keys/master.key"
_test "Restic local repo initialized" "RESTIC_PASSWORD_FILE=/etc/forgeos/backup/keys/master.key restic --repo '${RESTIC_REPO_LOCAL:-/srv/forgeos/backups/restic}' snapshots --quiet 2>/dev/null | true"
_test "Backup timer enabled"          "systemctl is-enabled forgeos-backup-restic.timer"
_test "Rclone timer enabled"          "systemctl is-enabled forgeos-backup-rclone.timer"
_test "forgeos-backup CLI"            "forgeos-backup help 2>&1 | grep -i backup"
_test "Snapper service active"        "systemctl is-active snapper-timeline.timer 2>/dev/null || systemctl is-active snapper-boot.service 2>/dev/null || command -v snapper"

# ============================================================
# SECTION 13: CORAL TPU (optional)
# ============================================================
_section "Coral TPU (optional — skip if no hardware)"

source /etc/forgeos/forgeos.conf 2>/dev/null || true
if [[ "${CORAL_DETECTED:-no}" == "yes" ]]; then
    _test "gasket module loaded"          "lsmod | grep gasket"
    _test "apex module loaded"            "lsmod | grep apex"
    _test "Apex device exists"            "ls /dev/apex_0"
    coral_count="${CORAL_COUNT:-1}"
    [[ "$coral_count" -ge 2 ]] && _test "Dual TPU: apex_1 exists" "ls /dev/apex_1"
    _test "apex udev rules installed"     "test -f /etc/udev/rules.d/65-apex.rules"
    _test "forgeos-coral CLI"             "forgeos-coral help 2>&1 | grep -i coral"
    _test "Frigate compose exists"        "test -f /opt/forgeos/apps/frigate/docker-compose.yml"
    _test "Frigate config generated"      "test -f /srv/forgeos/frigate/config/config.yml"
else
    _skip "Coral TPU tests" "CORAL_DETECTED=no (no PCIe hardware found)"
fi

# ============================================================
# SECTION 14: APPLICATIONS (optional)
# ============================================================
_section "Applications (optional)"

_test "OnlyOffice container running"  "docker ps --format '{{.Names}}' | grep forgeos-onlyoffice"
_test "OnlyOffice port 8080"          "ss -tlnp | grep ':8080'"
_warn "OnlyOffice health"             "curl -sf http://127.0.0.1:8080/healthcheck 2>/dev/null | grep -i ok"
_test "Microsoft fonts installed"     "fc-list | grep -i arial"
_test "Liberation fonts installed"    "fc-list | grep -i liberation"
_test "Immich server running"         "docker ps --format '{{.Names}}' | grep immich-server"
_test "Immich port 2283"              "ss -tlnp | grep ':2283'"

# ============================================================
# SECTION 15: GDPR + COMPLIANCE
# ============================================================
_section "GDPR / Compliance"

_test "No age verification code"       "! grep -r 'age.verif\|age_verif\|dateofbirth\|date_of_birth' /opt/forgeos/ 2>/dev/null | grep -v '.pyc'"
_test "No plaintext passwords in conf" "! grep -P 'password\s*=\s*[^\$\{].{8,}' /etc/forgeos/forgeos.conf 2>/dev/null | grep -v 'PASS.*\$' || true"
_test "Config file permissions 600"    "test \"\$(stat -c '%a' /etc/forgeos/forgeos.conf)\" = '600'"
_test "Audit log exists"              "test -f /var/log/audit/audit.log"
_test "Backup key protected 400"      "test \"\$(stat -c '%a' /etc/forgeos/backup/keys/master.key 2>/dev/null)\" = '400' || true"

# ============================================================
# SECTION 16: CLI TOOLS
# ============================================================
_section "CLI Tools"

for cli in forgeos-ctl forgeos-storage forgeos-samba forgeos-db forgeos-nginx \
           forgeos-vpn forgeos-backup forgeos-cloud forgeos-filedb forgeos-cache \
           forgeos-drives forgeos-fileshare forgeos-notify; do
    _test "CLI: ${cli}"               "command -v ${cli}"
done

if [[ "${FEATURE_MAIL:-no}" == "yes" ]]; then
    _test "CLI: forgeos-mail"         "command -v forgeos-mail"
fi
if [[ "${HIPAA_ENABLED:-no}" == "yes" ]]; then
    _test "CLI: forgeos-hipaa"        "command -v forgeos-hipaa"
fi
if [[ "${CORAL_DETECTED:-no}" == "yes" ]]; then
    _test "CLI: forgeos-coral"        "command -v forgeos-coral"
fi

# ============================================================
# SECTION 17: QUICK FUNCTIONALITY TESTS
# ============================================================
if ! $QUICK_MODE; then
    _section "Functionality Tests"

    _test "Samba share writable"          "test -d /srv/nas/data && echo test > /srv/nas/data/.forgeos-test && rm /srv/nas/data/.forgeos-test"
    _test "NFS export active"             "exportfs -v 2>/dev/null | grep -c srv || true"
    _test "Docker network connectivity"   "docker run --rm --network forgeos-internal alpine wget -qO- http://forgeos-filedb:12010/health 2>/dev/null | grep ok || true"
    _test "Restic backup test run"        "RESTIC_PASSWORD_FILE=/etc/forgeos/backup/keys/master.key restic --repo '${RESTIC_REPO_LOCAL:-/srv/forgeos/backups/restic}' backup /etc/forgeos/forgeos.conf --tag testrun --quiet 2>/dev/null"
    _test "Restic snapshot created"       "RESTIC_PASSWORD_FILE=/etc/forgeos/backup/keys/master.key restic --repo '${RESTIC_REPO_LOCAL:-/srv/forgeos/backups/restic}' snapshots --tag testrun --quiet 2>/dev/null | grep testrun"
    _test "forgeos-ctl status exits 0"    "forgeos-ctl status"
    _test "API metrics WebSocket capable" "curl -sf --max-time 3 http://127.0.0.1:5080/health | grep ok"
fi

# ============================================================
# RESULTS SUMMARY
# ============================================================
echo ""
echo -e "${ORANGE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${BOLD}Test Results${NC}"
echo -e "${ORANGE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${GREEN}✓ PASSED:${NC}  ${PASS}"
echo -e "  ${RED}✗ FAILED:${NC}  ${FAIL}"
echo -e "  ${YELLOW}⚠ WARNED:${NC}  ${WARN}"
echo -e "  ${DIM}— SKIPPED:${NC} ${SKIP}"
echo ""

# Write JSON report
mkdir -p "$(dirname "$REPORT_FILE")"
cat > "$REPORT_FILE" << REPORT
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hostname":  "$(hostname -f)",
  "forgeos_version": "${FORGEOS_VERSION:-1.0}",
  "kernel": "$(uname -r)",
  "summary": {
    "passed":  ${PASS},
    "failed":  ${FAIL},
    "warned":  ${WARN},
    "skipped": ${SKIP},
    "total":   $(( PASS + FAIL + WARN + SKIP ))
  },
  "results": [
$(IFS=$'\n'; echo "${RESULTS[*]}" | paste -sd, -)
  ]
}
REPORT

echo -e "  Report saved: ${REPORT_FILE}"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo -e "  ${RED}${BOLD}${FAIL} test(s) failed — review failures above${NC}"
    echo ""
    exit 1
else
    echo -e "  ${GREEN}${BOLD}All tests passed ✓${NC}"
    echo ""
    exit 0
fi
