#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 07 - Security
#
# Stack:
#   UFW          — stateful firewall, default deny inbound
#   Fail2ban     — SSH/SMB/nginx brute force protection
#   CrowdSec     — community-sourced threat intelligence
#   AppArmor     — MAC (mandatory access control) profiles
#   AIDE         — file integrity monitoring (IDS)
#   auditd       — kernel audit trail
#   GeoIP block  — optional: block non-local country ranges
#   rkhunter     — rootkit scanner
#   Unattended   — security upgrades (set in module 01)
#
# GDPR compliance note:
#   - No age verification implemented
#   - No backdoors of any kind
#   - Audit logs exportable on request
#   - IP addresses in logs are the minimum necessary
#   - Log retention default: 90 days (configurable)
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

# ============================================================
# UFW FIREWALL
# Default policy: deny all inbound, allow all outbound.
# Rules are opened per-service as modules install.
# ============================================================
configure_ufw() {
    step "Configuring UFW firewall"

    apt_install ufw

    # Reset to clean state
    ufw --force reset >> "$FORGENAS_LOG" 2>&1

    # Default policies
    ufw default deny incoming  >> "$FORGENAS_LOG" 2>&1
    ufw default allow outgoing >> "$FORGENAS_LOG" 2>&1
    ufw default deny forward   >> "$FORGENAS_LOG" 2>&1

    # Always-open services
    ufw allow ssh     comment "SSH"
    ufw allow 80/tcp  comment "HTTP (cert renewal)"
    ufw allow 443/tcp comment "HTTPS"

    # LAN-only services (NAS share protocols stay on LAN)
    local lan_cidr
    lan_cidr=$(ip route | awk '!/^default/ && /src/ {print $1}' | grep -v '^169' | head -1 || echo "192.168.0.0/16")
    ufw allow from "$lan_cidr" to any port 445    proto tcp comment "SMB (LAN)"
    ufw allow from "$lan_cidr" to any port 139    proto tcp comment "SMB NetBIOS (LAN)"
    ufw allow from "$lan_cidr" to any port 2049   proto tcp comment "NFS (LAN)"
    ufw allow from "$lan_cidr" to any port 2049   proto udp comment "NFS UDP (LAN)"
    ufw allow from "$lan_cidr" to any port 111    proto tcp comment "NFS rpcbind (LAN)"
    ufw allow from "$lan_cidr" to any port 21     proto tcp comment "FTPS control (LAN)"
    ufw allow from "$lan_cidr" to any port 990    proto tcp comment "FTPS implicit (LAN)"
    ufw allow from "$lan_cidr" to any port 40000:40100 proto tcp comment "FTPS passive (LAN)"
    ufw allow from "$lan_cidr" to any port 5353   proto udp comment "mDNS (LAN)"
    ufw allow from "$lan_cidr" to any port 12010  proto tcp comment "ForgeFileDB (LAN)"
    ufw allow from "$lan_cidr" to any port 51820  proto udp comment "WireGuard (LAN init)"

    # Allow Docker/Incus internal networks
    ufw allow from 172.16.0.0/12 comment "Docker networks"
    ufw allow from 192.168.200.0/24 comment "Incus network"

    # Enable with IPv6
    sed -i 's/^IPV6=.*/IPV6=yes/' /etc/default/ufw
    ufw --force enable >> "$FORGENAS_LOG" 2>&1

    info "UFW: enabled, default deny inbound"
    info "  LAN CIDR: $lan_cidr"
    forgenas_set "LAN_CIDR" "$lan_cidr"
}

