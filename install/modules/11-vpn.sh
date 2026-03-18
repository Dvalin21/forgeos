#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 11 - VPN
#
# Two complementary VPN options:
#
#   WireGuard — classic hub-and-spoke VPN server
#     - ForgeOS is the server (UDP 51820)
#     - Clients connect in from anywhere
#     - Full tunnel or split-tunnel per client
#     - Web UI generates per-client QR codes / .conf files
#     - forgeos-vpn CLI for peer management
#
#   Netbird — zero-config mesh VPN (optional)
#     - P2P when possible, relay when NAT blocks direct
#     - No port forwarding required
#     - Self-hosted or netbird.io managed plane
#     - Better for connecting multiple ForgeOS nodes
# ============================================================
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

WG_DIR="/etc/wireguard"
WG_IF="wg0"
WG_PORT=51820
WG_NET="10.10.0.0/24"
WG_SERVER_IP="10.10.0.1"
WG_PEERS_DIR="/etc/forgeos/vpn/peers"

mkdir -p "$WG_PEERS_DIR" /etc/forgeos/vpn
chmod 700 /etc/forgeos/vpn "$WG_PEERS_DIR"

# ============================================================
# WIREGUARD SERVER
# ============================================================
install_wireguard() {
    step "Installing WireGuard"
    apt_install wireguard wireguard-tools qrencode
}

generate_server_keys() {
    step "Generating WireGuard server keys"

    [[ -f "${WG_DIR}/server.key" ]] && {
        info "Server keys already exist — skipping keygen"
        return 0
    }

    mkdir -p "$WG_DIR"
    chmod 700 "$WG_DIR"

    wg genkey | tee "${WG_DIR}/server.key" | wg pubkey > "${WG_DIR}/server.pub"
    chmod 600 "${WG_DIR}/server.key"

    local pub; pub=$(cat "${WG_DIR}/server.pub")
    forgenas_set "WG_SERVER_PUBKEY" "$pub"
    info "WireGuard server keypair generated"
}

configure_wireguard_server() {
    step "Configuring WireGuard server"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local server_key; server_key=$(cat "${WG_DIR}/server.key")
    local public_ip; public_ip=$(curl -sf --max-time 5 https://api.ipify.org || \
                                 curl -sf --max-time 5 https://ifconfig.me || \
                                 echo "$(ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)")
    forgenas_set "PUBLIC_IP" "$public_ip"

    cat > "${WG_DIR}/${WG_IF}.conf" << WGCONF
# ForgeOS WireGuard Server Configuration
# Managed by: forgeos-vpn  |  Web UI: Network > VPN
# DO NOT edit manually — use the CLI or Web UI

[Interface]
Address    = ${WG_SERVER_IP}/24
ListenPort = ${WG_PORT}
PrivateKey = ${server_key}

# NAT: forward VPN traffic to LAN and internet
PostUp   = ufw route allow in on ${WG_IF} out on ${NIC_PRIMARY:-eth0}; \
           iptables -t nat -A POSTROUTING -s ${WG_NET} -o ${NIC_PRIMARY:-eth0} -j MASQUERADE; \
           ip6tables -t nat -A POSTROUTING -s fd00::/8 -o ${NIC_PRIMARY:-eth0} -j MASQUERADE
PostDown = ufw route delete allow in on ${WG_IF} out on ${NIC_PRIMARY:-eth0}; \
           iptables -t nat -D POSTROUTING -s ${WG_NET} -o ${NIC_PRIMARY:-eth0} -j MASQUERADE; \
           ip6tables -t nat -D POSTROUTING -s fd00::/8 -o ${NIC_PRIMARY:-eth0} -j MASQUERADE

# Peers are appended below by forgeos-vpn
# ── PEERS ──

WGCONF
    chmod 600 "${WG_DIR}/${WG_IF}.conf"

    # IP forwarding
    echo "net.ipv4.ip_forward = 1"  > /etc/sysctl.d/91-wireguard.conf
    echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.d/91-wireguard.conf
    sysctl -p /etc/sysctl.d/91-wireguard.conf >> "$FORGENAS_LOG" 2>&1

    # UFW
    ufw allow "${WG_PORT}/udp" comment "WireGuard VPN"

    enable_service "wg-quick@${WG_IF}"
    info "WireGuard server: ${WG_SERVER_IP} on UDP ${WG_PORT}"
    info "  Public endpoint: ${public_ip}:${WG_PORT}"
}

