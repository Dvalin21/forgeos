#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 10b - Samba WebGUI Management + File-Based DB Support
#
# ElevateDB RESEARCH SUMMARY:
# ─────────────────────────────────────────────────────────────
# ElevateDB (Elevate Software) is a file-based embedded database
# engine used by Delphi/C++Builder/Lazarus applications including
# Atrex inventory software. It is NOT a traditional server like
# PostgreSQL. Instead, client applications open database files
# directly from disk — either locally or across a network share.
#
# TWO OPERATION MODES:
#   Mode 1 — Local/File (most common with Atrex):
#     All clients open .EDB/.EDBT/.EDBI files directly over SMB.
#     This is where corruption happens WITHOUT correct settings.
#     Corruption vectors:
#       - Oplocks: OS caches writes locally, other clients see stale data
#       - Kernel oplocks: Same problem at kernel level
#       - Strict locking: Can cause deadlocks when ElevateDB manages its own
#       - SMB1: Broken opportunistic locking, always upgrade to SMB2/3
#     Our solution: dedicated "elevatedb" share template with all
#     locking disabled at the Samba level. ElevateDB handles its
#     own record-level locking internally.
#
#   Mode 2 — Client/Server (ElevateDB Server):
#     A single ElevateDB Server process manages all file access.
#     Clients connect via TCP — NO direct file access over SMB.
#     This is the CORRECT architecture for 5+ concurrent users.
#     ElevateDB Server is Windows-only. For Linux hosting we
#     provide a Wine-based Docker container that runs it natively.
#     This is better than file sharing for high-concurrency.
#
# OTHER FILE-BASED DATABASES WITH IDENTICAL REQUIREMENTS:
#   - DBISAM (ElevateDB predecessor, same company, .DB files)
#   - TurboDB / DataMaker (.dat files, Delphi ecosystem)
#   - NexusDB (.nxd files, Delphi ecosystem)
#   - Paradox (.db/.px files, Borland legacy)
#   - dBase/Visual FoxPro (.dbf files)
#   - Microsoft Access (.mdb/.accdb files)
#   - SQLite (.sqlite/.db — special: WAL mode allows safe multi-reader)
#   - BDE (Borland Database Engine) apps
#   All above: oplocks OFF, kernel oplocks OFF, strict locking OFF
#
# KEY DIFFERENCE — SQLite:
#   SQLite with WAL (Write-Ahead Logging) journal mode is the ONE
#   file-based DB that can handle concurrent access reasonably well
#   WITHOUT disabling all oplocks, because WAL uses atomic file ops.
#   But we still disable oplocks for SQLite shares for safety.
#
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

SAMBA_CONF="/etc/samba/smb.conf"
SAMBA_SHARES_DIR="/etc/forgeos/samba/shares"
FORGEOS_SHARES_FILE="/etc/forgeos/samba/forgeos-shares.conf"

# ============================================================
# SAMBA INSTALL + BASE CONFIG
# ============================================================
install_samba_managed() {
    step "Installing Samba (WebGUI-managed)"

    apt_install samba samba-common-bin smbclient acl attr libpam-winbind

    mkdir -p "$SAMBA_SHARES_DIR" "$(dirname "$FORGEOS_SHARES_FILE")"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local domain_short
    domain_short=$(echo "${DOMAIN:-FORGEOS}" | cut -d. -f1 | tr '[:lower:]' '[:upper:]')

    cat > "$SAMBA_CONF" << SMBC
# ForgeOS Samba Configuration
# ══════════════════════════════════════════════════════════
# Managed via Web UI > Network > File Sharing > SMB
# Raw editor: Web UI > Network > File Sharing > SMB > Raw Config
# CLI:        forgeos-samba help
# ══════════════════════════════════════════════════════════

[global]
   workgroup         = ${domain_short}
   server string     = ForgeOS NAS %v
   netbios name      = ${HOSTNAME:-FORGEOS}
   server role       = standalone server
   security          = user
   map to guest      = Bad User

   # Protocol — SMB2 minimum (NEVER SMB1 — broken oplocks)
   server min protocol = SMB2_10
   server max protocol = SMB3

   # Security
   restrict anonymous  = 2
   ntlm auth           = ntlmv2-only

   # Performance
   socket options      = TCP_NODELAY IPTOS_LOWDELAY
   use sendfile        = yes
   aio read size       = 16384
   aio write size      = 16384

   # macOS Time Machine
   vfs objects         = fruit streams_xattr acl_xattr
   fruit:metadata      = stream
   fruit:model         = MacSamba
   fruit:posix_rename  = yes
   fruit:veto_appledouble = no

   # Logging
   log file = /var/log/forgeos/samba/%m.log
   max log size = 50
   log level = 1

   # No printing
   load printers   = no
   printing        = bsd
   printcap name   = /dev/null
   disable spoolss = yes

   include = ${FORGEOS_SHARES_FILE}

SMBC

    echo "# ForgeOS shares — managed by forgeos-samba" > "$FORGEOS_SHARES_FILE"
    mkdir -p /var/log/forgeos/samba
    testparm -s "$SAMBA_CONF" >> "$FORGENAS_LOG" 2>&1 || warn "Samba config warnings"
    enable_service smbd nmbd
    info "Samba installed (WebGUI-managed)"
}

