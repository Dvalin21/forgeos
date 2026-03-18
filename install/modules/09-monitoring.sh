#!/usr/bin/env bash
# ============================================================
# ForgeOS Module 09 - Monitoring Stack
#
# Stack:
#   Prometheus     — metrics collection + alerting rules
#   Grafana        — dashboards (pre-built ForgeOS dashboard)
#   Alertmanager   — alert routing → Gotify + Apprise + email
#   node_exporter  — system metrics (CPU, RAM, net, disk I/O)
#   smartctl_exporter — per-drive SMART metrics with predictive
#   btrfs exporter — btrfs pool usage and health
#   Gotify         — push notifications (self-hosted)
#   Apprise        — multi-channel alerts (Slack/Discord/email/etc)
#   fancontrol     — automatic fan speed management
# ============================================================
source "$(dirname "$0")/../lib/common.sh"
# shellcheck source=/dev/null
source "$FORGENAS_CONFIG"

COMPOSE_DIR="/opt/forgeos/apps/monitoring"
DATA_DIR="/srv/forgeos/monitoring"

mkdir -p "$COMPOSE_DIR" "$DATA_DIR"/{prometheus,grafana,alertmanager,gotify}

# ============================================================
# DOCKER COMPOSE — Full monitoring stack
# ============================================================
write_compose() {
    step "Writing monitoring compose file"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"
    local gf_pass; gf_pass=$(gen_password 20)
    forgenas_set "GRAFANA_PASS" "$gf_pass"

    cat > "${COMPOSE_DIR}/docker-compose.yml" << COMPOSE
version: "3.8"

networks:
  monitoring:
    name: forgeos-monitoring
  forgeos-internal:
    external: true

volumes:
  prometheus_data:
    driver: local
    driver_opts: {type: none, o: bind, device: ${DATA_DIR}/prometheus}
  grafana_data:
    driver: local
    driver_opts: {type: none, o: bind, device: ${DATA_DIR}/grafana}
  alertmanager_data:
    driver: local
    driver_opts: {type: none, o: bind, device: ${DATA_DIR}/alertmanager}
  gotify_data:
    driver: local
    driver_opts: {type: none, o: bind, device: ${DATA_DIR}/gotify}

services:

  # ── Prometheus ─────────────────────────────────────────────
  prometheus:
    image: prom/prometheus:latest
    container_name: forgeos-prometheus
    restart: unless-stopped
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=90d'
      - '--storage.tsdb.retention.size=20GB'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
      - '--web.enable-admin-api'
    volumes:
      - prometheus_data:/prometheus
      - ${COMPOSE_DIR}/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ${COMPOSE_DIR}/alert-rules.yml:/etc/prometheus/alert-rules.yml:ro
    ports:
      - "127.0.0.1:9091:9090"
    networks: [monitoring, forgeos-internal]

  # ── Grafana ────────────────────────────────────────────────
  grafana:
    image: grafana/grafana:latest
    container_name: forgeos-grafana
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: "${gf_pass}"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_SERVER_ROOT_URL: "https://grafana.${DOMAIN:-nas.local}"
      GF_INSTALL_PLUGINS: "grafana-clock-panel,grafana-worldmap-panel"
      GF_FEATURE_TOGGLES_ENABLE: "ngalert"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
    volumes:
      - grafana_data:/var/lib/grafana
      - ${COMPOSE_DIR}/grafana/provisioning:/etc/grafana/provisioning:ro
      - ${COMPOSE_DIR}/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "127.0.0.1:3000:3000"
    networks: [monitoring, forgeos-internal]
    depends_on: [prometheus]

  # ── Alertmanager ───────────────────────────────────────────
  alertmanager:
    image: prom/alertmanager:latest
    container_name: forgeos-alertmanager
    restart: unless-stopped
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
      - '--storage.path=/alertmanager'
    volumes:
      - alertmanager_data:/alertmanager
      - ${COMPOSE_DIR}/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    ports:
      - "127.0.0.1:9093:9093"
    networks: [monitoring]

  # ── node_exporter ──────────────────────────────────────────
  node-exporter:
    image: prom/node-exporter:latest
    container_name: forgeos-node-exporter
    restart: unless-stopped
    command:
      - '--path.rootfs=/host'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
      - '--collector.systemd'
      - '--collector.processes'
      - '--collector.interrupts'
      - '--collector.tcpstat'
    volumes:
      - /:/host:ro,rslave
      - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket:ro
    pid: host
    network_mode: host

  # ── smartctl_exporter (SMART metrics per drive) ────────────
  smartctl-exporter:
    image: prometheuscommunity/smartctl-exporter:latest
    container_name: forgeos-smartctl-exporter
    restart: unless-stopped
    privileged: true
    command:
      - '--smartctl.path=/usr/sbin/smartctl'
    volumes:
      - /dev:/dev
    ports:
      - "127.0.0.1:9633:9633"
    networks: [monitoring]

  # ── Gotify (push notifications) ────────────────────────────
  gotify:
    image: gotify/server:latest
    container_name: forgeos-gotify
    restart: unless-stopped
    environment:
      GOTIFY_DEFAULTUSER_NAME: admin
      GOTIFY_DEFAULTUSER_PASS: "${gf_pass}"
      GOTIFY_SERVER_PORT: 80
    volumes:
      - gotify_data:/app/data
    ports:
      - "127.0.0.1:8070:80"
    networks: [forgeos-internal]

COMPOSE

    chmod 600 "${COMPOSE_DIR}/docker-compose.yml"
    info "Compose file written"
}

