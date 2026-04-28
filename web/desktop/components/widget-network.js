// widget-network.js - Network Status widget
class WidgetNetwork extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Network Status';
    this.refreshIntervalMs = 60000; // 60 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/system/network');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
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
        <span class="iface-name">${iface.name}</span>
        <span class="iface-speed">${iface.speed || 'N/A'}</span>
        <span class="iface-status ${iface.up ? 'up' : 'down'}">${iface.up ? 'Up' : 'Down'}</span>
      </div>
    `).join('') || '<div class="empty">No network interfaces found</div>';
  }
}

customElements.define('widget-network', WidgetNetwork);