# ============================================================
# SHARE TEMPLATES
# ============================================================
get_share_stanza() {
    local name="$1" path="$2" type="${3:-standard}"
    local write="${4:-yes}" users="${5:-@users}" comment="${6:-}"

    case "$type" in

    standard)
        cat << EOF
[${name}]
   comment      = ${comment:-ForgeOS Share}
   path         = ${path}
   browseable   = yes
   writable     = ${write}
   valid users  = ${users}
   create mask  = 0664
   directory mask = 0775
   vfs objects  = fruit streams_xattr acl_xattr

EOF
        ;;

    # ─────────────────────────────────────────────────────────
    # ELEVATEDB / FILE-BASED DATABASE SHARE
    # Covers: ElevateDB, DBISAM, NexusDB, TurboDB, Paradox,
    #         dBase/FoxPro, MS Access, BDE apps, any Delphi DB
    #
    # THE CORRUPTION PROBLEM explained:
    #   When SMB oplocks are enabled, the OS grants a client
    #   an "oplock" — permission to cache file data locally.
    #   If client A has an oplock on customers.edbt and writes
    #   a record, that write sits in client A's local cache.
    #   Client B then reads customers.edbt — it gets STALE DATA
    #   from the server, not client A's cached write.
    #   When client A finally flushes, the file on disk may
    #   have both writes interleaved incorrectly → CORRUPTION.
    #   ElevateDB's internal record locking cannot compensate
    #   because the OS-level oplock bypasses the DB engine.
    #
    # FIX: Disable ALL forms of oplocks. ElevateDB then handles
    # its own synchronization correctly at the record level.
    # ─────────────────────────────────────────────────────────
    elevatedb|filedb|database)
        cat << EOF
[${name}]
   comment      = ${comment:-ForgeOS File-DB Share (ElevateDB/DBISAM/dBase/Access)}
   path         = ${path}
   browseable   = yes
   writable     = yes
   valid users  = ${users}
   create mask  = 0664
   directory mask = 0775

   # ── CRITICAL: Oplock settings for file-based databases ──
   # Without these, concurrent access WILL corrupt database files.
   # ElevateDB, DBISAM, NexusDB, Paradox, Access, dBase/FoxPro
   # all require oplocks to be disabled at the Samba level.
   # The DB engine handles its own record-level locking internally.
   oplocks              = no
   level2 oplocks       = no
   kernel oplocks       = no

   # Do not let Samba's strict byte-range locking interfere
   # with the DB engine's own locking protocol
   strict locking       = no

   # Allow multiple simultaneous SMB connections to the same files
   # (required: each DB client needs its own SMB file handle)
   share modes          = yes

   # Connection keepalive — important for DB sessions
   # that may be idle between transactions
   keepalive            = 30

   # Minimum read/write units — DB engines do small random I/O
   # Setting aio sizes to 1 disables async buffering that can
   # reorder small DB writes (another corruption vector)
   aio read size        = 1
   aio write size       = 1

   # Disable client-side write caching for this share
   # (SMB2/3 durable handles can cache — dangerous for file DBs)
   posix locking        = no

   # No Recycle Bin — DB temp files must delete cleanly
   vfs objects          = streams_xattr acl_xattr

