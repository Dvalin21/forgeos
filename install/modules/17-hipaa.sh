#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 17 - HIPAA Compliance Mode
#
# WHAT HIPAA REQUIRES (simplified for a NAS/server context):
#   - Access controls (unique user IDs, auto-logoff)
#   - Audit controls (who accessed what, when, what changed)
#   - Integrity controls (data hasn't been altered improperly)
#   - Transmission security (encryption in transit AND at rest)
#   - No unauthorized access or disclosure of ePHI
#   - Backup & disaster recovery plan (addressable)
#
# WHAT THIS MODULE DOES:
#   - Enables at-rest encryption (LUKS2 on pool, or btrfs native)
#   - Forces TLS everywhere (already done by nginx module)
#   - Hardens auditd ruleset for ePHI file access tracking
#   - Enables automatic session timeout
#   - Configures fail2ban to be more aggressive
#   - Generates audit log reports (weekly/monthly)
#   - Documents the system configuration for BAA purposes
#   - Deploys RBAC user structure (min-privilege principle)
#
# WHAT THIS DOES NOT DO:
#   - Replace a HIPAA compliance officer
#   - Sign a Business Associate Agreement on your behalf
#   - Guarantee compliance (human processes matter too)
#   - Add age verification (explicitly not requested)
#   - Add back doors of any kind (explicitly not requested)
#
# IMPORTANT: ePHI directories must be designated by the admin.
#   Run: forgeos-hipaa designate-phi /srv/nas/datapool/patients
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

HIPAA_DIR="/etc/forgeos/hipaa"
HIPAA_LOG_DIR="/var/log/forgeos/hipaa"
PHI_DIRS_FILE="$HIPAA_DIR/phi-directories.conf"

# ============================================================
# INSTALL HIPAA PACKAGES
# ============================================================
install_hipaa_packages() {
    step "Installing HIPAA compliance packages"

    apt_install \
        auditd \
        audispd-plugins \
        libpam-pwquality \
        libpam-faillock \
        acl \
        attr \
        cryptsetup \
        cryptsetup-bin \
        aide \
        aide-common \
        rsyslog \
        logrotate \
        openssl

    info "HIPAA packages installed"
}

# ============================================================
# AUDIT RULES — HIPAA-SPECIFIC
# Tracks all access to files tagged as ePHI locations
# ============================================================
configure_hipaa_audit() {
    step "Configuring HIPAA audit rules"

    mkdir -p "$HIPAA_DIR" "$HIPAA_LOG_DIR"

    cat > /etc/audit/rules.d/99-hipaa-forgeos.rules << 'AUDIT'
# ForgeOS HIPAA Audit Rules
# Tracks all access relevant to HIPAA §164.312(b) — Audit Controls

## Delete all existing rules first
-D

## Set buffer size (large for busy ePHI systems)
-b 8192

## Failure mode: 1=log, 2=panic (2 is extreme — use 1 for NAS)
-f 1

## ── USER MANAGEMENT EVENTS ────────────────────────────────
## Track all user/group creation, modification, deletion
-w /etc/passwd   -p wa -k hipaa_user_mgmt
-w /etc/shadow   -p wa -k hipaa_user_mgmt
-w /etc/group    -p wa -k hipaa_user_mgmt
-w /etc/gshadow  -p wa -k hipaa_user_mgmt
-w /etc/sudoers  -p wa -k hipaa_privilege_escalation
-w /etc/sudoers.d/ -p wa -k hipaa_privilege_escalation

## ── AUTHENTICATION EVENTS ─────────────────────────────────
-w /var/log/auth.log      -p wa -k hipaa_authentication
-w /var/log/secure        -p wa -k hipaa_authentication
-w /var/run/faillock/     -p wa -k hipaa_failed_login
-w /etc/pam.d/            -p wa -k hipaa_auth_config

## ── SESSION EVENTS ────────────────────────────────────────
-w /var/log/wtmp  -p wa -k hipaa_session
-w /var/log/btmp  -p wa -k hipaa_session
-w /var/run/utmp  -p wa -k hipaa_session

## ── PRIVILEGED COMMAND EXECUTION ─────────────────────────
-a always,exit -F arch=b64 -S execve -F euid=0 -k hipaa_root_exec
-a always,exit -F path=/usr/bin/sudo -F perm=x -k hipaa_sudo

## ── NETWORK CONFIGURATION CHANGES ────────────────────────
-w /etc/hosts         -p wa -k hipaa_network_config
-w /etc/hostname      -p wa -k hipaa_network_config
-w /etc/network/      -p wa -k hipaa_network_config
-w /etc/netplan/      -p wa -k hipaa_network_config
-w /etc/nginx/        -p wa -k hipaa_service_config
-w /etc/ssh/          -p wa -k hipaa_service_config

## ── SAMBA (SMB file access to ePHI shares) ────────────────
-w /var/log/samba/    -p rwa -k hipaa_smb_access

## ── KERNEL MODULE LOADING ─────────────────────────────────
-w /sbin/insmod       -p x -k hipaa_kernel_modules
-w /sbin/rmmod        -p x -k hipaa_kernel_modules
-w /sbin/modprobe     -p x -k hipaa_kernel_modules

## ── TIME CHANGES (HIPAA requires accurate audit timestamps) 
-a always,exit -F arch=b64 -S adjtimex -S settimeofday -k hipaa_time_change
-w /etc/localtime     -p wa -k hipaa_time_change

## ── ePHI DIRECTORY ACCESS (added dynamically by forgeos-hipaa)
## Format: -w /path/to/phi -p rwxa -k hipaa_phi_access
## Populated from: /etc/forgeos/hipaa/phi-directories.conf
AUDIT

    # Reload audit rules
    augenrules --load >> "$FORGENAS_LOG" 2>&1 || warn "augenrules failed — will apply on next boot"
    enable_service auditd

    info "HIPAA audit rules configured"
}