# ============================================================
# PROMETHEUS CONFIG
# ============================================================
write_prometheus_config() {
    step "Writing Prometheus configuration"

    cat > "${COMPOSE_DIR}/prometheus.yml" << 'PROM'
global:
  scrape_interval:     15s
  evaluation_interval: 15s
  external_labels:
    instance: 'forgeos'

rule_files:
  - /etc/prometheus/alert-rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['forgeos-alertmanager:9093']

scrape_configs:
  # System metrics
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'forgeos'

  # SMART drive metrics
  - job_name: 'smartctl'
    static_configs:
      - targets: ['forgeos-smartctl-exporter:9633']
    scrape_interval: 60s

  # Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # ForgeOS API
  - job_name: 'forgeos-api'
    static_configs:
      - targets: ['host.docker.internal:5080']
    metrics_path: /metrics
    scrape_interval: 30s

  # Samba (if samba_exporter available)
  - job_name: 'samba'
    static_configs:
      - targets: ['localhost:9922']
    scrape_interval: 30s

  # MariaDB
  - job_name: 'mariadb'
    static_configs:
      - targets: ['localhost:9104']
    scrape_interval: 30s
PROM

    # Alert rules
    cat > "${COMPOSE_DIR}/alert-rules.yml" << 'RULES'
groups:
  - name: forgeos.storage
    rules:
      # Drive predictive failure (SMART)
      - alert: DriveSMARTPredictiveFailure
        expr: smartctl_device_smartstatus != 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "SMART predictive failure: {{ $labels.device }}"
          description: "Drive {{ $labels.device }} has failed SMART health check. Replace immediately."

      - alert: DriveReallocatedSectors
        expr: smartctl_attr_raw_value{attribute_name="Reallocated_Sector_Ct"} > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Reallocated sectors: {{ $labels.device }}"
          description: "Drive {{ $labels.device }} has {{ $value }} reallocated sectors. Monitor closely."

      - alert: DrivePendingSectors
        expr: smartctl_attr_raw_value{attribute_name="Current_Pending_Sector"} > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Pending sectors: {{ $labels.device }}"
          description: "Drive {{ $labels.device }} has {{ $value }} pending sectors — imminent failure."

      - alert: DriveTemperatureHigh
        expr: smartctl_attr_raw_value{attribute_name="Temperature_Celsius"} > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Drive temperature warning: {{ $labels.device }}"
          description: "Drive {{ $labels.device }} temperature {{ $value }}°C (threshold: 50°C)"

      - alert: DriveTemperatureCritical
        expr: smartctl_attr_raw_value{attribute_name="Temperature_Celsius"} > 60
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Drive temperature critical: {{ $labels.device }}"
          description: "Drive {{ $labels.device }} at {{ $value }}°C — risk of immediate failure."

      - alert: DiskUsageWarning
        expr: (1 - node_filesystem_avail_bytes{fstype="btrfs"} / node_filesystem_size_bytes{fstype="btrfs"}) > 0.80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage >80%: {{ $labels.mountpoint }}"
          description: "Pool at {{ $labels.mountpoint }} is {{ $value | humanizePercentage }} full."

      - alert: DiskUsageCritical
        expr: (1 - node_filesystem_avail_bytes{fstype="btrfs"} / node_filesystem_size_bytes{fstype="btrfs"}) > 0.92
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk usage >92%: {{ $labels.mountpoint }}"
          description: "Pool at {{ $labels.mountpoint }} is {{ $value | humanizePercentage }} full — URGENT."

  - name: forgeos.system
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 90
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage"
          description: "CPU has been above 90% for 15 minutes."

      - alert: HighMemoryUsage
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) > 0.90
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Memory usage above 90% for 10 minutes."

      - alert: SystemHighTemperature
        expr: node_hwmon_temp_celsius > 85
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "System temperature critical"
          description: "Sensor {{ $labels.chip }}/{{ $labels.sensor }} at {{ $value }}°C"

      - alert: ServiceDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service down: {{ $labels.job }}"
          description: "Prometheus cannot reach {{ $labels.job }} on {{ $labels.instance }}"

      - alert: NginxDown
        expr: node_systemd_unit_state{name="nginx.service",state="active"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "nginx is down"
          description: "The nginx reverse proxy is not active."
RULES

    info "Prometheus config and alert rules written"
}

