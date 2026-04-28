// widget-system.js - System Health widget
class WidgetSystem extends ForgeWidget {
  constructor() {
    super();
    this.title = 'System Health';
    this.icon = '💻';
    this.refreshIntervalMs = 30000; // 30 seconds
  }
  
  async loadData() {
    this.showLoading();
    const data = await this._apiCall('/api/system/stats');
    if (data) {
      this.data = data;
      this.update(this.data);
    } else {
      this.showError('Unable to load system stats');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    const cpu = data.cpu_pct != null ? data.cpu_pct.toFixed(1) : 'N/A';
    const memPct = data.memory && data.memory.percent != null ? data.memory.percent.toFixed(1) : 'N/A';
    const temp = data.temps && data.temps.cpu != null ? data.temps.cpu.toFixed(1) : 'N/A';
    const uptime = data.uptime || 'N/A';
    
    content.innerHTML = `
      <div style="display: grid; gap: var(--space-sm);">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">CPU Usage</span>
          <span style="color: var(--accent-primary); font-size: 18px; font-weight: 600;">${cpu}%</span>
        </div>
        <div style="background: rgba(0,180,216,0.1); height: 4px; border-radius: 2px; overflow: hidden;">
          <div style="background: var(--accent-primary); height: 100%; width: ${cpu}%; transition: width 0.3s ease;"></div>
        </div>
        
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: var(--space-sm);">
          <span style="color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Memory</span>
          <span style="color: var(--accent-success); font-size: 18px; font-weight: 600;">${memPct}%</span>
        </div>
        <div style="background: rgba(6,214,160,0.1); height: 4px; border-radius: 2px; overflow: hidden;">
          <div style="background: var(--accent-success); height: 100%; width: ${memPct}%; transition: width 0.3s ease;"></div>
        </div>
        
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: var(--space-sm);">
          <span style="color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">CPU Temp</span>
          <span style="color: ${temp > 70 ? 'var(--accent-danger)' : temp > 50 ? 'var(--accent-warning)' : 'var(--accent-primary)'}; font-size: 18px; font-weight: 600;">${temp}°C</span>
        </div>
        
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: var(--space-md);">
          <span style="color: var(--text-muted); font-size: 12px;">Uptime</span>
          <span style="color: var(--text-secondary); font-size: 13px;">${uptime}</span>
        </div>
      </div>
    `;
  }
}

customElements.define('widget-system', WidgetSystem);
