#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 18 - Applications
#
# OnlyOffice  — self-hosted office suite (Docs server)
#               Works as browser editor for DOCX/XLSX/PPTX
#               Integrates with FileBrowser, Nextcloud, etc.
#               Port 8080 → proxied to office.domain
#
# Microsoft Fonts — required for true layout compatibility
#               in OnlyOffice with documents created in MS Office.
#               Without them: fonts substitute, layouts shift.
#               Package: ttf-mscorefonts-installer (multiverse)
#               Includes: Arial, Times New Roman, Courier New,
#               Verdana, Georgia, Trebuchet, Impact, Comic Sans,
#               Webdings, Wingdings, and others.
#               LICENSE: Microsoft's end-user license applies.
#               Free for use but not redistribution.
#
# Immich      — self-hosted Google Photos alternative
#               AI face recognition, object detection
#               Port 2283 → proxied to photos.domain
#               GPU-accelerated ML via CUDA/VA-API if available
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

APPS_DIR="/opt/forgeos/apps"
APP_DATA="/srv/forgeos"

# ============================================================
# MICROSOFT FONTS
# Required before OnlyOffice installs — fonts must be present
# in the host and will be mounted into the container.
# ============================================================
install_microsoft_fonts() {
    step "Installing Microsoft Core Fonts"

    # Enable multiverse (Ubuntu) or contrib (Debian)
    local distro; distro=$(lsb_release -is)
    if [[ "$distro" == "Ubuntu" ]]; then
        add-apt-repository -y multiverse >> "$FORGENAS_LOG" 2>&1 || true
        _apt_ready=false
    else
        # Debian: add contrib
        sed -i 's/^deb \(.*\) main$/deb \1 main contrib non-free/' /etc/apt/sources.list 2>/dev/null || true
        _apt_ready=false
    fi

    # Accept EULA non-interactively
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
        | debconf-set-selections

    apt_install ttf-mscorefonts-installer fontconfig

    # Build font cache
    fc-cache -fv >> "$FORGENAS_LOG" 2>&1 || true

    # Verify key fonts are present
    local fonts_ok=true
    for font in arial.ttf times.ttf couri.ttf verdana.ttf georgia.ttf; do
        if ! fc-list 2>/dev/null | grep -qi "${font%.ttf}"; then
            warn "Font may be missing: ${font%.ttf}"
            fonts_ok=false
        fi
    done

    if $fonts_ok; then
        info "Microsoft fonts installed: Arial, Times New Roman, Courier New, Verdana, Georgia"
        info "  + Trebuchet MS, Impact, Comic Sans MS, Webdings, Wingdings"
    else
        warn "Some Microsoft fonts may be missing — OnlyOffice will use substitutes"
        info "  Manual install attempt: dpkg-reconfigure ttf-mscorefonts-installer"
    fi

    # Font directory for container mount
    local ms_font_dir="/usr/share/fonts/truetype/msttcorefonts"
    [[ -d "$ms_font_dir" ]] || ms_font_dir="/usr/share/fonts/truetype/mscorefonts"
    [[ -d "$ms_font_dir" ]] || ms_font_dir=$(fc-list 2>/dev/null | grep -i "arial" | head -1 | cut -d: -f1 | xargs dirname || echo "")

    forgenas_set "MS_FONTS_DIR" "${ms_font_dir:-/usr/share/fonts/truetype}"
    info "Font directory: ${ms_font_dir:-unknown}"

    # Also install additional free fonts for better document compatibility
    apt_install_optional \
        fonts-liberation \
        fonts-dejavu-extra \
        fonts-noto-core \
        fonts-open-sans \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea

    fc-cache -f >> "$FORGENAS_LOG" 2>&1 || true
    info "Additional compatibility fonts: Liberation, DejaVu, Noto, Open Sans, Carlito, Caladea"
}

