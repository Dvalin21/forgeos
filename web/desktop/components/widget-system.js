// widget-system.js - System Health widget
class WidgetSystem extends ForgeWidget {
  constructor() {
    super();
    this.title = 'System Health';
    this.refreshIntervalMs = 30000; // 30 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/system/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load system stats:', err);
      this.showError('Unable to load system stats');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    content.innerHTML = `
      <div class="stat-row">
        <span class="label">CPU:</span>
        <span class="value">${data.cpu ? data.cpu.toFixed(1) : 'N/A'}%</span>
      </div>
      <div class="stat-row">
        <span class="label">RAM:</span>
        <span class="value">${data.memory ? data.memory.percent.toFixed(1) : 'N/A'}%</span>
      </div>
      <div class="stat-row">
        <span class="label">Temp:</span>
        <span class="value">${data.temps && data.temps.cpu ? data.temps.cpu.toFixed(1) : 'N/A'}°C</span>
      </div>
      <div class="stat-row">
        <span class="label">Uptime:</span>
        <span class="value">${data.uptime || 'N/A'}</span>
      </div>
    `;
  }
}

customElements.define('widget-system', WidgetSystem);