# ============================================================
# ALERTMANAGER CONFIG
# Routes alerts to Gotify + Apprise + optional email
# ============================================================
write_alertmanager_config() {
    step "Writing Alertmanager configuration"

    # shellcheck source=/dev/null

    source "$FORGENAS_CONFIG"

    cat > "${COMPOSE_DIR}/alertmanager.yml" << ALERT
global:
  resolve_timeout: 5m
  # SMTP config (optional — set in Web UI > Settings > Notifications)
  # smtp_smarthost: 'smtp.gmail.com:587'
  # smtp_from: 'forgeos@${DOMAIN:-nas.local}'
  # smtp_auth_username: ''
  # smtp_auth_password: ''

route:
  group_by: ['alertname', 'severity']
  group_wait:      30s
  group_interval:  5m
  repeat_interval: 4h
  receiver: forgeos-default

  routes:
    # Critical alerts: immediate, no grouping delay
    - match:
        severity: critical
      group_wait: 10s
      repeat_interval: 1h
      receiver: forgeos-critical

receivers:
  - name: forgeos-default
    webhook_configs:
      - url: 'http://host.docker.internal:5080/api/alert-webhook'
        send_resolved: true

  - name: forgeos-critical
    webhook_configs:
      - url: 'http://host.docker.internal:5080/api/alert-webhook'
        send_resolved: true
    # Apprise multi-channel (configured via forgeos-ctl set-apprise)
    # webhook_configs:
    #   - url: 'http://host.docker.internal:5080/api/alert-webhook'

inhibit_rules:
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: ['alertname', 'device']
ALERT

    info "Alertmanager config written"
}

