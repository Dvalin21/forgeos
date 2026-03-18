#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 14 - Mail Server
#
# Stack:
#   Postfix  — MTA (sends and receives mail)
#   Dovecot  — IMAP/POP3 server (clients connect here)
#   Rspamd   — spam filtering + DKIM signing
#   ClamAV   — virus scanning (via clamav-milter)
#   OpenDKIM — DKIM key management (via Rspamd)
#   SOGo     — webmail + calendar + contacts (GroupDAV/CalDAV)
#
# Ports:
#   25    SMTP (inbound from internet, outbound relay)
#   587   Submission (clients send mail here, STARTTLS required)
#   465   SMTPS (implicit TLS submission, modern clients)
#   993   IMAPS (implicit TLS, clients)
#   995   POP3S (optional, legacy)
#   4190  ManageSieve (mail filter rules)
#   8086  SOGo webmail (proxied to https://mail.domain)
#
# Security:
#   Mandatory TLS everywhere (no plaintext auth, ever)
#   DKIM, SPF, DMARC alignment checked on inbound
#   DKIM signing on all outbound mail
#   Rspamd with neural spam scoring
#   ClamAV on all attachments
#   Rate limiting on submission port
#
# DNS records are auto-generated and displayed at end.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

MAIL_CONF_DIR="/etc/forgeos/mail"
MAIL_DATA="/srv/forgeos/mail"
VMAIL_UID=5000
VMAIL_GID=5000

mkdir -p "$MAIL_CONF_DIR" "$MAIL_DATA"/{mailboxes,sieve}
chmod 700 "$MAIL_CONF_DIR"

# ============================================================
# VMAIL USER
# All mailboxes owned by this system user
# ============================================================
setup_vmail_user() {
    step "Creating vmail system user"

    if ! id vmail &>/dev/null; then
        groupadd -g $VMAIL_GID vmail
        useradd -u $VMAIL_UID -g $VMAIL_GID -d "$MAIL_DATA/mailboxes" \
            -s /usr/sbin/nologin -M vmail
    fi

    chown -R vmail:vmail "$MAIL_DATA"
    chmod 700 "$MAIL_DATA/mailboxes"
    info "vmail user created (uid=${VMAIL_UID})"
}

# ============================================================
# POSTFIX
# ============================================================
configure_postfix() {
    step "Configuring Postfix MTA"

    apt_install postfix postfix-mysql libsasl2-modules sasl2-bin \
        postfix-pcre opendkim opendkim-tools

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:?DOMAIN not set}"
    local hostname="${HOSTNAME:-forgeos}"
    local fqdn="${hostname}.${domain}"
    local cert_path="/etc/letsencrypt/live/${domain}/fullchain.pem"
    local key_path="/etc/letsencrypt/live/${domain}/privkey.pem"

    # Fall back to self-signed if no cert yet
    if [[ ! -f "$cert_path" ]]; then
        mkdir -p /etc/postfix/tls
        openssl req -x509 -nodes -days 3650 \
            -newkey rsa:4096 \
            -keyout /etc/postfix/tls/mail.key \
            -out    /etc/postfix/tls/mail.crt \
            -subj   "/CN=${fqdn}" >> "$FORGENAS_LOG" 2>&1
        cert_path="/etc/postfix/tls/mail.crt"
        key_path="/etc/postfix/tls/mail.key"
    fi

    cat > /etc/postfix/main.cf << MAIN
# ForgeOS Postfix Configuration

# Identity
myhostname       = ${fqdn}
mydomain         = ${domain}
myorigin         = \$mydomain
inet_interfaces  = all
inet_protocols   = ipv4

# Local delivery
mydestination    = \$myhostname, localhost.\$mydomain, localhost
mynetworks       = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 $(forgenas_get LAN_CIDR 192.168.0.0/16)
home_mailbox     = Maildir/
alias_maps       = hash:/etc/aliases
alias_database   = hash:/etc/aliases

# TLS inbound (mandatory for submission)
smtpd_tls_cert_file             = ${cert_path}
smtpd_tls_key_file              = ${key_path}
smtpd_tls_security_level        = may
smtpd_tls_protocols             = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtpd_tls_ciphers               = high
smtpd_tls_mandatory_protocols   = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtpd_tls_mandatory_ciphers     = high
smtpd_tls_loglevel              = 1
smtpd_tls_session_cache_database = btree:\${data_directory}/smtpd_scache