EOF
        ;;

    # ─────────────────────────────────────────────────────────
    # SQLite SHARE
    # SQLite is special: WAL mode makes it safer than other
    # file-based DBs for concurrent access, but we still
    # disable oplocks because SQLite's WAL uses OS-level file
    # locking (fcntl) which SMB oplocks can interfere with.
    # Applications must open SQLite with WAL journal mode:
    #   PRAGMA journal_mode=WAL;
    # ─────────────────────────────────────────────────────────
    sqlite)
        cat << EOF
[${name}]
   comment      = ${comment:-ForgeOS SQLite Share}
   path         = ${path}
   browseable   = yes
   writable     = yes
   valid users  = ${users}
   create mask  = 0664
   directory mask = 0775

   # SQLite requires oplocks disabled — fcntl locking conflicts
   # with SMB oplock grants even in WAL mode
   oplocks          = no
   level2 oplocks   = no
   kernel oplocks   = no
   strict locking   = no
   # SQLite WAL creates -wal and -shm sidecar files
   # These must be writable by all DB clients
   create mask      = 0666

   vfs objects      = streams_xattr acl_xattr

EOF
        ;;

    timemachine)
        local quota="${6:-500000}"
        cat << EOF
[${name}]
   comment      = ${comment:-Time Machine Backup}
   path         = ${path}
   browseable   = yes
   writable     = yes
   valid users  = ${users}
   vfs objects  = fruit streams_xattr
   fruit:time machine = yes
   fruit:time machine max size = ${quota}M
   durable handles  = yes
   kernel oplocks   = no
   kernel share modes = no
   posix locking    = no

EOF
        ;;

    public-ro)
        cat << EOF
[${name}]
   comment    = ${comment:-Public Read-Only}
   path       = ${path}
   browseable = yes
   writable   = no
   guest ok   = yes
   read only  = yes

EOF
        ;;

    admin)
        cat << EOF
[${name}]
   comment    = ${comment:-Admin Share}
   path       = ${path}
   browseable = no
   writable   = yes
   valid users = @admins
   create mask = 0640
   directory mask = 0750

EOF
        ;;
    esac
}