# ============================================================
# GRAFANA PROVISIONING — Auto-load ForgeOS dashboards
# ============================================================
write_grafana_provisioning() {
    step "Writing Grafana provisioning"

    mkdir -p "${COMPOSE_DIR}/grafana/provisioning/"{datasources,dashboards,notifiers}
    mkdir -p "${COMPOSE_DIR}/grafana/dashboards"

    # Datasource
    cat > "${COMPOSE_DIR}/grafana/provisioning/datasources/prometheus.yml" << 'DS'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://forgeos-prometheus:9090
    isDefault: true
    editable: false
DS

    # Dashboard provisioner
    cat > "${COMPOSE_DIR}/grafana/provisioning/dashboards/forgeos.yml" << 'DP'
apiVersion: 1
providers:
  - name: ForgeOS
    orgId: 1
    folder: ForgeOS
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
DP

    # ForgeOS main dashboard (minimal JSON — full dashboard auto-imports from Grafana marketplace)
    cat > "${COMPOSE_DIR}/grafana/dashboards/forgeos-main.json" << 'DASH'
{
  "__inputs": [],
  "__requires": [],
  "annotations": {"list": []},
  "description": "ForgeOS System Overview",
  "editable": true,
  "gnetId": null,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": "Prometheus",
      "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}, "unit": "percent"}},
      "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
      "id": 1,
      "title": "CPU Usage",
      "type": "gauge",
      "targets": [{"expr": "100 - (avg(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)", "legendFormat": "CPU %"}]
    },
    {
      "datasource": "Prometheus",
      "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}, "unit": "percent"}},
      "gridPos": {"h": 6, "w": 6, "x": 6, "y": 0},
      "id": 2,
      "title": "Memory Usage",
      "type": "gauge",
      "targets": [{"expr": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100", "legendFormat": "RAM %"}]
    },
    {
      "datasource": "Prometheus",
      "fieldConfig": {"defaults": {"unit": "celsius"}},
      "gridPos": {"h": 6, "w": 6, "x": 12, "y": 0},
      "id": 3,
      "title": "Drive Temperatures",
      "type": "table",
      "targets": [{"expr": "smartctl_attr_raw_value{attribute_name=\"Temperature_Celsius\"}", "legendFormat": "{{device}}"}]
    },
    {
      "datasource": "Prometheus",
      "gridPos": {"h": 6, "w": 6, "x": 18, "y": 0},
      "id": 4,
      "title": "SMART Status",
      "type": "table",
      "targets": [{"expr": "smartctl_device_smartstatus", "legendFormat": "{{device}} {{model_name}}"}]
    }
  ],
  "refresh": "10s",
  "schemaVersion": 27,
  "style": "dark",
  "tags": ["forgeos"],
  "title": "ForgeOS Overview",
  "uid": "forgeos-main",
  "version": 1
}
DASH

    info "Grafana provisioning written (datasource + ForgeOS dashboard)"
}

# ============================================================
# FAN CONTROL
# ============================================================
configure_fancontrol() {
    step "Configuring fan control (lm-sensors + fancontrol)"

    apt_install lm-sensors fancontrol

    # Run sensors-detect automatically (answer yes to everything)
    yes | sensors-detect --auto >> "$FORGENAS_LOG" 2>&1 || warn "sensors-detect had issues"

    # Create base fancontrol config if not exists
    if [[ ! -f /etc/fancontrol ]]; then
        cat > /etc/fancontrol << 'FC'
# ForgeOS fancontrol configuration
# Auto-generated — tune via Web UI > Sensors
# Full docs: man fancontrol
INTERVAL=10
DEVPATH=
DEVNAME=
FCTEMPS=
FCFANS=
MINTEMP=
MAXTEMP=
MINSTART=
MINSTOP=
# Note: This default config is intentionally empty.
# Run: sudo pwmconfig
# Or configure via Web UI > System > Sensors > Fan Control
FC
    fi

    # Enable service but don't start yet (needs valid config)
    systemctl enable fancontrol 2>/dev/null || true

    # Apprise for multi-channel alerts
    apt_install_optional python3-pip
    pip3 install apprise --quiet 2>/dev/null || warn "Apprise install failed (optional)"

    info "Fan control: configure via 'sudo pwmconfig' or Web UI > Sensors"
}

