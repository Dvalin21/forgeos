// widget-alerts.js - Recent Alerts widget
class WidgetAlerts extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Recent Alerts';
    this.refreshIntervalMs = 30000; // 30 seconds
  }

  async loadData() {
    this.showLoading();
    try {
      const data = await this._apiCall('/api/notifications?limit=5');
      this.data = data;
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load alerts:', err);
      this.showError('Unable to load alerts');
    }
  }

  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;

    const alerts = data.notifications || [];
    content.innerHTML = alerts.map(alert => `
      <div class="alert-row alert-${alert.severity || 'info'}">
        <span class="alert-icon">${this.getSeverityIcon(alert.severity)}</span>
        <span class="alert-message">${alert.message || 'No message'}</span>
        <span class="alert-time">${this.formatTime(alert.timestamp)}</span>
      </div>
    `).join('') || '<div class="empty">No recent alerts</div>';
  }

  getSeverityIcon(severity) {
    const icons = {
      'critical': '<svg viewBox="0 0 24 24" style="width: 16px; height: 16px; stroke: var(--accent-danger); stroke-width: 2; fill: none;"><polygon points="12 2 2 22 22 22 12 2"/><line x1="12" y1="10" x2="12" y2="16"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>',
      'warning': '<svg viewBox="0 0 24 24" style="width: 16px; height: 16px; stroke: var(--accent-warning); stroke-width: 2; fill: none;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      'info': '<svg viewBox="0 0 24 24" style="width: 16px; height: 16px; stroke: var(--accent-primary); stroke-width: 2; fill: none;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
      'success': '<svg viewBox="0 0 24 24" style="width: 16px; height: 16px; stroke: var(--accent-success); stroke-width: 2.5; fill: none;"><polyline points="20 6 9 17 4 12"/></svg>'
    };
    return icons[severity] || icons.info;
  }

  formatTime(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
}

customElements.define('widget-alerts', WidgetAlerts);