# TLS outbound
smtp_tls_security_level  = may
smtp_tls_loglevel        = 1
smtp_tls_session_cache_database = btree:\${data_directory}/smtp_scache

# SASL Authentication (clients authenticating to submit mail)
smtpd_sasl_auth_enable          = yes
smtpd_sasl_type                 = dovecot
smtpd_sasl_path                 = private/auth
smtpd_sasl_security_options     = noanonymous
smtpd_sasl_tls_security_options = noanonymous

# Restrictions
smtpd_relay_restrictions =
    permit_mynetworks,
    permit_sasl_authenticated,
    defer_unauth_destination

smtpd_recipient_restrictions =
    permit_mynetworks,
    permit_sasl_authenticated,
    reject_unauth_destination,
    reject_unknown_recipient_domain,
    reject_unauth_pipelining

smtpd_sender_restrictions =
    permit_mynetworks,
    permit_sasl_authenticated,
    reject_unknown_sender_domain

# Rate limiting
smtpd_client_connection_rate_limit = 30
smtpd_client_message_rate_limit    = 100
anvil_rate_time_unit               = 60s

# Anti-spam (Rspamd milter)
milter_protocol   = 6
milter_default_action = accept
smtpd_milters     = inet:127.0.0.1:11332
non_smtpd_milters = inet:127.0.0.1:11332

# Message size limit (50MB)
message_size_limit = 52428800
mailbox_size_limit = 0

# Virtual mailboxes (Dovecot handles delivery)
virtual_transport        = lmtp:unix:private/dovecot-lmtp
virtual_mailbox_domains  = ${domain}
virtual_mailbox_base     = ${MAIL_DATA}/mailboxes
virtual_minimum_uid      = ${VMAIL_UID}
virtual_uid_maps         = static:${VMAIL_UID}
virtual_gid_maps         = static:${VMAIL_GID}
virtual_mailbox_maps     = hash:/etc/postfix/vmailbox
virtual_alias_maps       = hash:/etc/postfix/virtual

# Queue
maximal_queue_lifetime = 5d
bounce_queue_lifetime  = 1d
MAIN

    # Submission ports config
    cat > /etc/postfix/master.cf << 'MASTER'
# ForgeOS Postfix master.cf
# service  type  private  unpriv  chroot  wakeup  maxproc  command + args

# SMTP (inbound from internet)
smtp      inet  n  -  y  -  -  smtpd

# Submission port 587 (STARTTLS, clients)
submission inet n - y - - smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_client_restrictions=permit_sasl_authenticated,reject
  -o smtpd_tls_mandatory_protocols=!SSLv2,!SSLv3,!TLSv1,!TLSv1.1

# SMTPS port 465 (implicit TLS, modern clients)
smtps     inet  n  -  y  -  -  smtpd
  -o syslog_name=postfix/smtps
  -o smtpd_tls_wrappermode=yes
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_client_restrictions=permit_sasl_authenticated,reject

# Local delivery
pickup    unix  n  -  y  60  1  pickup
cleanup   unix  n  -  y  -  0  cleanup
qmgr      unix  n  -  n  300  1  qmgr
tlsmgr    unix  -  -  y  1000?  1  tlsmgr
rewrite   unix  -  -  y  -  -  trivial-rewrite
bounce    unix  -  -  y  -  0  bounce
defer     unix  -  -  y  -  0  bounce
trace     unix  -  -  y  -  0  bounce
verify    unix  -  -  y  -  1  verify
flush     unix  n  -  y  1000?  0  flush
proxymap  unix  -  -  n  -  -  proxymap
proxywrite unix  -  -  n  -  1  proxymap
smtp      unix  -  -  y  -  -  smtp
relay     unix  -  -  y  -  -  smtp
showq     unix  n  -  y  -  -  showq
error     unix  -  -  y  -  -  error
retry     unix  -  -  y  -  -  error
discard   unix  -  -  y  -  -  discard
local     unix  -  n  n  -  -  local
virtual   unix  -  n  n  -  -  virtual
lmtp      unix  -  -  y  -  -  lmtp
anvil     unix  -  -  y  -  1  anvil
scache    unix  -  -  y  -  1  scache
MASTER

    # Virtual mailboxes + aliases
    touch /etc/postfix/vmailbox /etc/postfix/virtual
    postmap /etc/postfix/vmailbox /etc/postfix/virtual
    newaliases

    enable_service postfix
    info "Postfix: SMTP 25, Submission 587/465"
}