# ============================================================
# ONLYOFFICE DOCUMENT SERVER
# ============================================================
install_onlyoffice() {
    step "Installing OnlyOffice Document Server"

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"
    local ms_fonts_dir="${MS_FONTS_DIR:-/usr/share/fonts/truetype}"
    local oo_dir="${APPS_DIR}/onlyoffice"
    local oo_data="${APP_DATA}/onlyoffice"
    local oo_secret; oo_secret=$(gen_password 32)

    mkdir -p "$oo_dir" "${oo_data}"/{logs,data,lib,db}
    forgenas_set "ONLYOFFICE_SECRET" "$oo_secret"

    cat > "${oo_dir}/docker-compose.yml" << OODOCS
version: "3.8"
# OnlyOffice Document Server
# Accessible at: https://office.${domain}
# JWT secret: stored in /etc/forgeos/forgeos.conf

services:
  onlyoffice:
    image: onlyoffice/documentserver:latest
    container_name: forgeos-onlyoffice
    restart: unless-stopped

    ports:
      - "127.0.0.1:8080:80"

    environment:
      # JWT security — prevent unauthorized document access
      JWT_ENABLED:  "true"
      JWT_SECRET:   "${oo_secret}"
      JWT_HEADER:   "AuthorizationJwt"
      JWT_IN_BODY:  "true"

      # Database
      DB_TYPE: sqlite3

      # Memory limits per document (MB)
      ALLOW_META_IP_ADDRESS: "true"
      ALLOW_PRIVATE_IP_ADDRESS: "true"

    volumes:
      # Data persistence
      - ${oo_data}/logs:/var/log/onlyoffice
      - ${oo_data}/data:/var/www/onlyoffice/Data
      - ${oo_data}/lib:/var/lib/onlyoffice
      - ${oo_data}/db:/var/lib/postgresql

      # Microsoft fonts — mounted from host
      # This is why we install them on the host first.
      # OnlyOffice uses these for pixel-perfect MS Office layout rendering.
      - ${ms_fonts_dir}:/usr/share/fonts/truetype/custom:ro

    # Resource limits — OnlyOffice is memory hungry
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M

    networks:
      - forgeos-internal

networks:
  forgeos-internal:
    external: true
OODOCS

    # nginx reverse proxy
    if [[ -d /etc/nginx/forgeos.d ]]; then
        cat > /etc/nginx/forgeos.d/onlyoffice.conf << NGINX
# OnlyOffice Document Server
server {
    listen 443 ssl http2;
    server_name office.${domain};

    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    # Required for large document uploads
    client_max_body_size 0;
    proxy_request_buffering off;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";

        # Required for OnlyOffice WebSocket
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
NGINX
        nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi

    # Start container
    docker_compose_pull "$oo_dir"
    docker_compose_up   "$oo_dir"

    if wait_for_port 127.0.0.1 8080 60; then
        info "OnlyOffice started on port 8080"
    else
        info "OnlyOffice starting (may take 2-3 minutes first boot)"
    fi

    info "OnlyOffice: https://office.${domain}"
    info "  JWT Secret: ${oo_secret} (needed to integrate with other apps)"
    info "  Microsoft fonts: mounted from ${ms_fonts_dir}"
    forgenas_set "ONLYOFFICE_URL" "https://office.${domain}"
}

# ============================================================
# IMMICH — AI-Powered Photo Library
# ============================================================
install_immich() {
    step "Installing Immich photo library"

    source "$FORGENAS_CONFIG"
    local domain="${DOMAIN:-nas.local}"
    local immich_dir="${APPS_DIR}/immich"
    local immich_data="${APP_DATA}/immich"
    local immich_pg_pass; immich_pg_pass=$(gen_password 24)
    local immich_secret; immich_secret=$(gen_password 32)

    mkdir -p "$immich_dir" "${immich_data}"/{photos,profile,thumbs,encoded,postgres}
    forgenas_set "IMMICH_PG_PASS"  "$immich_pg_pass"
    forgenas_set "IMMICH_SECRET"   "$immich_secret"

    cat > "${immich_dir}/.env" << IMMENV
# Immich environment — managed by ForgeOS
DB_PASSWORD=${immich_pg_pass}
DB_USERNAME=immich
DB_DATABASE_NAME=immich
IMMICH_SECRET=${immich_secret}
UPLOAD_LOCATION=${immich_data}/photos
EXTERNAL_PATH=/srv/nas/media
THUMBS_PATH=${immich_data}/thumbs
ENCODED_VIDEO_PATH=${immich_data}/encoded
PROFILE_IMAGE_PATH=${immich_data}/profile
DB_DATA_LOCATION=${immich_data}/postgres
IMMENV
    chmod 600 "${immich_dir}/.env"

    cat > "${immich_dir}/docker-compose.yml" << IMMICH
version: "3.8"
# Immich — self-hosted Google Photos
# https://photos.${domain}

name: immich

services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:release
    container_name: immich-server
    restart: unless-stopped
    volumes:
      - \${UPLOAD_LOCATION}:/usr/src/app/upload
      - \${EXTERNAL_PATH}:/external:ro
      - \${THUMBS_PATH}:/usr/src/app/upload/thumbs
      - \${ENCODED_VIDEO_PATH}:/usr/src/app/upload/encoded-video
      - \${PROFILE_IMAGE_PATH}:/usr/src/app/upload/profile
    env_file: .env
    ports:
      - "127.0.0.1:2283:2283"
    depends_on:
      - database
      - redis
    networks: [immich-net, forgeos-internal]

  immich-machine-learning:
    image: ghcr.io/immich-app/immich-machine-learning:release
    container_name: immich-machine-learning
    restart: unless-stopped
    volumes:
      - immich-model-cache:/cache
    env_file: .env
$(
    # GPU acceleration for ML if available
    if [[ "${GPU_NVIDIA:-false}" == "true" ]]; then
        echo "    runtime: nvidia"
        echo "    environment:"
        echo "      - NVIDIA_VISIBLE_DEVICES=all"
    elif [[ "${GPU_INTEL:-false}" == "true" || "${GPU_AMD:-false}" == "true" ]]; then
        echo "    devices:"
        echo "      - /dev/dri:/dev/dri"
    fi
)
    networks: [immich-net]

  redis:
    image: redis:7-alpine
    container_name: immich-redis
    restart: unless-stopped
    networks: [immich-net]

  database:
    image: tensorchord/pgvecto-rs:pg14-v0.2.0
    container_name: immich-postgres
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD:    \${DB_PASSWORD}
      POSTGRES_USER:        \${DB_USERNAME}
      POSTGRES_DB:          \${DB_DATABASE_NAME}
      POSTGRES_INITDB_ARGS: "--data-checksums"
    volumes:
      - \${DB_DATA_LOCATION}:/var/lib/postgresql/data
    command: >
      postgres
      -c shared_preload_libraries=vectors.so
      -c search_path="\$user", public, vectors
      -c logging_collector=on
      -c max_wal_size=2GB
      -c shared_buffers=512MB
      -c wal_compression=lz4
    networks: [immich-net]

volumes:
  immich-model-cache:

networks:
  immich-net:
    name: forgeos-immich
  forgeos-internal:
    external: true
IMMICH

    # nginx proxy
    if [[ -d /etc/nginx/forgeos.d ]]; then
        cat > /etc/nginx/forgeos.d/immich.conf << NGINX
server {
    listen 443 ssl http2;
    server_name photos.${domain};
    ssl_certificate     /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    client_max_body_size 0;
    proxy_request_buffering off;
    location / {
        proxy_pass         http://127.0.0.1:2283;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_read_timeout 600s;
    }
}
NGINX
        nginx -t >> "$FORGENAS_LOG" 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi

    docker_compose_pull "$immich_dir"
    docker_compose_up   "$immich_dir"

    info "Immich: https://photos.${domain}"
    info "  Photos directory: ${immich_data}/photos"
    info "  External media (read-only): /srv/nas/media"
    forgenas_set "IMMICH_URL" "https://photos.${domain}"
}

# ============================================================
# MAIN
# ============================================================
install_microsoft_fonts
install_onlyoffice
install_immich

forgenas_set "MODULE_APPS_DONE" "yes"

local domain="${DOMAIN:-nas.local}"
info "Applications module complete"
info "  OnlyOffice:  https://office.${domain}"
info "  Immich:      https://photos.${domain}"
info "  MS Fonts:    $(fc-list 2>/dev/null | grep -ic arial) fonts installed"