# ============================================================
# FORGEOS-SAMBA CLI
# ============================================================
create_samba_cli() {
    step "Installing forgeos-samba CLI"

    cat > /usr/local/bin/forgeos-samba << 'SAMBACLI'
#!/usr/bin/env bash
# ForgeOS Samba Management Tool
set -euo pipefail
SHARES_DIR="/etc/forgeos/samba/shares"
SHARES_FILE="/etc/forgeos/samba/forgeos-shares.conf"
mkdir -p "$SHARES_DIR"
CMD="${1:-help}"; shift || true

rebuild() {
    { echo "# ForgeOS Samba shares — $(date)"; echo ""
      for f in "$SHARES_DIR"/*.share 2>/dev/null; do
          [[ -f "$f" ]] || continue; cat "$f"; echo ""
      done
    } > "$SHARES_FILE"
    testparm -s /etc/samba/smb.conf &>/dev/null || { echo "Config test FAILED"; return 1; }
    smbcontrol smbd reload-config 2>/dev/null || systemctl reload smbd 2>/dev/null || true
    echo "Samba reloaded"
}

# Auto-detect database type from file extensions
detect_db_type() {
    local path="$1"
    # ElevateDB / DBISAM
    find "$path" -maxdepth 3 \( -name "*.EDB" -o -name "*.EDBT" -o -name "*.EDBI" \
        -o -name "*.DB" -o -name "*.PX" \) -print -quit 2>/dev/null | grep -q . && { echo "elevatedb"; return; }
    # SQLite
    find "$path" -maxdepth 3 \( -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" \) \
        -print -quit 2>/dev/null | grep -q . && { echo "sqlite"; return; }
    # dBase/FoxPro/Access
    find "$path" -maxdepth 3 \( -name "*.dbf" -o -name "*.mdb" -o -name "*.accdb" \
        -o -name "*.fdb" -o -name "*.gdb" \) -print -quit 2>/dev/null | grep -q . && { echo "database"; return; }
    echo "standard"
}

case "$CMD" in
create)
    name="${1:?name}" path="${2:?path}" type="${3:-standard}"
    write="${4:-yes}" users="${5:-@users}" comment="${6:-}"
    mkdir -p "$path"; chmod 775 "$path"; chgrp users "$path" 2>/dev/null || true
    # Source share stanza generator from module
    source /opt/forgeos/install/modules/10b-samba-db.sh 2>/dev/null \
        && get_share_stanza "$name" "$path" "$type" "$write" "$users" "$comment" \
        > "$SHARES_DIR/${name}.share" \
        || { echo "ERROR: module not sourced"; exit 1; }
    rebuild
    echo "Share '$name' created → $path (type: $type)"
    ;;
auto-share)
    path="${1:?path}"
    name=$(basename "$path" | tr ' _' '--' | tr '[:upper:]' '[:lower:]')
    type=$(detect_db_type "$path")
    [[ "$type" != "standard" ]] && echo "  ⚠ Detected $type files — using $type share template (oplocks disabled)"
    /usr/local/bin/forgeos-samba create "$name" "$path" "$type" yes @users "Auto: $(basename "$path")"
    ;;
remove|rm)
    rm -f "$SHARES_DIR/${1:?name}.share"; rebuild; echo "Share '$1' removed"
    ;;
list)
    echo "=== ForgeOS Samba Shares ==="
    for f in "$SHARES_DIR"/*.share; do
        [[ -f "$f" ]] || continue
        local name; name=$(grep '^\[' "$f" | head -1 | tr -d '[]')
        local path; path=$(grep 'path' "$f" | head -1 | awk -F'= ' '{print $2}')
        local type=""
        grep -q 'oplocks.*=.*no' "$f" && type="[file-db/elevatedb]"
        grep -q 'time machine' "$f"   && type="[timemachine]"
        grep -q 'guest ok.*yes' "$f"  && type="[public-ro]"
        printf "  %-20s  %-38s  %s\n" "$name" "$path" "$type"
    done
    echo ""; smbstatus --shares 2>/dev/null | head -10 || true
    ;;
add-user)
    id "$1" &>/dev/null || useradd -m -s /bin/bash "$1"
    [[ -n "${2:-}" ]] && echo -e "${2}\n${2}" | smbpasswd -a "$1" -s || smbpasswd -a "$1"
    usermod -aG users "$1" 2>/dev/null || true
    echo "User '$1' added to Samba"
    ;;
remove-user) smbpasswd -x "$1" ;;
raw-get) cat /etc/samba/smb.conf; echo ""; cat "$SHARES_FILE" 2>/dev/null ;;
raw-put)
    echo "$1" > /tmp/smb-test.conf
    testparm -s /tmp/smb-test.conf &>/dev/null || { echo "Config test FAILED"; exit 1; }
    cp /etc/samba/smb.conf /etc/samba/smb.conf.bak
    echo "$1" > /etc/samba/smb.conf
    smbcontrol smbd reload-config 2>/dev/null || systemctl reload smbd
    echo "Saved and reloaded"
    ;;
reload) rebuild ;;
status) systemctl status smbd --no-pager | head -15 ;;
connections) smbstatus 2>/dev/null ;;
edb-info)
    # Print ElevateDB setup guidance
    cat << 'EDBINFO'
=== ElevateDB / Atrex File-DB Setup Guide ===

ElevateDB operates in two modes. Choose based on your user count:

MODE A: File Share (1-5 concurrent users)
  - Works out of the box with ForgeOS "elevatedb" share template
  - Samba oplocks are disabled — ElevateDB handles its own locking
  - Create the share:
      forgeos-samba create myapp /srv/nas/myapp elevatedb yes @users
  - Map drive on Windows: \\forgeos\myapp
  - Open the .EDB catalog file from the mapped drive in your app

MODE B: ElevateDB Server via Wine (5+ concurrent users)
  - ElevateDB Server manages all file I/O — no direct SMB file access
  - Clients connect via TCP (default port 12010)
  - Server is Windows binary — runs cleanly in Wine on Linux
  - Setup:
      1. forgeos-db start elevatedb-server   (requires EDB Server installer)
      2. Configure your app to use Remote session type
      3. Set server address to ForgeOS IP, port 12010
  - This is the architecturally correct solution for multi-user

FILE EXTENSIONS (ElevateDB):
  .EDB   — Database catalog
  .EDBT  — Table data file
  .EDBI  — Index file
  .EDBL  — Transaction log
  All must be accessible to all clients with read/write permissions.

CRITICAL SETTINGS (applied automatically to elevatedb shares):
  oplocks = no
  level2 oplocks = no
  kernel oplocks = no
  strict locking = no
  aio read size = 1
  aio write size = 1
EDBINFO
    ;;
help|*)
    echo "ForgeOS Samba Manager"
    echo "  create <n> <path> [type] [w] [users]  Create share"
    echo "  auto-share <path>                     Detect type and create"
    echo "  remove <n>"
    echo "  list"
    echo "  add-user <user> [pass]"
    echo "  raw-get / raw-put '<config>'"
    echo "  reload | status | connections"
    echo "  edb-info   ElevateDB/Atrex setup guide"
    echo ""
    echo "  Types: standard, elevatedb, sqlite, database, timemachine, public-ro, admin"
    echo ""
    echo "  'elevatedb' share type disables all oplocks for safe concurrent"
    echo "  access to ElevateDB, DBISAM, NexusDB, Paradox, dBase, Access."
    ;;
esac
SAMBACLI
    chmod +x /usr/local/bin/forgeos-samba
}

# ============================================================
# DATABASE COMPATIBILITY + ELEVATEDB SERVER (Wine)
# ============================================================
install_database_compat() {
    step "Installing database compatibility layer"

    mkdir -p /opt/forgeos/apps/databases /srv/forgeos/databases

    # ── MariaDB (MySQL-compatible) ──
    apt_install mariadb-server mariadb-client
    mysql -e "DELETE FROM mysql.user WHERE User='';" 2>/dev/null || true
    mysql -e "DROP DATABASE IF EXISTS test;" 2>/dev/null || true
    mysql -e "FLUSH PRIVILEGES;" 2>/dev/null || true
    local db_pass; db_pass=$(openssl rand -base64 24 | tr -d '/')
    mysql -e "CREATE USER IF NOT EXISTS 'forgeos_db'@'%' IDENTIFIED BY '${db_pass}';" 2>/dev/null || true
    mysql -e "GRANT ALL ON *.* TO 'forgeos_db'@'%' WITH GRANT OPTION;" 2>/dev/null || true
    mysql -e "FLUSH PRIVILEGES;" 2>/dev/null || true
    sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf 2>/dev/null || true
    forgenas_set "MARIADB_PASS" "$db_pass"
    enable_service mariadb

    # ── PostgreSQL ──
    apt_install postgresql postgresql-client
    enable_service postgresql

    # ── Redis ──
    apt_install redis-server
    sed -i 's/^bind 127.0.0.1.*/bind 0.0.0.0/' /etc/redis/redis.conf 2>/dev/null || true
    enable_service redis-server

    # ── ElevateDB Server via Wine Docker ──
    # ElevateDB Server is a small single-executable Windows binary.
    # It runs perfectly under Wine. This gives proper multi-user
    # client/server access — clients connect via TCP, never touch
    # the .EDB files directly over SMB. This eliminates ALL
    # file-locking corruption risk for 5+ concurrent users.
    cat > /opt/forgeos/apps/databases/elevatedb-server-compose.yml << 'EDBCOMP'
# ForgeOS — ElevateDB Server (Wine)
# Provides proper C/S multi-user access for ElevateDB applications
# including Atrex inventory software.
#
# SETUP:
#   1. Download ElevateDB Server from https://www.elevatesoft.com/download
#      (select "ElevateDB Server" — small single Windows executable)
#   2. Copy EDBSrvr.exe to /srv/forgeos/databases/elevatedb/
#   3. docker compose -f elevatedb-server-compose.yml up -d
#   4. Configure your ElevateDB app to use Remote session, port 12010
#
# WHY THIS WORKS:
#   Wine implements the Win32 file I/O APIs that ElevateDB Server uses.
#   ElevateDB Server handles all locking internally — clients connect
#   via TCP, never access .EDB files directly. No SMB locking issues.

version: "3.8"
services:
  elevatedb-server:
    image: scottyhardy/docker-wine:latest
    container_name: forgeos-elevatedb
    restart: unless-stopped
    environment:
      - DISPLAY_WIDTH=0
      - DISPLAY_HEIGHT=0
    volumes:
      - /srv/forgeos/databases/elevatedb:/edbdata
      - /srv/nas:/srv/nas          # Exposes NAS shares to EDB server
    ports:
      - "12010:12010"              # ElevateDB default server port
    command: >
      wine /edbdata/EDBSrvr.exe
      -configfile /edbdata/edbsrvr.ini
    networks:
      - forgeos-internal

networks:
  forgeos-internal:
    external: true
EDBCOMP

    # ElevateDB server INI template
    mkdir -p /srv/forgeos/databases/elevatedb
    cat > /srv/forgeos/databases/elevatedb/edbsrvr.ini << 'EDBINI'
[ElevateDB Server]
; ForgeOS ElevateDB Server Configuration
; Place your .EDB database files in this directory or subdirectories

; Server listening address and port
Address=0.0.0.0
Port=12010

; Data directory — where your .EDB catalog files live
DatabaseDirectory=/edbdata/databases

; Maximum concurrent sessions
MaxSessions=50

; Session timeout (seconds) — 0 = no timeout
SessionTimeout=0

; Logging
LogEnabled=True
LogFileName=/edbdata/edbsrvr.log
LogMaxSize=10485760

; Security — change these before production use
AdminPassword=changeme

[Database1]
; Add your databases here
; Name=MyDatabase
; Path=/edbdata/databases/mydb
EDBINI

    # ── Firebird (for .fdb/.gdb apps) ──
    cat > /opt/forgeos/apps/databases/firebird-compose.yml << 'FBCOMP'
version: "3.8"
services:
  firebird:
    image: jacobalberty/firebird:latest
    container_name: forgeos-firebird
    restart: unless-stopped
    environment:
      ISC_PASSWORD: "${FIREBIRD_PASSWORD:-changeme}"
    volumes:
      - /srv/forgeos/databases/firebird:/firebird/data
      - /srv/nas:/srv/nas:ro
    ports:
      - "127.0.0.1:3050:3050"
FBCOMP

    # ── MSSQL (optional, for .NET apps) ──
    cat > /opt/forgeos/apps/databases/mssql-compose.yml << 'MSSQL'
version: "3.8"
services:
  mssql:
    image: mcr.microsoft.com/mssql/server:2022-latest
    container_name: forgeos-mssql
    restart: unless-stopped
    environment:
      ACCEPT_EULA: "Y"
      SA_PASSWORD: "${MSSQL_SA_PASSWORD:?Set MSSQL_SA_PASSWORD}"
      MSSQL_PID: "Express"
    volumes:
      - /srv/forgeos/databases/mssql:/var/opt/mssql
    ports:
      - "127.0.0.1:1433:1433"
MSSQL

    # ── forgeos-db CLI ──
    cat > /usr/local/bin/forgeos-db << 'DBCLI'
#!/usr/bin/env bash
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true

case "$CMD" in
status)
    echo "=== ForgeOS Database Services ==="
    for svc in mariadb postgresql redis-server; do
        systemctl is-active "$svc" &>/dev/null \
            && printf "  ✓ %-20s running\n" "$svc" \
            || printf "  ✗ %-20s stopped\n" "$svc"
    done
    for ctr in forgeos-elevatedb forgeos-firebird forgeos-mssql; do
        docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$ctr" \
            && printf "  ✓ %-20s running\n" "$ctr" \
            || printf "  — %-20s not started\n" "$ctr"
    done
    ;;
start)
    case "${1:-}" in
        elevatedb|edb)
            [[ -f /srv/forgeos/databases/elevatedb/EDBSrvr.exe ]] \
                || { echo "EDBSrvr.exe not found in /srv/forgeos/databases/elevatedb/"; echo "Download from elevatesoft.com/download"; exit 1; }
            docker compose -f /opt/forgeos/apps/databases/elevatedb-server-compose.yml up -d
            echo "ElevateDB Server started on port 12010"
            echo "Configure your app: Remote session → $(hostname -I | awk '{print $1}'):12010"
            ;;
        firebird) docker compose -f /opt/forgeos/apps/databases/firebird-compose.yml up -d ;;
        mssql)
            [[ -z "${MSSQL_SA_PASSWORD:-}" ]] \
                && { echo "Set MSSQL_SA_PASSWORD env var first"; exit 1; }
            docker compose -f /opt/forgeos/apps/databases/mssql-compose.yml up -d ;;
        *) echo "Usage: forgeos-db start [elevatedb|firebird|mssql]" ;;
    esac
    ;;