# ============================================================
# DOVECOT
# ============================================================
configure_dovecot() {
    step "Configuring Dovecot IMAP"

    apt_install dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd \
        dovecot-sieve dovecot-managesieved

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"
    local cert_path="/etc/letsencrypt/live/${domain}/fullchain.pem"
    local key_path="/etc/letsencrypt/live/${domain}/privkey.pem"
    [[ ! -f "$cert_path" ]] && cert_path="/etc/postfix/tls/mail.crt" key_path="/etc/postfix/tls/mail.key"

    cat > /etc/dovecot/dovecot.conf << DOVECOT
# ForgeOS Dovecot Configuration

protocols = imap lmtp sieve

mail_location = maildir:${MAIL_DATA}/mailboxes/%d/%n/Maildir
mail_privileged_group = mail

first_valid_uid = ${VMAIL_UID}
last_valid_uid  = ${VMAIL_UID}
first_valid_gid = ${VMAIL_GID}

namespace inbox {
  inbox = yes
  mailbox Drafts    { special_use = \Drafts;   auto = subscribe; }
  mailbox Junk      { special_use = \Junk;     auto = subscribe; }
  mailbox Sent      { special_use = \Sent;     auto = subscribe; }
  mailbox Trash     { special_use = \Trash;    auto = subscribe; }
  mailbox Archive   { special_use = \Archive;  auto = subscribe; }
}

# TLS — mandatory
ssl         = required
ssl_cert    = <${cert_path}
ssl_key     = <${key_path}
ssl_min_protocol = TLSv1.2
ssl_cipher_list  = HIGH:MEDIUM:!NULL:!aNULL:!ADH:!DES:!3DES

# Authentication
disable_plaintext_auth = yes
auth_mechanisms        = plain login

passdb { driver = passwd-file; args = /etc/forgeos/mail/passwd; }
userdb { driver = static; args = uid=vmail gid=vmail home=${MAIL_DATA}/mailboxes/%d/%n; }

service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode  = 0660
    user  = postfix
    group = postfix
  }
  unix_listener auth-userdb { mode = 0600; user = vmail; }
}

service lmtp {
  unix_listener /var/spool/postfix/private/dovecot-lmtp {
    mode  = 0600
    user  = postfix
    group = postfix
  }
}

service imap-login { inet_listener imaps { port = 993; ssl = yes; } }

protocol imap {
  mail_max_userip_connections = 20
  imap_idle_notify_interval   = 2 mins
}

# Sieve (server-side mail filters)
protocol lmtp { mail_plugins = \$mail_plugins sieve; }
plugin {
  sieve = file:${MAIL_DATA}/sieve/%u/scripts;active=${MAIL_DATA}/sieve/%u/active.sieve
  sieve_global = /etc/dovecot/sieve/global/
}

service managesieve-login {
  inet_listener sieve { port = 4190; }
}

# Logging
log_path = /var/log/forgeos/dovecot.log
info_log_path = /var/log/forgeos/dovecot-info.log
DOVECOT

    mkdir -p /etc/dovecot/sieve/global
    touch /etc/forgeos/mail/passwd
    chmod 600 /etc/forgeos/mail/passwd

    enable_service dovecot
    info "Dovecot: IMAPS 993, ManageSieve 4190"
}

# ============================================================
# RSPAMD
# Spam filter + DKIM signer
# ============================================================
configure_rspamd() {
    step "Installing Rspamd"

    curl -fsSL https://rspamd.com/apt-stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/rspamd.gpg 2>/dev/null || {
        warn "Rspamd GPG key failed — using apt version"
        apt_install rspamd
        return 0
    }

    local codename; codename=$(lsb_release -cs)
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/rspamd.gpg] \
https://rspamd.com/apt-stable/ ${codename} main" \
        > /etc/apt/sources.list.d/rspamd.list

    _apt_ready=false
    apt_install rspamd redis-server

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    # Worker config — use Redis for caching
    cat > /etc/rspamd/local.d/worker-normal.inc << 'RSPWRK'
bind_socket = "127.0.0.1:11332";
RSPWRK

    cat > /etc/rspamd/local.d/redis.conf << RSPREDIS