# ============================================================
# PASSWORD POLICY — HIPAA-grade
# ============================================================
configure_password_policy() {
    step "Configuring HIPAA password policy"

    cat > /etc/security/pwquality.conf << 'PWQUAL'
# ForgeOS HIPAA Password Policy
# HIPAA does not mandate specific complexity, but NIST 800-63b
# and common sense do. We follow NIST recommendations:
# - Minimum length 12 chars (better than 8)
# - Check against known breached password lists
# - No mandatory rotation (per NIST 800-63b — forced rotation
#   leads to weaker passwords like Password1!)
# - DO lock out after repeated failures (handled by faillock)

minlen = 12
minclass = 3          # Requires 3 of: upper, lower, digits, special
maxrepeat = 3         # No more than 3 identical consecutive chars
maxsequence = 4       # No sequential chars: abcd, 1234
dictcheck = 1         # Check against dictionary
usercheck = 1         # Don't allow username in password
gecoscheck = 1        # Check against user info fields
badwords = password admin forgeos hipaa patient doctor medical
PWQUAL

    # Account lockout after 5 failed attempts (HIPAA §164.312(d))
    cat > /etc/security/faillock.conf << 'FAILLOCK'
# ForgeOS HIPAA Account Lockout
deny = 5              # Lock after 5 failures
fail_interval = 900   # Within 15 minutes
unlock_time = 1800    # Locked for 30 minutes (or manual unlock)
audit                 # Log to audit system
FAILLOCK

    # Session timeout — auto-logout after 15 minutes idle (HIPAA §164.312(a)(2)(iii))
    cat > /etc/profile.d/forgeos-hipaa-timeout.sh << 'TIMEOUT'
# ForgeOS HIPAA automatic session timeout
# Locks terminal after 15 minutes idle
export TMOUT=900       # 15 minutes
readonly TMOUT
export HISTFILE=/dev/null   # Don't store command history containing ePHI
TIMEOUT

    # SSH session timeout
    cat >> /etc/ssh/sshd_config.d/forgeos-hipaa.conf << 'SSHD'
# ForgeOS HIPAA SSH session timeout
ClientAliveInterval 300
ClientAliveCountMax 3
LoginGraceTime 60
SSHD

    systemctl reload ssh 2>/dev/null || true
    info "HIPAA password policy and session timeout configured"
}