stop)
    case "${1:-}" in
        elevatedb|edb) docker compose -f /opt/forgeos/apps/databases/elevatedb-server-compose.yml down ;;
        firebird)      docker compose -f /opt/forgeos/apps/databases/firebird-compose.yml down ;;
        mssql)         docker compose -f /opt/forgeos/apps/databases/mssql-compose.yml down ;;
    esac
    ;;
mariadb-create)
    mysql -e "CREATE DATABASE IF NOT EXISTS \`${1:?dbname}\`;"
    mysql -e "CREATE USER IF NOT EXISTS '${2:?user}'@'%' IDENTIFIED BY '${3:?pass}';"
    mysql -e "GRANT ALL ON \`${1}\`.* TO '${2}'@'%'; FLUSH PRIVILEGES;"
    echo "MariaDB: database '$1' created, user '$2' granted access"
    ;;
pg-create)
    sudo -u postgres createuser "${2:?user}" 2>/dev/null || true
    sudo -u postgres createdb -O "${2}" "${1:?dbname}" 2>/dev/null || true
    echo "PostgreSQL: database '$1' created for user '$2'"
    ;;
edb-setup)
    forgeos-samba edb-info
    ;;
sqlite-optimize)
    # Apply WAL mode to all SQLite files on NAS (safe for multi-reader)
    local path="${1:-/srv/nas}"
    local count=0
    while IFS= read -r -d '' f; do
        sqlite3 "$f" "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA wal_autocheckpoint=1000;" 2>/dev/null \
            && (( count++ )) || true
    done < <(find "$path" -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" -print0 2>/dev/null)
    echo "WAL mode applied to $count SQLite files"
    ;;
help|*)
    echo "ForgeOS Database Manager"
    echo "  status"
    echo "  start [elevatedb|firebird|mssql]"
    echo "  stop  [elevatedb|firebird|mssql]"
    echo "  mariadb-create <db> <user> <pass>"
    echo "  pg-create <db> <user>"
    echo "  edb-setup         ElevateDB/Atrex setup guide"
    echo "  sqlite-optimize [path]  Apply WAL mode to SQLite files"
    echo ""
    echo "Always-on: MariaDB (:3306), PostgreSQL (:5432), Redis (:6379)"
    echo "On-demand: ElevateDB Server (:12010), Firebird (:3050), MSSQL (:1433)"
    ;;
