#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 22 - FOG Imaging
#
# FOG Project - Free Open-Source Ghost
# Network imaging and computer management solution
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

install_fog() {
    step "Installing FOG Imaging Server"

    apt_install \
        apache2 \
        mysql-server \
        php \
        php-mysql \
        php-gd \
        php-fpm \
        php-curl \
        php-json \
        php-xml \
        net-tools \
        wget \
        gzip \
        tar \
        locate

    if [ ! -d /opt/fog ]; then
        _progress "Cloning FOG repository"
        git clone --depth 1 https://github.com/FOGProject/fogproject.git /opt/fog \
            >> "$FORGENAS_LOG" 2>&1
        _done
    fi

    info "FOG repository ready at /opt/fog"
}

configure_fog() {
    step "Configuring FOG Imaging"

    _progress "Creating FOG storage directory"
    mkdir -p /images
    mkdir -p /images/dev
    chown -R fog:fog /images 2>/dev/null || true
    chmod -R 755 /images
    _done

    _progress "Configuring Apache for FOG"
    a2enmod php-fpm >> "$FORGENAS_LOG" 2>&1 || true
    a2enmod rewrite >> "$FORGENAS_LOG" 2>&1 || true
    systemctl restart apache2 >> "$FORGENAS_LOG" 2>&1 || true
    _done

    info "FOG web configuration ready"
    info "Run /opt/fog/bin/installfog.sh to complete FOG setup"
}

mark_complete() {
    mkdir -p "$FORGEOS_MODULES_DONE"
    touch "$FORGEOS_MODULES_DONE/22-imaging"
    info "FOG Imaging module complete"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    require_root
    install_fog
    configure_fog
    mark_complete
fi