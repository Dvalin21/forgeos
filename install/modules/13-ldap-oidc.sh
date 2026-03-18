#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 13 - LDAP + OIDC Authentication
#
# Stack:
#   lldap      — Lightweight LDAP server (Rust, Docker)
#                Replaces OpenLDAP for simple use cases.
#                No schemas, no ACI headaches — just works.
#                Ports: 3890 (LDAP), 17170 (HTTP admin UI)
#                Used by: Samba, Authentik, monitoring, mail
#
#   Authentik  — OIDC/OAuth2 identity provider + SSO
#                Provides login portal for all ForgeOS services.
#                2FA: TOTP (Google Authenticator, Authy) + WebAuthn
#                Ports: 9000 (HTTP), 9443 (HTTPS)
#                nginx proxy: auth.domain
#
# Architecture:
#   lldap ← stores users/groups
#   Authentik ← reads lldap via LDAP, issues OIDC tokens
#   nginx/services ← trust Authentik tokens via forward_auth
#
# This is optional — ForgeOS works with local auth.
# Enable when: multiple users, SSO across services needed.
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

AUTH_DIR="/opt/forgeos/apps/auth"
AUTH_DATA="/srv/forgeos/auth"
COMPOSE_FILE="${AUTH_DIR}/docker-compose.yml"

mkdir -p "$AUTH_DIR" "${AUTH_DATA}"/{lldap,authentik/{media,certs,custom-templates}}

# ============================================================
# GENERATE SECRETS
# ============================================================
generate_secrets() {
    step "Generating authentication secrets"

    local lldap_jwt;    lldap_jwt=$(gen_password 48)
    local lldap_pass;   lldap_pass=$(gen_password 24)
    local ak_secret;    ak_secret=$(gen_password 48)
    local ak_pg_pass;   ak_pg_pass=$(gen_password 24)
    local ak_admin_tok; ak_admin_tok=$(gen_password 32)

    forgenas_set "LLDAP_JWT_SECRET"    "$lldap_jwt"
    forgenas_set "LLDAP_LDAP_PASS"     "$lldap_pass"
    forgenas_set "AUTHENTIK_SECRET"    "$ak_secret"
    forgenas_set "AUTHENTIK_PG_PASS"   "$ak_pg_pass"
    forgenas_set "AUTHENTIK_ADMIN_TOK" "$ak_admin_tok"

    # Write env file for Docker Compose
    cat > "${AUTH_DIR}/.env" << ENV
LLDAP_JWT_SECRET=${lldap_jwt}
LLDAP_LDAP_PASS=${lldap_pass}
AUTHENTIK_SECRET=${ak_secret}
AUTHENTIK_PG_PASS=${ak_pg_pass}
ENV
    chmod 600 "${AUTH_DIR}/.env"
    info "Auth secrets generated"
}