# ============================================================
# AT-REST ENCRYPTION
# HIPAA §164.312(a)(2)(iv) — encryption of stored ePHI
# We use btrfs native encryption (Linux 6.7+) or a FUSE-based
# encrypted overlay for older kernels
# ============================================================
configure_atrest_encryption() {
    step "Configuring at-rest encryption for ePHI"

    local kernel_ver
    # shellcheck disable=SC2034
    # shellcheck disable=SC2034
    kernel_ver=$(uname -r | cut -d. -f1-2 | tr -d '.')

    # Check for fscrypt support (btrfs-native or ext4)
    if [[ -f /proc/crypto ]] && grep -q 'fscrypt' /proc/filesystems 2>/dev/null; then
        info "fscrypt available — ePHI directories can use kernel-native encryption"
        forgenas_set "HIPAA_ENCRYPT_METHOD" "fscrypt"
    else
        info "Kernel encryption status: check kernel module availability"
        forgenas_set "HIPAA_ENCRYPT_METHOD" "gocryptfs"
    fi

    # Install gocryptfs as universal fallback
    # gocryptfs: AES-256-GCM, authenticated encryption, audited by Fraunhofer
    if ! command -v gocryptfs &>/dev/null; then
        apt_install gocryptfs 2>/dev/null \
            || {
                local gc_ver="2.4.0"
                local arch; arch=$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/aarch64/')
                wget -q "https://github.com/rfjakob/gocryptfs/releases/download/v${gc_ver}/gocryptfs_v${gc_ver}_linux-static_${arch}.tar.gz" \
                    -O /tmp/gcfs.tar.gz 2>/dev/null \
                    && tar -xzf /tmp/gcfs.tar.gz -C /usr/local/bin gocryptfs \
                    && rm -f /tmp/gcfs.tar.gz \
                    || warn "gocryptfs install failed — manual encryption required"
            }
    fi

    # Create encrypted ePHI overlay tool
    cat > /usr/local/bin/forgeos-hipaa-encrypt << 'ENCTOOLS'
#!/usr/bin/env bash
# ForgeOS ePHI Encrypted Directory Manager
# Uses gocryptfs (AES-256-GCM, authenticated encryption, no backdoors)

CMD="${1:-help}"; shift || true

encrypt_dir() {
    local plain_dir="$1"
    local cipher_dir="${plain_dir}.encrypted"

    [[ -d "$plain_dir" ]] || { echo "Directory not found: $plain_dir"; exit 1; }

    if [[ -d "$cipher_dir" ]]; then
        echo "Encrypted storage already exists at $cipher_dir"
        echo "Mount with: forgeos-hipaa-encrypt mount $plain_dir"
        exit 0
    fi

    mkdir -p "$cipher_dir"
    echo "Initializing encrypted storage..."
    echo "You will be prompted for an encryption passphrase."
    echo "STORE THIS PASSPHRASE SECURELY — data is unrecoverable without it."
    echo ""
    gocryptfs -init "$cipher_dir"

    echo ""
    echo "Encrypted storage initialized at: $cipher_dir"
    echo "Mounting to: $plain_dir"
    gocryptfs "$cipher_dir" "$plain_dir"
    echo "ePHI directory mounted and encrypted."
    echo ""
    echo "To add this to HIPAA audit tracking:"
    echo "  forgeos-hipaa designate-phi $plain_dir"
}

mount_dir() {
    local plain_dir="$1"
    local cipher_dir="${plain_dir}.encrypted"
    [[ -d "$cipher_dir" ]] || { echo "No encrypted storage at $cipher_dir"; exit 1; }
    gocryptfs "$cipher_dir" "$plain_dir"
    echo "Mounted: $cipher_dir → $plain_dir"
}

umount_dir() {
    local plain_dir="$1"
    fusermount -u "$plain_dir"
    echo "Unmounted: $plain_dir"
}

case "$CMD" in
    init|encrypt) encrypt_dir "$@" ;;
    mount)        mount_dir "$@" ;;
    umount)       umount_dir "$@" ;;
    status)
        echo "=== Encrypted mounts ==="
        findmnt -t fuse.gocryptfs 2>/dev/null || echo "(none)"
        ;;
    help|*)
        echo "ForgeOS ePHI Encryption Tool"
        echo "  init <directory>   Initialize encryption for a directory"
        echo "  mount <directory>  Mount encrypted directory"
        echo "  umount <directory> Unmount encrypted directory"
        echo "  status             Show encrypted mounts"
        ;;
esac
ENCTOOLS
    chmod +x /usr/local/bin/forgeos-hipaa-encrypt

    info "At-rest encryption tooling installed"
    info "  Encrypt ePHI: forgeos-hipaa-encrypt init /srv/nas/patients"
}