# ============================================================
# PEER MANAGEMENT CLI
# ============================================================
install_vpn_cli() {
    step "Installing forgeos-vpn CLI"

    cat > /usr/local/bin/forgeos-vpn << 'VPNCLI'
#!/usr/bin/env bash
# ForgeOS VPN Manager
source /etc/forgeos/forgeos.conf 2>/dev/null || true
set -euo pipefail

WG_IF="wg0"
WG_DIR="/etc/wireguard"
WG_CONF="${WG_DIR}/${WG_IF}.conf"
WG_NET="10.10.0"
PEERS_DIR="/etc/forgeos/vpn/peers"
CMD="${1:-help}"; shift || true

# Find next available IP in 10.10.0.x (starts at .2, server is .1)
next_ip() {
    local used; used=$(grep -oP '10\.10\.0\.\K\d+' "${WG_DIR}/${WG_IF}.conf" 2>/dev/null || echo "")
    for i in $(seq 2 254); do
        echo "$used" | grep -qw "$i" || { echo "${WG_NET}.${i}"; return; }
    done
    echo ""; return 1
}

add_peer() {
    local name="${1:?peer name}" dns="${2:-1.1.1.1}" allowed_ips="${3:-0.0.0.0/0}"
    local ip; ip=$(next_ip) || { echo "No IPs available"; exit 1; }
    local peer_dir="${PEERS_DIR}/${name}"
    mkdir -p "$peer_dir"; chmod 700 "$peer_dir"

    # Generate peer keys
    wg genkey | tee "${peer_dir}/private.key" | wg pubkey > "${peer_dir}/public.key"
    wg genpsk > "${peer_dir}/preshared.key"
    chmod 600 "${peer_dir}/private.key" "${peer_dir}/preshared.key"

    local peer_priv; peer_priv=$(cat "${peer_dir}/private.key")
    local peer_pub;  peer_pub=$(cat "${peer_dir}/public.key")
    local psk;       psk=$(cat "${peer_dir}/preshared.key")
    local srv_pub;   srv_pub=$(cat "${WG_DIR}/server.pub")
    local endpoint="${PUBLIC_IP:-$(curl -sf https://api.ipify.org)}:51820"

    # Write client .conf
    cat > "${peer_dir}/${name}.conf" << PEERCONF
# ForgeOS WireGuard — Client: ${name}
# Generated: $(date)

[Interface]
PrivateKey = ${peer_priv}
Address    = ${ip}/32
DNS        = ${dns}

[Peer]
PublicKey    = ${srv_pub}
PresharedKey = ${psk}
Endpoint     = ${endpoint}
AllowedIPs   = ${allowed_ips}
PersistentKeepalive = 25
PEERCONF
    chmod 600 "${peer_dir}/${name}.conf"

    # Append peer to server config
    cat >> "$WG_CONF" << SVPEER

[Peer]
# ${name}
PublicKey    = ${peer_pub}
PresharedKey = ${psk}
AllowedIPs   = ${ip}/32
SVPEER

    # Hot-reload WireGuard (no reconnect needed)
    wg addconf "$WG_IF" <(echo "[Peer]
PublicKey    = ${peer_pub}
PresharedKey = ${psk}
AllowedIPs   = ${ip}/32") 2>/dev/null || systemctl reload "wg-quick@${WG_IF}" 2>/dev/null || true

    # Store metadata
    echo "{\"name\":\"${name}\",\"ip\":\"${ip}\",\"created\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"allowed_ips\":\"${allowed_ips}\"}" \
        > "${peer_dir}/meta.json"

    echo ""
    echo "  Peer '${name}' added: ${ip}"
    echo "  Config: ${peer_dir}/${name}.conf"
    echo ""

    # QR code for mobile
    echo "  QR code (scan with WireGuard mobile app):"
    qrencode -t ansiutf8 < "${peer_dir}/${name}.conf" 2>/dev/null \
        || echo "  (qrencode not available — use config file)"
}

remove_peer() {
    local name="${1:?peer name}"
    local peer_dir="${PEERS_DIR}/${name}"
    [[ -f "${peer_dir}/public.key" ]] || { echo "Peer '${name}' not found"; exit 1; }
    local pub; pub=$(cat "${peer_dir}/public.key")
    # Remove from live WireGuard
    wg set "$WG_IF" peer "$pub" remove 2>/dev/null || true
    # Remove from config
    python3 << PYREMOVE
import re
conf = open("${WG_CONF}").read()
# Remove peer block matching the public key
conf = re.sub(r'\n\[Peer\]\n# ${name}\n.*?(?=\n\[Peer\]|\Z)', '', conf, flags=re.DOTALL)
open("${WG_CONF}", 'w').write(conf)
PYREMOVE
    rm -rf "$peer_dir"
    echo "Peer '${name}' removed"
}

list_peers() {
    echo "=== ForgeOS WireGuard Peers ==="
    echo ""
    printf "  %-20s %-16s %-12s %s\n" "NAME" "IP" "HANDSHAKE" "STATUS"
    printf "  %-20s %-16s %-12s %s\n" "────────────────────" "────────────────" "────────────" "──────"
    for peer_dir in "${PEERS_DIR}"/*/; do
        [[ -d "$peer_dir" ]] || continue
        local name; name=$(basename "$peer_dir")
        local ip="—" last_hs="never" status="offline"
        [[ -f "${peer_dir}/meta.json" ]] && \
            ip=$(python3 -c "import json; d=json.load(open('${peer_dir}/meta.json')); print(d.get('ip','—'))" 2>/dev/null || echo "—")
        if [[ -f "${peer_dir}/public.key" ]]; then
            local pub; pub=$(cat "${peer_dir}/public.key")
            local hs; hs=$(wg show "$WG_IF" peers 2>/dev/null | grep -A5 "$pub" | awk '/latest handshake/{print $3,$4,$5}' || echo "never")
            [[ -n "$hs" && "$hs" != "never" ]] && status="online" last_hs="$hs"
        fi
        printf "  %-20s %-16s %-12s %s\n" "$name" "$ip" "$last_hs" "$status"
    done
    echo ""
    echo "Server status:"
    wg show "$WG_IF" 2>/dev/null | grep -E 'interface|listening|peer|endpoint|transfer' | head -20 || true
}

show_qr() {
    local name="${1:?peer name}"
    local conf="${PEERS_DIR}/${name}/${name}.conf"
    [[ -f "$conf" ]] || { echo "Peer '${name}' not found"; exit 1; }
    echo "QR code for '${name}':"
    qrencode -t ansiutf8 < "$conf"
    echo ""
    echo "Config: $conf"
}

case "$CMD" in
add)       add_peer "$@" ;;
remove|rm) remove_peer "$@" ;;
list)      list_peers ;;
qr)        show_qr "$@" ;;
status)    wg show "$WG_IF" 2>/dev/null || echo "WireGuard not running" ;;
restart)   systemctl restart "wg-quick@${WG_IF}"; echo "WireGuard restarted" ;;
stop)      systemctl stop "wg-quick@${WG_IF}"; echo "WireGuard stopped" ;;
start)     systemctl start "wg-quick@${WG_IF}"; echo "WireGuard started" ;;
conf)      cat "${PEERS_DIR}/${1:?peer}/${1}.conf" 2>/dev/null || echo "Not found" ;;
help|*)
    echo "ForgeOS VPN Manager (WireGuard)"
    echo ""
    echo "  add <name> [dns] [allowed_ips]  Add peer + generate QR"
    echo "  remove <name>                   Remove peer"
    echo "  list                            All peers + handshake status"
    echo "  qr <name>                       Show QR code for peer"
    echo "  conf <name>                     Print peer .conf"
    echo "  status                          WireGuard interface status"
    echo "  restart | stop | start"
    echo ""
    echo "  Examples:"
    echo "    forgeos-vpn add phone              # full tunnel"
    echo "    forgeos-vpn add laptop 1.1.1.1 10.10.0.0/24,192.168.1.0/24"
    echo "    forgeos-vpn list"
    echo "    forgeos-vpn qr phone"
    ;;
esac
VPNCLI
    chmod +x /usr/local/bin/forgeos-vpn
    info "forgeos-vpn CLI installed"
}

# ============================================================
# DEFAULT PEERS (from forgeos.conf VPN_DEFAULT_PEERS)
# Comma-separated list: VPN_DEFAULT_PEERS="laptop,phone,tablet"
# ============================================================
create_default_peers() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ -z "${VPN_DEFAULT_PEERS:-}" ]] && return 0

    step "Creating default VPN peers"
    IFS=',' read -ra peers <<< "$VPN_DEFAULT_PEERS"
    for peer in "${peers[@]}"; do
        peer=$(echo "$peer" | xargs)  # trim whitespace
        [[ -z "$peer" ]] && continue
        forgeos-vpn add "$peer" 2>/dev/null \
            && info "  Created peer: $peer" \
            || warn "  Peer creation failed: $peer"
    done
}

# ============================================================
# NETBIRD (optional mesh VPN)
# Enabled by: NETBIRD=yes in forgeos.conf
# ============================================================
install_netbird() {
    # shellcheck source=/dev/null
    source "$FORGENAS_CONFIG"
    [[ "${NETBIRD:-no}" != "yes" ]] && {
        info "Netbird: disabled (set NETBIRD=yes to enable)"
        return 0
    }

    step "Installing Netbird mesh VPN"

    curl -fsSL https://pkgs.netbird.io/install.sh | bash >> "$FORGENAS_LOG" 2>&1 \
        || { warn "Netbird install failed"; return 0; }

    local nb_key="${NETBIRD_SETUP_KEY:-}"
    local nb_mgmt="${NETBIRD_MGMT_URL:-https://api.wiretrustee.com}"

    if [[ -n "$nb_key" ]]; then
        netbird up --setup-key "$nb_key" --management-url "$nb_mgmt" \
            >> "$FORGENAS_LOG" 2>&1 \
            || warn "Netbird setup-key auth failed — run 'netbird up' manually"
        info "Netbird: connected to management server"
    else
        info "Netbird installed — run 'netbird up' to connect"
        info "  Set NETBIRD_SETUP_KEY in /etc/forgeos/forgeos.conf for auto-setup"
    fi

    enable_service netbird 2>/dev/null || true
}

# ============================================================
# FIREWALL RULES FOR VPN
# ============================================================
configure_vpn_firewall() {
    ufw allow "${WG_PORT}/udp" comment "WireGuard" 2>/dev/null || true

    # Allow VPN clients to reach NAS services
    ufw allow from "${WG_NET}" to any port 443  comment "HTTPS from VPN"
    ufw allow from "${WG_NET}" to any port 445  comment "SMB from VPN"
    ufw allow from "${WG_NET}" to any port 5080 comment "ForgeOS API from VPN"

    info "Firewall: VPN rules added (WireGuard subnet: ${WG_NET})"
}

# ============================================================
# MAIN
# ============================================================
install_wireguard
generate_server_keys
configure_wireguard_server
configure_vpn_firewall
install_vpn_cli
create_default_peers
install_netbird

forgenas_set "MODULE_VPN_DONE"   "yes"
forgenas_set "FEATURE_VPN"       "yes"
forgenas_set "WG_LISTEN_PORT"    "$WG_PORT"
forgenas_set "WG_NETWORK"        "$WG_NET"

info "VPN module complete"
info "  WireGuard:   UDP ${WG_PORT}, network ${WG_NET}"
info "  Add peer:    forgeos-vpn add <name>"
info "  List peers:  forgeos-vpn list"
info "  Show QR:     forgeos-vpn qr <name>"
[[ "${NETBIRD:-no}" == "yes" ]] && info "  Netbird:     mesh VPN active"