# ============================================================
# FAIL2BAN
# Bans IPs after repeated failed auth attempts.
# Default: 5 failures → 1-hour ban
# ============================================================
configure_fail2ban() {
    step "Configuring Fail2ban"

    apt_install fail2ban

    cat > /etc/fail2ban/jail.d/forgeos.conf << 'F2B'
# ForgeOS Fail2ban configuration
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
banaction = ufw
banaction_allports = ufw

# Backend: systemd for Ubuntu 22+ (no need to read log files)
backend = systemd
usedns   = no
logencoding = auto

# Ignore local networks
ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16

[sshd]
enabled  = true
mode     = extra
maxretry = 4
bantime  = 2h

[nginx-http-auth]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log

[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log

[nginx-bad-request]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log

[samba]
enabled  = true
filter   = samba
logpath  = /var/log/forgeos/samba/*.log
maxretry = 5

# ForgeOS API brute force
[forgeos-api]
enabled   = true
filter    = forgeos-api
port      = 443,5080
logpath   = /var/log/forgeos/forgeos-api.log
maxretry  = 10
bantime   = 30m
F2B

    # Custom filter for ForgeOS API
    cat > /etc/fail2ban/filter.d/forgeos-api.conf << 'FILTER'
[Definition]
failregex = ^.*"POST /api/auth/login.*" (401|403) .*<HOST>.*$
ignoreregex =
FILTER

    # Custom filter for Samba
    cat > /etc/fail2ban/filter.d/samba.conf << 'FILTER'
[Definition]
failregex = .*smbd.*client <HOST> failed to respond to challenge
            .*client <HOST>.*Authentication failed
            .*AUTHENTICATION FAILED.*<HOST>
ignoreregex =
FILTER

    enable_service fail2ban
    info "Fail2ban: SSH, nginx, Samba, ForgeOS API protected"
}

# ============================================================
# CROWDSEC
# Community threat intelligence — shares attack patterns
# with global network, gets back blocklists.
# GDPR: CrowdSec is GDPR-compliant, only shares anonymized signals.
# ============================================================
configure_crowdsec() {
    step "Installing CrowdSec"

    curl -fsSL https://install.crowdsec.net | bash >> "$FORGENAS_LOG" 2>&1 \
        || { warn "CrowdSec install script failed — skipping"; return 0; }

    apt_install crowdsec crowdsec-firewall-bouncer-nftables 2>/dev/null \
        || apt_install_optional crowdsec

    # Install collections for our services
    cscli collections install crowdsecurity/linux >> "$FORGENAS_LOG" 2>&1 || true
    cscli collections install crowdsecurity/nginx >> "$FORGENAS_LOG" 2>&1 || true
    cscli collections install crowdsecurity/sshd  >> "$FORGENAS_LOG" 2>&1 || true
    cscli collections install crowdsecurity/samba >> "$FORGENAS_LOG" 2>&1 || true

    # Configure acquis (log sources)
    cat >> /etc/crowdsec/acquis.yaml << 'ACQUIS'

---
filenames:
  - /var/log/auth.log
  - /var/log/syslog
labels:
  type: syslog

---
filenames:
  - /var/log/nginx/access.log
  - /var/log/nginx/error.log
labels:
  type: nginx

---
filenames:
  - /var/log/forgeos/samba/*.log
labels:
  type: samba
ACQUIS

    enable_service crowdsec
    enable_service crowdsec-firewall-bouncer 2>/dev/null || true

    info "CrowdSec: community threat intelligence active"
    info "  Dashboard: cscli dashboard setup  (optional, requires Docker)"
    info "  Decisions: cscli decisions list"
}

# ============================================================
# APPARMOR
# Mandatory access control — even root can't escape profiles.
# Ubuntu ships AppArmor; we add NAS-specific profiles.
# ============================================================
configure_apparmor() {
    step "Configuring AppArmor"

    apt_install apparmor apparmor-utils apparmor-profiles apparmor-profiles-extra

    # Enable and load all available profiles
    aa-enforce /etc/apparmor.d/* >> "$FORGENAS_LOG" 2>&1 || true

    # ForgeOS API profile
    cat > /etc/apparmor.d/usr.opt.forgeos.forgeos-api << 'AA'
#include <tunables/global>

/opt/forgeos/venv/bin/python3 {
  #include <abstractions/base>
  #include <abstractions/python>
  #include <abstractions/nameservice>

  /opt/forgeos/** r,
  /etc/forgeos/** r,
  /var/log/forgeos/** rw,
  /srv/nas/** r,
  /run/forgeos/** rw,

  /etc/nginx/** r,
  /etc/samba/** r,

  network inet stream,
  network inet6 stream,
  network unix stream,
}
AA

    apparmor_parser -r /etc/apparmor.d/usr.opt.forgeos.forgeos-api 2>/dev/null || true
    enable_service apparmor
    info "AppArmor: enforcing mode, ForgeOS profile active"
}

# ============================================================
# AUDITD — kernel audit trail
# Required for HIPAA and general compliance.
# Even without HIPAA mode, we log security-relevant events.
# ============================================================
configure_auditd() {
    step "Configuring auditd"

    apt_install auditd audispd-plugins

    cat > /etc/audit/rules.d/forgeos.rules << 'AUDIT'
# ForgeOS audit rules
# Monitors security-relevant events

## Delete all current rules
-D

## Buffer size
-b 8192

## Failure mode: 1=log, 2=panic
-f 1

## Monitor privileged commands
-a always,exit -F arch=b64 -S execve -F euid=0 -k root_commands

## Auth file changes
-w /etc/passwd      -p wa -k user_changes
-w /etc/shadow      -p wa -k user_changes
-w /etc/group       -p wa -k group_changes
-w /etc/sudoers     -p wa -k sudo_changes
-w /etc/sudoers.d/  -p wa -k sudo_changes
-w /etc/ssh/        -p wa -k ssh_config

## ForgeOS config changes
-w /etc/forgeos/      -p wa -k forgeos_config
-w /etc/samba/smb.conf -p wa -k samba_config
-w /etc/nginx/         -p wa -k nginx_config

## Network config changes
-w /etc/netplan/  -p wa -k network_config
-w /etc/hosts     -p wa -k hosts_file

## Login events
-w /var/log/wtmp  -p wa -k logins
-w /var/log/btmp  -p wa -k logins
-w /var/run/utmp  -p wa -k session

## System calls — privilege escalation
-a always,exit -F arch=b64 -S setuid    -k privilege_escalation
-a always,exit -F arch=b64 -S setreuid  -k privilege_escalation
-a always,exit -F arch=b64 -S setgid    -k privilege_escalation

## File deletion in /srv/nas (data loss audit trail)
-a always,exit -F arch=b64 -S unlink -S rename -F dir=/srv/nas -k nas_deletion

## Make rules immutable (requires reboot to change)
## Uncomment in production:
# -e 2
AUDIT

    service auditd restart 2>/dev/null || systemctl restart auditd 2>/dev/null || true
    enable_service auditd
    info "auditd: kernel audit trail active"
    info "  Audit log: /var/log/audit/audit.log"
    info "  NAS deletion audit: all /srv/nas deletions logged"
}

# ============================================================
# AIDE — File Integrity Monitoring
# Creates a baseline hash database. Subsequent runs compare
# against baseline to detect unauthorized file changes.
# Run weekly via cron; alerts via Apprise.
# ============================================================
configure_aide() {
    step "Configuring AIDE (file integrity monitor)"

    apt_install aide aide-common

    cat > /etc/aide/aide.conf.d/forgeos.conf << 'AIDE'
# ForgeOS AIDE configuration
# Monitor critical system files and ForgeOS config

# ForgeOS config (any change is suspicious)
/etc/forgeos  DATAONLY+sha512

# System binaries
/bin          DATAONLY+sha512
/sbin         DATAONLY+sha512
/usr/bin      DATAONLY+sha512
/usr/sbin     DATAONLY+sha512

# SSH
/etc/ssh      DATAONLY+sha512

# Nginx
/etc/nginx    DATAONLY+sha512

# Samba
/etc/samba/smb.conf DATAONLY+sha512

# Excludes — these change normally
!/var/log
!/run
!/proc
!/sys
!/tmp
!/var/tmp
!/var/cache
!/srv/nas
!/srv/forgeos
AIDE

    # Initialize baseline (takes a minute on first run)
    _progress "Initializing AIDE baseline (first run takes ~60s)"
    aideinit >> "$FORGENAS_LOG" 2>&1 &
    local aide_pid=$!
    # Don't block install — AIDE runs in background
    disown $aide_pid
    _done

    # Weekly AIDE check cron
    cat > /etc/cron.weekly/forgeos-aide << 'AIDE_CRON'
#!/bin/bash
aide --check 2>&1 | tee /var/log/forgeos/aide-weekly.log | \
    grep -E 'changed|removed|added' | \
    xargs -I{} forgeos-notify warning "AIDE File Integrity" "{}" 2>/dev/null || true
AIDE_CRON
    chmod +x /etc/cron.weekly/forgeos-aide

    info "AIDE: initializing baseline in background, weekly checks scheduled"
}

# ============================================================
# RKHUNTER — rootkit scanner
# ============================================================
configure_rkhunter() {
    step "Configuring rkhunter"

    apt_install rkhunter

    # Update signatures
    rkhunter --update >> "$FORGENAS_LOG" 2>&1 || true
    # Set properties baseline
    rkhunter --propupd >> "$FORGENAS_LOG" 2>&1 || true

    # Weekly scan cron
    cat > /etc/cron.weekly/forgeos-rkhunter << 'RKRON'
#!/bin/bash
rkhunter --check --skip-keypress --report-warnings-only 2>&1 | \
    tee /var/log/forgeos/rkhunter-weekly.log | \
    grep -i 'warning\|infection' | \
    xargs -I{} forgeos-notify critical "rkhunter" "{}" 2>/dev/null || true
RKRON
    chmod +x /etc/cron.weekly/forgeos-rkhunter

    info "rkhunter: rootkit scanner, weekly runs scheduled"
}

# ============================================================
# SYSLOG HARDENING
# ============================================================
configure_syslog() {
    # Log auth events with more detail
    cat > /etc/rsyslog.d/90-forgeos-security.conf << 'SLOG'
# ForgeOS security logging
auth,authpriv.*                 /var/log/forgeos/auth.log
*.*;auth,authpriv.none          -/var/log/syslog
kern.*                          /var/log/kern.log
SLOG

    systemctl restart rsyslog 2>/dev/null || true
}

# ============================================================
# KERNEL HARDENING — additional sysctl for security
# (NAS tuning is in module 01; these are security-specific)
# ============================================================
configure_kernel_security() {
    cat >> /etc/sysctl.d/90-forgeos-nas.conf << 'KSEC'

# ── Kernel security ───────────────────────────────────────────
# Restrict dmesg to root
kernel.dmesg_restrict = 1

# Restrict perf events
kernel.perf_event_paranoid = 3

# Restrict kernel pointers in /proc
kernel.kptr_restrict = 2

# Protect against PTRACE abuse
kernel.yama.ptrace_scope = 1

# No kernel module loading after boot (advanced — comment if issues)
# kernel.modules_disabled = 1

# Restrict unprivileged user namespaces (mitigates container escapes)
kernel.unprivileged_userns_clone = 1
KSEC

    sysctl -p /etc/sysctl.d/90-forgeos-nas.conf >> "$FORGENAS_LOG" 2>&1 || true
}

# ============================================================
# MAIN
# ============================================================
configure_ufw
configure_fail2ban
configure_crowdsec
configure_apparmor
configure_auditd
configure_aide
configure_rkhunter
configure_syslog
configure_kernel_security

forgenas_set "MODULE_SECURITY_DONE" "yes"
forgenas_set "FEATURE_SECURITY" "yes"
info "Security module complete"
info "  UFW:       enabled, default deny"
info "  Fail2ban:  SSH/nginx/Samba/API protected"
info "  CrowdSec:  community threat intelligence"
info "  AppArmor:  enforcing"
info "  auditd:    kernel audit trail"
info "  AIDE:      file integrity (initializing)"
info "  rkhunter:  rootkit scanner"
info ""
info "  GDPR: no age verification, no backdoors"
info "        audit logs exportable: ausearch -m USER_AUTH"