# ============================================================
# DOCKER COMPOSE
# ============================================================
write_compose() {
    step "Writing auth stack compose file"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    cat > "$COMPOSE_FILE" << COMPOSE
version: "3.8"

networks:
  auth:
    name: forgeos-auth
  forgeos-internal:
    external: true

volumes:
  lldap_data:
    driver: local
    driver_opts: {type: none, o: bind, device: ${AUTH_DATA}/lldap}
  authentik_pg_data:
    driver: local
  authentik_redis_data:
    driver: local

services:

  # ── lldap ──────────────────────────────────────────────────
  lldap:
    image: lldap/lldap:stable
    container_name: forgeos-lldap
    restart: unless-stopped
    ports:
      - "127.0.0.1:3890:3890"   # LDAP (internal only)
      - "127.0.0.1:17170:17170" # Admin UI
    volumes:
      - lldap_data:/data
    environment:
      - TZ=${TIMEZONE:-UTC}
      - LLDAP_JWT_SECRET=\${LLDAP_JWT_SECRET}
      - LLDAP_LDAP_USER_PASS=\${LLDAP_LDAP_PASS}
      - LLDAP_LDAP_BASE_DN=dc=${domain//./,dc=}
      - LLDAP_HTTP_PORT=17170
      - LLDAP_LDAP_PORT=3890
      - LLDAP_VERBOSE=false
    networks: [auth, forgeos-internal]

  # ── PostgreSQL (Authentik backend) ─────────────────────────
  authentik-postgresql:
    image: postgres:15-alpine
    container_name: forgeos-authentik-pg
    restart: unless-stopped
    environment:
      POSTGRES_DB:       authentik
      POSTGRES_USER:     authentik
      POSTGRES_PASSWORD: \${AUTHENTIK_PG_PASS}
    volumes:
      - authentik_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U authentik"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks: [auth]

  # ── Redis (Authentik cache) ─────────────────────────────────
  authentik-redis:
    image: redis:alpine
    container_name: forgeos-authentik-redis
    restart: unless-stopped
    command: --save 60 1 --loglevel warning
    volumes:
      - authentik_redis_data:/data
    networks: [auth]

  # ── Authentik Server ────────────────────────────────────────
  authentik-server:
    image: ghcr.io/goauthentik/server:latest
    container_name: forgeos-authentik
    restart: unless-stopped
    command: server
    environment:
      AUTHENTIK_REDIS__HOST:       forgeos-authentik-redis
      AUTHENTIK_POSTGRESQL__HOST:  forgeos-authentik-pg
      AUTHENTIK_POSTGRESQL__USER:  authentik
      AUTHENTIK_POSTGRESQL__NAME:  authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: \${AUTHENTIK_PG_PASS}
      AUTHENTIK_SECRET_KEY:        \${AUTHENTIK_SECRET}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
      AUTHENTIK_DISABLE_UPDATE_CHECK: "true"
      AUTHENTIK_DISABLE_STARTUP_ANALYTICS: "true"
      AUTHENTIK_DEFAULT_USER_CHANGE_NAME:     "false"
      AUTHENTIK_DEFAULT_USER_CHANGE_EMAIL:    "true"
      AUTHENTIK_DEFAULT_USER_CHANGE_USERNAME: "false"
      AUTHENTIK_EMAIL__FROM:       "forgeos@${domain}"
      AUTHENTIK_EMAIL__HOST:       "localhost"
    volumes:
      - ${AUTH_DATA}/authentik/media:/media
      - ${AUTH_DATA}/authentik/custom-templates:/templates
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9443:9443"
    depends_on:
      authentik-postgresql:
        condition: service_healthy
      authentik-redis:
        condition: service_started
    networks: [auth, forgeos-internal]

  # ── Authentik Worker ────────────────────────────────────────
  authentik-worker:
    image: ghcr.io/goauthentik/server:latest
    container_name: forgeos-authentik-worker
    restart: unless-stopped
    command: worker
    user: root
    environment:
      AUTHENTIK_REDIS__HOST:       forgeos-authentik-redis
      AUTHENTIK_POSTGRESQL__HOST:  forgeos-authentik-pg
      AUTHENTIK_POSTGRESQL__USER:  authentik
      AUTHENTIK_POSTGRESQL__NAME:  authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: \${AUTHENTIK_PG_PASS}
      AUTHENTIK_SECRET_KEY:        \${AUTHENTIK_SECRET}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${AUTH_DATA}/authentik/media:/media
      - ${AUTH_DATA}/authentik/certs:/certs
    depends_on:
      - authentik-postgresql
      - authentik-redis
    networks: [auth]

COMPOSE

    chmod 600 "$COMPOSE_FILE"
    info "Auth compose file written"
}

# ============================================================
# NGINX PROXY FOR AUTH SERVICES
# ============================================================
configure_auth_nginx() {
    step "Configuring nginx for auth services"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"

    [[ ! -d /etc/nginx/forgeos.d ]] && { warn "nginx not configured yet (module 12)"; return 0; }

    cat > /etc/nginx/forgeos.d/auth.conf << NGINX
# ForgeOS Auth Services

# Authentik SSO
server {
    listen 443 ssl http2;
    server_name auth.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    location / {
        proxy_pass          http://127.0.0.1:9000;
        proxy_http_version  1.1;
        proxy_set_header    Host \$host;
        proxy_set_header    X-Real-IP \$remote_addr;
        proxy_set_header    X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto \$scheme;
        proxy_set_header    Upgrade \$http_upgrade;
        proxy_set_header    Connection "upgrade";
    }
}

# lldap admin UI
server {
    listen 443 ssl http2;
    server_name ldap-admin.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    # LAN access only
    allow $(forgenas_get LAN_CIDR 192.168.0.0/16);
    deny all;
    location / {
        proxy_pass http://127.0.0.1:17170;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX

    # Authentik forward_auth snippet — used by other services
    cat > /etc/nginx/snippets/authentik-forward-auth.conf << 'FWAUTH'
# Include this in any nginx server block to require Authentik SSO:
#   include snippets/authentik-forward-auth.conf;

auth_request /outpost.goauthentik.io/auth/nginx;
error_page 401 = @authentik_signin;

location @authentik_signin {
    internal;
    add_header Set-Cookie $auth_cookie;
    return 302 /outpost.goauthentik.io/start?rd=$request_uri;
}

location /outpost.goauthentik.io {
    proxy_pass          http://127.0.0.1:9000/outpost.goauthentik.io;
    proxy_set_header    Host $host;
    proxy_set_header    X-Original-URL $scheme://$http_host$request_uri;
    add_header          Set-Cookie $auth_cookie;
    auth_request_set    $auth_cookie $upstream_http_set_cookie;
}
FWAUTH

    nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || \
        warn "nginx auth config — verify after cert setup"

    info "nginx: auth.${domain}, ldap-admin.${domain}"
}

# ============================================================
# INITIAL lldap BOOTSTRAP
# Creates default groups: admins, users, media, nas-readonly
# ============================================================
bootstrap_lldap() {
    step "Bootstrapping lldap (waiting for container)"

    if ! wait_for_port 127.0.0.1 17170 60; then
        warn "lldap not ready after 60s — skipping bootstrap"
        warn "  Manual setup: https://ldap-admin.$(forgenas_get DOMAIN nas.local)"
        return 0
    fi

    sleep 3  # Extra settle time

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    # shellcheck disable=SC2034
    # shellcheck disable=SC2034
    local base_dn="dc=${DOMAIN//./,dc=}"
    local admin_pass="${LLDAP_LDAP_PASS:-}"

    # Create default groups via lldap API
    local token
    token=$(curl -sf -X POST "http://localhost:17170/auth/simple/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"${admin_pass}\"}" \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" \
        2>/dev/null || echo "")

    if [[ -z "$token" ]]; then
        warn "lldap API auth failed — bootstrap skipped"
        info "  Default lldap admin password: ${admin_pass}"
        return 0
    fi

    for group in admins users media nas-readonly; do
        curl -sf -X POST "http://localhost:17170/api/graphql" \
            -H "Authorization: Bearer ${token}" \
            -H "Content-Type: application/json" \
            -d "{\"query\":\"mutation { createGroup(name: \\\"${group}\\\") { id } }\"}" \
            >> "$FORGENAS_LOG" 2>&1 || true
    done

    info "lldap groups created: admins, users, media, nas-readonly"
    info "  lldap UI: https://ldap-admin.$(forgenas_get DOMAIN nas.local)"
    info "  lldap admin password: ${admin_pass}"
}

# ============================================================
# CLI
# ============================================================
install_auth_cli() {
    step "Installing forgeos-auth CLI"

    cat > /usr/local/bin/forgeos-auth << 'AUTHCLI'
#!/usr/bin/env bash
# ForgeOS Auth Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
CMD="${1:-help}"; shift || true
AUTH_DIR="/opt/forgeos/apps/auth"

_lldap_token() {
    curl -sf -X POST "http://localhost:17170/auth/simple/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"${LLDAP_LDAP_PASS}\"}" \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null
}

case "$CMD" in
status)
    echo "=== Auth Stack ==="
    for ctr in forgeos-lldap forgeos-authentik forgeos-authentik-pg forgeos-authentik-redis; do
        docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q "$ctr" \
            && printf "  ✓ %-35s\n" "$ctr" \
            || printf "  ✗ %-35s\n" "$ctr"
    done
    echo ""
    local domain; domain=$(grep ^DOMAIN /etc/forgeos/forgeos.conf | cut -d= -f2 | tr -d '"')
    echo "  SSO Portal:  https://auth.${domain}"
    echo "  LDAP Admin:  https://ldap-admin.${domain}"
    ;;
add-user)
    user="${1:?username}" pass="${2:?password}" email="${3:-${1}@$(grep ^DOMAIN /etc/forgeos/forgeos.conf | cut -d= -f2 | tr -d '"')}"
    tok=$(_lldap_token)
    [[ -z "$tok" ]] && { echo "lldap not running"; exit 1; }
    curl -sf -X POST "http://localhost:17170/api/graphql" \
        -H "Authorization: Bearer ${tok}" \
        -H "Content-Type: application/json" \
        -d "{\"query\":\"mutation { createUser(user: { id: \\\"${user}\\\", email: \\\"${email}\\\", displayName: \\\"${user}\\\" }) { id } }\"}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print('Created:',d.get('data',{}).get('createUser',{}).get('id','error'))"
    ;;
list-users)
    tok=$(_lldap_token)
    [[ -z "$tok" ]] && { echo "lldap not running"; exit 1; }
    curl -sf -X POST "http://localhost:17170/api/graphql" \
        -H "Authorization: Bearer ${tok}" \
        -H "Content-Type: application/json" \
        -d '{"query":"query { users { id displayName email } }"}' \
        | python3 -c "
import sys,json
for u in json.load(sys.stdin).get('data',{}).get('users',[]):
    print(f'  {u[\"id\"]:20s} {u.get(\"displayName\",\"\"):20s} {u.get(\"email\",\"\")}')
"
    ;;
restart)
    docker compose -f "${AUTH_DIR}/docker-compose.yml" restart
    echo "Auth stack restarted"
    ;;
logs)
    docker compose -f "${AUTH_DIR}/docker-compose.yml" logs --tail 50 "${1:-authentik-server}"
    ;;
