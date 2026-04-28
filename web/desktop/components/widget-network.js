// widget-network.js - Network Status widget
class WidgetNetwork extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Network Status';
    this.refreshIntervalMs = 60000; // 60 seconds
  }

  async loadData() {
    this.showLoading();
    try {
      const data = await this._apiCall('/api/network');
      this.data = data;
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load network data:', err);
      this.showError('Unable to load network status');
    }
  }

  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;

    const interfaces = data.interfaces || [];
    content.innerHTML = interfaces.map(iface => `
      <div class="iface-row">
        <span class="iface-name">${iface.name || 'N/A'}</span>
        <span class="iface-ip">${iface.ipv4 || 'N/A'}</span>
        <span class="iface-rx">↓ ${this._formatBytes(iface.rx_bytes || 0)}</span>
        <span class="iface-tx">↑ ${this._formatBytes(iface.tx_bytes || 0)}</span>
        <span class="iface-status ${iface.state === 'up' ? 'up' : 'down'}">${iface.state || 'down'}</span>
      </div>
    `).join('') || '<div class="empty">No network interfaces found</div>';
  }

  _formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }
}

customElements.define('widget-network', WidgetNetwork);