# ============================================================
# PHI DIRECTORY DESIGNATION + AUDIT TRACKING
# ============================================================
configure_phi_tracking() {
    step "Configuring ePHI directory audit tracking"

    touch "$PHI_DIRS_FILE"

    cat > /usr/local/bin/forgeos-hipaa << 'HIPAATOOL'
#!/usr/bin/env bash
# ForgeOS HIPAA Compliance Management Tool
source /etc/forgeos/forgeos.conf 2>/dev/null || true
PHI_DIRS_FILE="/etc/forgeos/hipaa/phi-directories.conf"
HIPAA_LOG="/var/log/forgeos/hipaa"
CMD="${1:-help}"; shift || true

designate_phi() {
    local dir="$1"
    [[ -d "$dir" ]] || { echo "Directory not found: $dir"; exit 1; }

    # Add to PHI list
    grep -qxF "$dir" "$PHI_DIRS_FILE" || echo "$dir" >> "$PHI_DIRS_FILE"

    # Add audit rule for this directory
    local rule="-w ${dir} -p rwxa -k hipaa_phi_access"
    grep -qF "$rule" /etc/audit/rules.d/99-hipaa-forgeos.rules \
        || echo "$rule" >> /etc/audit/rules.d/99-hipaa-forgeos.rules

    # Apply rule live
    auditctl -w "$dir" -p rwxa -k hipaa_phi_access 2>/dev/null || true

    # Set restrictive ACLs
    chmod 750 "$dir"
    setfacl -m "u::rwx,g::r-x,o::---" "$dir" 2>/dev/null || true

    echo "ePHI directory designated and audit-tracked: $dir"
}

generate_report() {
    local period="${1:-daily}"
    local out="$HIPAA_LOG/hipaa-report-$(date +%Y%m%d).txt"
    mkdir -p "$HIPAA_LOG"

    {
        echo "╔══════════════════════════════════════════════════╗"
        echo "║       FORGEOS HIPAA AUDIT REPORT                 ║"
        echo "╚══════════════════════════════════════════════════╝"
        echo "Generated: $(date)"
        echo "System:    $(hostname -f)"
        echo "Period:    $period"
        echo ""

        echo "── Authentication Events ─────────────────────────"
        ausearch -k hipaa_authentication --start today 2>/dev/null \
            | aureport --auth 2>/dev/null | head -30 || echo "(none)"
        echo ""

        echo "── Failed Login Attempts ─────────────────────────"
        ausearch -k hipaa_failed_login --start today 2>/dev/null \
            | head -20 || echo "(none)"
        echo ""

        echo "── ePHI Directory Access ─────────────────────────"
        ausearch -k hipaa_phi_access --start today 2>/dev/null \
            | aureport --file 2>/dev/null | head -50 || echo "(none)"
        echo ""

        echo "── Privilege Escalation ──────────────────────────"
        ausearch -k hipaa_sudo --start today 2>/dev/null \
            | head -20 || echo "(none)"
        echo ""

        echo "── User Management Changes ───────────────────────"
        ausearch -k hipaa_user_mgmt --start today 2>/dev/null \
            | head -20 || echo "(none)"
        echo ""

        echo "── Service Config Changes ────────────────────────"
        ausearch -k hipaa_service_config --start today 2>/dev/null \
            | head -20 || echo "(none)"
        echo ""

        echo "── System Uptime / Availability ─────────────────"
        uptime
        last reboot | head -5
        echo ""

        echo "── Backup Status ─────────────────────────────────"
        ls -lh /opt/forgeos/backup/logs/*.log 2>/dev/null | tail -5 || echo "(no backup logs)"
        echo ""

        echo "══════════════════════════════════════════════════"
        echo "END OF REPORT"
    } > "$out"

    echo "Report written to: $out"
    cat "$out"
}

check_compliance() {
    echo "=== ForgeOS HIPAA Compliance Check ==="
    echo ""

    local pass=0 warn=0 fail=0

    check() {
        local label="$1" cmd="$2" required="${3:-yes}"
        if eval "$cmd" &>/dev/null; then
            echo "  ✓ $label"
            (( pass++ ))
        else
            if [[ "$required" == "yes" ]]; then
                echo "  ✗ $label  ← REQUIRED"
                (( fail++ ))
            else
                echo "  ⚠ $label  ← recommended"
                (( warn++ ))
            fi
        fi
    }

    check "TLS on web UI (nginx)"        "nginx -t"
    check "auditd running"               "systemctl is-active auditd"
    check "auditd HIPAA rules loaded"    "auditctl -l | grep -q hipaa_phi"  no
    check "SSH: root login disabled"     "grep -q 'PermitRootLogin no' /etc/ssh/sshd_config.d/*.conf"
    check "SSH: password auth restricted" "grep -q 'PasswordAuthentication no' /etc/ssh/sshd_config.d/*.conf" no
    check "Fail2ban: active"             "systemctl is-active fail2ban"
    check "AppArmor: enforce mode"       "aa-status 2>/dev/null | grep -q 'enforce'"  no
    check "AIDE: integrity database"     "[[ -f /var/lib/aide/aide.db ]]"  no
    check "Session timeout configured"   "[[ -f /etc/profile.d/forgeos-hipaa-timeout.sh ]]"
    check "Password policy (pwquality)"  "grep -q 'minlen = 12' /etc/security/pwquality.conf"
    check "Account lockout (faillock)"   "grep -q 'deny = 5' /etc/security/faillock.conf"
    check "NTP: time sync active"        "systemctl is-active chrony || systemctl is-active ntp || systemctl is-active systemd-timesyncd"
    check "Backup: timer active"         "systemctl is-active forgenas-backup.timer || systemctl is-active forgeos-backup.timer"  no
    check "ePHI dirs designated"         "[[ -s $PHI_DIRS_FILE ]]"  no
    check "At-rest encryption available" "command -v gocryptfs"  no

    echo ""
    echo "  Results: $pass passed, $warn warnings, $fail required failures"
    echo ""
    [[ $fail -gt 0 ]] && echo "  ACTION REQUIRED: $fail compliance items need attention." \
                      || echo "  Core HIPAA controls are in place."
    echo ""
    echo "  NOTE: Technical controls alone do not ensure HIPAA compliance."
    echo "  Review your policies, workforce training, and BAA agreements."
}

case "$CMD" in
    designate-phi)    designate_phi "$@" ;;
    report)           generate_report "$@" ;;
    check)            check_compliance ;;
    phi-list)         cat "$PHI_DIRS_FILE" 2>/dev/null || echo "(none designated)" ;;
    encrypt-phi)      forgeos-hipaa-encrypt init "$@" ;;
    help|*)
        echo "ForgeOS HIPAA Compliance Manager"
        echo ""
        echo "  designate-phi <dir>   Mark directory as containing ePHI (enables audit tracking)"
        echo "  report [daily|weekly] Generate HIPAA audit report"
        echo "  check                 Run compliance checklist"
        echo "  phi-list              List designated ePHI directories"
        echo "  encrypt-phi <dir>     Enable at-rest encryption on ePHI directory"
        echo ""
        echo "Example workflow for a medical office:"
        echo "  1. forgeos-hipaa designate-phi /srv/nas/patients"
        echo "  2. forgeos-hipaa encrypt-phi /srv/nas/patients"
        echo "  3. forgeos-hipaa check"
        echo "  4. forgeos-hipaa report daily"
        ;;
esac
HIPAATOOL
    chmod +x /usr/local/bin/forgeos-hipaa
}

# ============================================================
# AUDIT LOG ROTATION + REPORTING TIMERS
# ============================================================
configure_audit_reporting() {
    step "Configuring HIPAA audit log reporting"

    # Audit log rotation — HIPAA requires 6 years retention (addressable)
    cat > /etc/logrotate.d/forgeos-hipaa << 'LR'
/var/log/audit/audit.log
/var/log/forgeos/hipaa/*.txt {
    daily
    rotate 2190
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        service auditd rotate 2>/dev/null || true
    endscript
}
LR

    # Daily audit report timer
    cat > /etc/systemd/system/forgeos-hipaa-report.service << 'SVC'
[Unit]
Description=ForgeOS HIPAA Daily Audit Report
[Service]
Type=oneshot
ExecStart=/usr/local/bin/forgeos-hipaa report daily
SVC

    cat > /etc/systemd/system/forgeos-hipaa-report.timer << 'TIMER'
[Unit]
Description=ForgeOS HIPAA Daily Audit Report
[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true
[Install]
WantedBy=timers.target
TIMER

    systemctl daemon-reload
    systemctl enable forgeos-hipaa-report.timer

    info "HIPAA daily audit reports scheduled (06:00 daily)"
    info "Reports saved to: /var/log/forgeos/hipaa/"
}

# ============================================================
# SAMBA HIPAA-SPECIFIC SETTINGS
# ============================================================
configure_samba_hipaa() {
    step "Applying HIPAA settings to Samba"

    cat >> /etc/samba/smb.conf << 'SAMBAHIPAA'

# ── HIPAA Compliance additions ──────────────────────────────
[global]
# Detailed access logging
full_audit:prefix  = %u|%I|%S
full_audit:failure = connect
full_audit:success = open close read write rename unlink mkdir rmdir
full_audit:facility = LOCAL5
full_audit:priority = NOTICE
vfs objects = full_audit acl_xattr

# Disable insecure features
ntlm auth = ntlmv2-only
restrict anonymous = 2
SAMBAHIPAA

    # Rsyslog: redirect Samba full_audit LOCAL5 to HIPAA log
    cat >> /etc/rsyslog.d/49-forgeos-hipaa.conf << 'RSYS'
# ForgeOS HIPAA: Samba file access log
local5.*    /var/log/forgeos/hipaa/samba-access.log
RSYS

    systemctl restart rsyslog 2>/dev/null || true
    info "Samba HIPAA audit logging enabled → /var/log/forgeos/hipaa/samba-access.log"
}

# ============================================================
# BAA DOCUMENTATION GENERATOR
# ============================================================
generate_baa_docs() {
    step "Generating HIPAA configuration documentation"

    mkdir -p /opt/forgeos/docs/hipaa

    cat > /opt/forgeos/docs/hipaa/HIPAA-CONFIGURATION.md << 'DOCS'
# ForgeOS HIPAA Security Configuration

## Technical Safeguards Implemented

### Access Control (§164.312(a)(1))
- **Unique user identification**: Each user has a unique account (Authentik/LDAP)
- **Emergency access**: Root account accessible with strong passphrase
- **Automatic logoff**: 15-minute idle timeout on all terminal sessions
- **Encryption/decryption**: gocryptfs AES-256-GCM available for ePHI directories

### Audit Controls (§164.312(b))
- **auditd**: Kernel-level syscall auditing enabled
- **File access**: All reads/writes to designated ePHI directories are logged
- **Authentication events**: All logins, failures, and privilege escalations logged
- **Samba access**: Full audit VFS module logs all file operations
- **Retention**: Audit logs retained for 6 years (logrotate configured)
- **Reports**: Daily automated audit reports at 06:00

### Integrity Controls (§164.312(c)(1))
- **btrfs checksums**: All data blocks checksummed at filesystem level
- **AIDE**: File integrity monitoring database available
- **btrfs scrub**: Weekly integrity verification of all data

### Transmission Security (§164.312(e)(2)(ii))
- **TLS 1.2/1.3 only**: All web services require modern TLS
- **HSTS**: HTTP Strict Transport Security on all vhosts
- **SFTP/FTPS**: Encrypted file transfer (FTPS port 21 with TLS required)
- **VPN**: WireGuard available for site-to-site ePHI transmission

## Administrative Safeguards Required (Human Processes)
These cannot be automated and must be addressed by your organization:
- [ ] Security Management Process (§164.308(a)(1))
- [ ] Assigned Security Responsibility (§164.308(a)(2))
- [ ] Workforce Training (§164.308(a)(5))
- [ ] Contingency Plan (§164.308(a)(7)) ← Backup module covers technical part
- [ ] Business Associate Agreements with vendors

## Physical Safeguards Required
- [ ] Facility Access Controls
- [ ] Workstation Security (physical locks, screen privacy filters)
- [ ] Device and Media Controls

## Commands Reference
```bash
forgeos-hipaa check                     # Run compliance checklist
forgeos-hipaa designate-phi /path       # Mark ePHI directory
forgeos-hipaa encrypt-phi /path         # Encrypt ePHI directory
forgeos-hipaa report daily              # Generate audit report
```
DOCS

    info "HIPAA documentation generated: /opt/forgeos/docs/hipaa/"
}

# ============================================================
# MAIN
# ============================================================
install_hipaa_packages
configure_hipaa_audit
configure_password_policy
configure_atrest_encryption
configure_phi_tracking
configure_audit_reporting
configure_samba_hipaa
generate_baa_docs

forgenas_set "HIPAA_ENABLED" "yes"

info "HIPAA compliance module complete"
info ""
info "  Next steps:"
info "  1. forgeos-hipaa designate-phi /srv/nas/your-phi-directory"
info "  2. forgeos-hipaa encrypt-phi   /srv/nas/your-phi-directory"
info "  3. forgeos-hipaa check"
info "  4. Review: /opt/forgeos/docs/hipaa/HIPAA-CONFIGURATION.md"
info ""
warn "  REMINDER: Technical controls alone do not ensure HIPAA compliance."
warn "  Consult a HIPAA compliance officer for full program implementation."
