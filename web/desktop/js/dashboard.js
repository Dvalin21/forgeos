// dashboard.js - Widget grid dashboard
class ForgeDashboard {
  constructor() {
    this.widgets = [];
    this.init();
  }
  
  init() {
    this.renderWidgets();
    this.loadWidgetData();
  }
  
  renderWidgets() {
    const widgets = [
      { type: 'system', title: 'System', size: '1x1' },
      { type: 'storage', title: 'Storage', size: '2x1' },
      { type: 'docker', title: 'Docker', size: '1x1' },
      { type: 'alerts', title: 'Alerts', size: '1x1' }
    ];
    
    // Create dashboard div if it doesn't exist
    let dashboard = document.getElementById('dashboard');
    if (!dashboard) {
      dashboard = document.createElement('div');
      dashboard.id = 'dashboard';
      const desktop = document.getElementById('desktop');
      if (desktop) {
        desktop.appendChild(dashboard);
      }
    }
    
    dashboard.innerHTML = widgets.map(w => `
      <div class="widget widget-${w.size}" data-type="${w.type}">
        <div class="widget-header">
          <span class="widget-title">${w.title}</span>
        </div>
        <div class="widget-content" id="widget-${w.type}">
          <div class="loading">Loading...</div>
        </div>
      </div>
    `).join('');
  }
  
  async loadWidgetData() {
    // System stats widget
    try {
      const stats = await fetch('/api/system/stats').then(r => r.json());
      document.getElementById('widget-system').innerHTML = `
        <div class="stat-row"><span>CPU</span><span>${stats.cpu_pct}%</span></div>
        <div class="stat-row"><span>Memory</span><span>${stats.memory}%</span></div>
      `;
    } catch(e) {
      document.getElementById('widget-system').innerHTML = '<div class="error">Offline</div>';
    }
  }
}

document.addEventListener('DOMContentLoaded', () => new ForgeDashboard());