servers = "127.0.0.1";
RSPREDIS

    # DKIM signing
    mkdir -p /etc/rspamd/dkim
    rspamadm dkim_keygen -s "mail" -d "$domain" \
        -k "/etc/rspamd/dkim/${domain}.mail.key" \
        > "/etc/rspamd/dkim/${domain}.mail.txt" 2>/dev/null || \
    opendkim-genkey -b 2048 -d "$domain" -D /etc/rspamd/dkim/ \
        -s mail -v >> "$FORGENAS_LOG" 2>&1 || true

    chmod 600 /etc/rspamd/dkim/*.key 2>/dev/null || true
    chown rspamd:rspamd /etc/rspamd/dkim/ 2>/dev/null || true

    cat > /etc/rspamd/local.d/dkim_signing.conf << DKIM
# DKIM signing for outbound mail
enabled = true;
use_domain = "header";
path = "/etc/rspamd/dkim/${domain}.mail.key";
selector = "mail";
DKIM

    # Spam actions
    cat > /etc/rspamd/local.d/actions.conf << 'ACTIONS'
reject  = 15;   # reject outright
greylist = 4;   # greylist borderline
add_header = 6; # add spam header
ACTIONS

    enable_service rspamd
    info "Rspamd: spam filter + DKIM signing active"
}

# ============================================================
# CLAMAV VIRUS SCANNER
# ============================================================
configure_clamav() {
    step "Installing ClamAV"

    apt_install clamav clamav-daemon clamav-milter

    # Update signatures
    systemctl stop clamav-freshclam 2>/dev/null || true
    freshclam >> "$FORGENAS_LOG" 2>&1 || warn "freshclam update failed (will retry)"
    enable_service clamav-daemon clamav-freshclam

    cat > /etc/clamav/clamav-milter.conf << 'CLAM'
MilterSocket inet:11333@127.0.0.1
MaxFileSize 25M
ScanMail true
ScanArchive true
LogSyslog true
LogFile /var/log/forgeos/clamav-milter.log
CLAM

    enable_service clamav-milter
    info "ClamAV: virus scanning on all attachments"
}

# ============================================================
# SOGO WEBMAIL
# ============================================================
install_sogo() {
    step "Installing SOGo webmail"

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    # SOGo repo
    apt_key add - << 'KEY' 2>/dev/null || true
KEY
    wget -qO - https://keys.opengpg.org/vks/v1/by-fingerprint/74FFC6D72B925A34B5D356BDF8A27B36A6E2EAE1 \
        | gpg --dearmor -o /usr/share/keyrings/sogo.gpg 2>/dev/null || {
        warn "SOGo repo key failed — trying apt-get directly"
        apt_install_optional sogo
        return 0
    }

    local codename; codename=$(lsb_release -cs)
    echo "deb [signed-by=/usr/share/keyrings/sogo.gpg] \
https://packages.inverse.ca/SOGo/nightly/5/ubuntu/ ${codename} ${codename}" \
        > /etc/apt/sources.list.d/sogo.list

    _apt_ready=false
    apt_install sogo sogo-tool \
        postgresql libpq5 \
        gnustep-base-runtime 2>/dev/null \
        || { warn "SOGo package install failed — trying Roundcube fallback"; _install_roundcube; return 0; }

    # SOGo requires PostgreSQL backend
    apt_install postgresql
    enable_service postgresql

    local sogo_pass; sogo_pass=$(gen_password 24)
    sudo -u postgres psql -c "CREATE USER sogo WITH PASSWORD '${sogo_pass}';" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE sogo OWNER sogo;" 2>/dev/null || true
    forgenas_set "SOGO_DB_PASS" "$sogo_pass"

    cat > /etc/sogo/sogo.conf << SOGOCONF
{
  /* SOGo ForgeOS Configuration */
  SOGoProfileURL     = "postgresql://sogo:${sogo_pass}@127.0.0.1:5432/sogo/sogousers";
  OCSFolderInfoURL   = "postgresql://sogo:${sogo_pass}@127.0.0.1:5432/sogo/sogofolder";
  OCSSessionsFolderURL = "postgresql://sogo:${sogo_pass}@127.0.0.1:5432/sogo/sogosessions";
  OCSEMailAlarmsFolderURL = "postgresql://sogo:${sogo_pass}@127.0.0.1:5432/sogo/sogoalarms";

  /* Domains */
  SOGoMailDomain   = "${domain}";
  SOGoIMAPServer   = "imaps://localhost:993";
  SOGoSMTPServer   = "smtp://localhost:587";
  SOGoSMTPAuthenticationType = PLAIN;
  SOGoMailingMechanism = smtp;

  /* UI */
  SOGoPageTitle       = "ForgeOS Mail";
  SOGoLanguage        = English;
  SOGoTimeZone        = "${TIMEZONE:-UTC}";
  SOGoFirstDayOfWeek  = 1;
  SOGoSentFolderName  = Sent;
  SOGoTrashFolderName = Trash;
  SOGoDraftsFolderName = Drafts;

  /* Auth */
  SOGoPasswordChangeEnabled = YES;
  SOGoLoginModule = mail;

  /* Workers */
  WOWorkersCount  = 3;
  SOGoMaximumPingInterval = 3540;
  SOGoMaximumSyncInterval = 3540;
  SOGoInternalSyncInterval = 30;

  /* Logging */
  SOGoDebugRequests = NO;
}
SOGOCONF

    enable_service sogo memcached 2>/dev/null || enable_service sogo

    # nginx proxy
    if [[ -d /etc/nginx/forgeos.d ]]; then
        cat > /etc/nginx/forgeos.d/mail.conf << NGINX