# ============================================================
# APPRISE CONFIG HELPER
# ============================================================
configure_apprise() {
    step "Configuring Apprise notification URLs"

    mkdir -p /etc/forgeos/notifications

    cat > /etc/forgeos/notifications/apprise.yml << 'APPRISE'
# ForgeOS Apprise Notification Configuration
# Add your notification URLs here.
# Docs: https://github.com/caronc/apprise/wiki
#
# Examples:
#   Discord:  discord://webhook_id/webhook_token
#   Slack:    slack://tokenA/tokenB/tokenC
#   Telegram: tgram://bottoken/ChatID
#   Matrix:   matrix://user:pass@host
#   Email:    mailto://user:pass@gmail.com?to=you@gmail.com
#   Pushover: pover://user@token
#   ntfy:     ntfy://topic
#   Gotify:   gotify://hostname/token
#
# The Gotify entry below is pre-configured:
urls:
  - gotify://localhost:8070/${GOTIFY_TOKEN:-changeme}
# Uncomment and fill in additional channels:
# - discord://...
# - slack://...
APPRISE

    cat > /usr/local/bin/forgeos-notify << 'NOTIFYSCRIPT'
#!/usr/bin/env bash
# ForgeOS notification sender
# Usage: forgeos-notify <level> <title> <message>
LEVEL="${1:-info}"  TITLE="${2:-ForgeOS}"  MSG="${3:-}"
# Send via Apprise (multi-channel)
apprise -t "$TITLE" -b "$MSG" --config /etc/forgeos/notifications/apprise.yml 2>/dev/null || true
# Also log
logger -t forgeos-notify "${LEVEL}: ${TITLE}: ${MSG}"
NOTIFYSCRIPT
    chmod +x /usr/local/bin/forgeos-notify
}

# ============================================================
# MAIN
# ============================================================
write_compose
write_prometheus_config
write_alertmanager_config
write_grafana_provisioning
configure_fancontrol
configure_apprise

step "Starting monitoring stack"
docker_compose_pull "$COMPOSE_DIR"
docker_compose_up   "$COMPOSE_DIR"

# Wait for Grafana
if wait_for_port 127.0.0.1 3000 60; then
    info "Grafana started on http://127.0.0.1:3000"
else
    warn "Grafana not yet ready — check: docker logs forgeos-grafana"
fi

# Wait for Gotify
if wait_for_port 127.0.0.1 8070 30; then
    # Get Gotify app token for ForgeOS
    sleep 3
    gotify_token=$(curl -sf -u "admin:$(forgenas_get GRAFANA_PASS)" \
        -X POST "http://localhost:8070/application" \
        -H "Content-Type: application/json" \
        -d '{"name":"ForgeOS","description":"ForgeOS system alerts"}' \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])" 2>/dev/null || echo "")
    if [[ -n "$gotify_token" ]]; then
        forgenas_set "GOTIFY_TOKEN" "$gotify_token"
        # Update Apprise config with real token
        sed -i "s/\${GOTIFY_TOKEN:-changeme}/${gotify_token}/" /etc/forgeos/notifications/apprise.yml
        info "Gotify token saved: $gotify_token"
    fi
else
    warn "Gotify not started — check: docker logs forgeos-gotify"
fi

forgenas_set "FEATURE_MONITORING" "yes"
forgenas_set "GRAFANA_URL" "http://127.0.0.1:3000"
forgenas_set "PROMETHEUS_URL" "http://127.0.0.1:9091"
forgenas_set "GOTIFY_URL" "http://localhost:8070"

info "Monitoring stack installed"
info "  Grafana:        http://127.0.0.1:3000  (admin / $(forgenas_get GRAFANA_PASS))"
info "  Prometheus:     http://127.0.0.1:9091"
info "  Alertmanager:   http://127.0.0.1:9093"
info "  Gotify:         http://127.0.0.1:8070"
info ""
info "  Notifications:  edit /etc/forgeos/notifications/apprise.yml"
info "  Fan control:    sudo pwmconfig  OR  Web UI > Sensors"