esac
DBCLI
    chmod +x /usr/local/bin/forgeos-db
    info "Database compatibility layer installed"
}

# ============================================================
# DEFAULT SHARES
# ============================================================
create_default_shares() {
    step "Creating default shares"
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    local base="${PRIMARY_POOL_MOUNT:-/srv/nas}"

    /usr/local/bin/forgeos-samba create "data"        "${base}/data"       standard  yes "@users"  "Data"
    /usr/local/bin/forgeos-samba create "media"       "${base}/media"      standard  yes "@users"  "Media"
    /usr/local/bin/forgeos-samba create "public"      "${base}/public"     public-ro no  ""        "Public"
    /usr/local/bin/forgeos-samba create "backups"     "${base}/backups"    admin     yes "@admins" "Backups"

    mkdir -p "${base}/timemachine"; chmod 1777 "${base}/timemachine"
    /usr/local/bin/forgeos-samba create "timemachine" "${base}/timemachine" timemachine yes "@users" "Mac Time Machine"

    info "Default shares: data, media, public, backups, timemachine"
}

# ============================================================
# MAIN
# ============================================================
install_samba_managed
create_samba_cli
create_default_shares
install_database_compat

info "Samba + Database Compatibility module complete"
info "  ElevateDB guide:  forgeos-samba edb-info"
info "  EDB file share:   forgeos-samba create mydb /srv/nas/mydb elevatedb"
info "  EDB server mode:  forgeos-db start elevatedb  (requires EDBSrvr.exe)"
info "  DB status:        forgeos-db status"