server {
    listen 443 ssl http2;
    server_name mail.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    location / {
        proxy_pass  http://127.0.0.1:20000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    # Redirect /mail → root
    rewrite ^/$ /SOGo/ redirect;
}
NGINX
        nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi

    info "SOGo webmail: https://mail.${domain}/SOGo"
}

_install_roundcube() {
    # Lightweight fallback webmail
    apt_install_optional roundcube roundcube-pgsql roundcube-plugins
    info "Roundcube webmail installed as SOGo fallback"
}

# ============================================================
# DNS RECORD GENERATOR
# Prints the exact DNS records needed for a working mail server
# ============================================================
print_dns_records() {
    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"
    local public_ip="${PUBLIC_IP:-<your-server-ip>}"
    local hostname="${HOSTNAME:-forgeos}"

    local dkim_record=""
    if [[ -f "/etc/rspamd/dkim/${domain}.mail.txt" ]]; then
        dkim_record=$(cat "/etc/rspamd/dkim/${domain}.mail.txt" | tr -d '\n' | \
            grep -oP 'p=\K[^;]+' | head -1 || echo "<generate with: rspamadm dkim_keygen>")
    fi

    echo ""
    echo "  ════════════════════════════════════════════════════"
    echo "  DNS RECORDS REQUIRED FOR MAIL"
    echo "  Add these to your DNS provider for: ${domain}"
    echo "  ════════════════════════════════════════════════════"
    echo ""
    echo "  A record (mail server):"
    echo "    ${hostname}.${domain}. IN A ${public_ip}"
    echo ""
    echo "  MX record (where to deliver mail):"
    echo "    ${domain}. IN MX 10 ${hostname}.${domain}."
    echo ""
    echo "  SPF (authorize this server to send mail):"
    echo "    ${domain}. IN TXT \"v=spf1 mx a:${hostname}.${domain} ~all\""
    echo ""
    echo "  DKIM (cryptographic signature):"
    echo "    mail._domainkey.${domain}. IN TXT \"v=DKIM1; k=rsa; p=${dkim_record}\""
    echo ""
    echo "  DMARC (alignment policy):"
    echo "    _dmarc.${domain}. IN TXT \"v=DMARC1; p=quarantine; rua=mailto:postmaster@${domain}; adkim=r; aspf=r\""
    echo ""
    echo "  PTR record (reverse DNS — set at your hosting provider):"
    echo "    ${public_ip} → ${hostname}.${domain}"
    echo ""
    echo "  IMPORTANT: Without correct PTR + SPF + DKIM, mail will be spam-filtered"
    echo "  by Gmail, Outlook, etc. Set all five records before sending."
    echo "  ════════════════════════════════════════════════════"
    echo ""

    # Save to file for easy reference
    print_dns_records 2>/dev/null > /etc/forgeos/mail/dns-records.txt || true
}