help|*)
    echo "ForgeOS Auth Manager"
    echo "  status                     Auth stack status"
    echo "  add-user <user> <pass> [email]  Add user to lldap"
    echo "  list-users                 List all users"
    echo "  restart                    Restart auth stack"
    echo "  logs [service]             Container logs"
    echo ""
    echo "  2FA is configured via Authentik Web UI"
    echo "  TOTP (Google Auth/Authy) and WebAuthn supported"
    ;;
esac
AUTHCLI
    chmod +x /usr/local/bin/forgeos-auth
}

# ============================================================
# MAIN
# ============================================================
generate_secrets
write_compose

step "Starting auth stack"
docker_compose_pull "$AUTH_DIR"
docker_compose_up   "$AUTH_DIR"

configure_auth_nginx
bootstrap_lldap
install_auth_cli

forgenas_set "MODULE_AUTH_DONE"  "yes"
forgenas_set "FEATURE_LDAP"      "yes"
forgenas_set "LLDAP_BASE_DN"     "dc=${DOMAIN//./,dc=}"
forgenas_set "LLDAP_URL"         "ldap://127.0.0.1:3890"
forgenas_set "AUTHENTIK_URL"     "http://127.0.0.1:9000"

domain="${DOMAIN:-nas.local}"
info "LDAP + OIDC module complete"
info "  SSO portal:    https://auth.${domain}"
info "  lldap admin:   https://ldap-admin.${domain}  (admin / ${LLDAP_LDAP_PASS})"
info "  Authentik:     https://auth.${domain}/if/admin/"
info "  lldap groups:  admins, users, media, nas-readonly"
info ""
info "  2FA:           Configure in Authentik UI → Policies → MFA"
info "  Samba + LDAP:  forgeos-samba add-user (maps to lldap)"
warn "  Save the lldap admin password: ${LLDAP_LDAP_PASS}"
