// widget-alerts.js - Recent Alerts widget
class WidgetAlerts extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Recent Alerts';
    this.refreshIntervalMs = 30000; // 30 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/notifications?limit=5');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
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
      <div class="alert-row alert-${alert.severity}">
        <span class="alert-icon">${this.getSeverityIcon(alert.severity)}</span>
        <span class="alert-message">${alert.message}</span>
        <span class="alert-time">${this.formatTime(alert.timestamp)}</span>
      </div>
    `).join('') || '<div class="empty">No recent alerts</div>';
  }
  
  getSeverityIcon(severity) {
    const icons = { 'critical': '🔥', 'warning': '⚠️', 'info': 'ℹ️', 'success': '✅' };
    return icons[severity] || 'ℹ️';
  }
  
  formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
}

customElements.define('widget-alerts', WidgetAlerts);