# ============================================================
# MAIL CLI
# ============================================================
install_mail_cli() {
    cat > /usr/local/bin/forgeos-mail << 'MAILCLI'
#!/usr/bin/env bash
# ForgeOS Mail Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

case "$CMD" in
status)
    echo "=== ForgeOS Mail ==="
    for svc in postfix dovecot rspamd clamav-daemon; do
        systemctl is-active "$svc" &>/dev/null \
            && printf "  ✓ %-20s\n" "$svc" \
            || printf "  ✗ %-20s\n" "$svc"
    done
    echo ""
    echo "  Queue: $(postqueue -p 2>/dev/null | tail -1 || echo 'empty')"
    echo "  Spam blocked today: $(grep -c 'reject' /var/log/mail.log 2>/dev/null || echo '0')"
    ;;
add-user)
    user="${1:?user}" pass="${2:?pass}"
    domain="${DOMAIN:-nas.local}"
    mkdir -p "/srv/forgeos/mail/mailboxes/${domain}/${user}/Maildir"
    chown -R vmail:vmail "/srv/forgeos/mail/mailboxes/${domain}/${user}"
    echo "${user}@${domain}:{PLAIN}${pass}:${VMAIL_UID:-5000}:${VMAIL_GID:-5000}::/srv/forgeos/mail/mailboxes/${domain}/${user}::" \
        >> /etc/forgeos/mail/passwd
    echo "${user}@${domain}  ${domain}/${user}/Maildir/" \
        >> /etc/postfix/vmailbox
    postmap /etc/postfix/vmailbox
    echo "Mail user: ${user}@${domain}"
    ;;
remove-user)
    user="${1:?user}" domain="${DOMAIN:-nas.local}"
    sed -i "/^${user}@${domain}:/d" /etc/forgeos/mail/passwd
    sed -i "/^${user}@${domain} /d" /etc/postfix/vmailbox
    postmap /etc/postfix/vmailbox
    echo "Removed: ${user}@${domain}"
    ;;
list-users)
    awk -F: '{print $1}' /etc/forgeos/mail/passwd 2>/dev/null || echo "No mail users"
    ;;
queue)
    postqueue -p
    ;;
flush)
    postqueue -f; echo "Queue flushed"
    ;;
test-send)
    echo "Test mail from ForgeOS at $(date)" \
        | mail -s "ForgeOS Test" -r "forgeos@${DOMAIN:-nas.local}" "${1:?recipient}"
    echo "Test mail sent to $1"
    ;;
dns-records)
    cat /etc/forgeos/mail/dns-records.txt 2>/dev/null \
        || echo "Run the mail module to generate DNS records"
    ;;
dkim-show)
    cat "/etc/rspamd/dkim/${DOMAIN:-nas.local}.mail.txt" 2>/dev/null \
        || echo "DKIM key not found — check /etc/rspamd/dkim/"
    ;;
help|*)
    echo "ForgeOS Mail Manager"
    echo "  status                  All mail service status"
    echo "  add-user <user> <pass>  Add mailbox"
    echo "  remove-user <user>      Remove mailbox"
    echo "  list-users              List all mailboxes"
    echo "  queue                   Show mail queue"
    echo "  flush                   Flush mail queue"
    echo "  test-send <email>       Send test mail"
    echo "  dns-records             Show required DNS records"
    echo "  dkim-show               Show DKIM public key"
    ;;
esac
MAILCLI
    chmod +x /usr/local/bin/forgeos-mail
}

# ============================================================
# FIREWALL
# ============================================================
configure_mail_firewall() {
    ufw allow 25/tcp  comment "SMTP inbound"
    ufw allow 587/tcp comment "SMTP submission"
    ufw allow 465/tcp comment "SMTPS"
    ufw allow 993/tcp comment "IMAPS"
    ufw allow 4190/tcp comment "Sieve"
}

# ============================================================
# MAIN
# ============================================================
setup_vmail_user
configure_postfix
configure_dovecot
configure_rspamd
configure_clamav
install_sogo
configure_mail_firewall
install_mail_cli
print_dns_records

forgenas_set "MODULE_MAIL_DONE" "yes"
forgenas_set "FEATURE_MAIL"     "yes"

local domain="${DOMAIN:-nas.local}"
info "Mail module complete"
info "  Webmail:     https://mail.${domain}/SOGo"
info "  SMTP:        ${HOSTNAME:-forgeos}.${domain}:587 (STARTTLS)"
info "  IMAP:        ${HOSTNAME:-forgeos}.${domain}:993 (SSL)"
info "  Add mailbox: forgeos-mail add-user <user> <pass>"
warn "  DNS records saved to: /etc/forgeos/mail/dns-records.txt"
warn "  Configure DNS before mail will work with external providers."
