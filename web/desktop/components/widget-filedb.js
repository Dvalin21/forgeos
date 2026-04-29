// widget-filedb.js - ForgeFileDB Status widget
class WidgetFiledb extends ForgeWidget {
  constructor() {
    super();
    this.title = 'ForgeFileDB';
    this.icon = '🗄️';
    this.refreshIntervalMs = 60000; // 60 seconds
  }

  async loadData() {
    this.showLoading();
    try {
      const data = await this._apiCall('/api/filedb/status');
      if (data) {
        this.data = data;
        this.update(this.data);
      } else {
        this.showError('Unable to load ForgeFileDB status');
      }
    } catch (err) {
      console.error('Failed to load ForgeFileDB data:', err);
      this.showError('ForgeFileDB unavailable');
    }
  }

  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;

    const isRunning = data.daemon_running !== false;
    const clients = data.connected_clients || 0;
    const databases = data.open_databases || 0;
    const snapshots = data.snapshots_today || 0;
    const conflicts = data.total_conflicts || 0;

    content.innerHTML = `
      <div style="display: grid; gap: var(--space-sm);">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Status</span>
          <span style="color: ${isRunning ? 'var(--accent-success)' : 'var(--accent-danger)'}; font-size: 12px; font-weight: 600;">
            ${isRunning ? '● Running' : '○ Stopped'}
          </span>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-muted); font-size: 12px;">Connected Clients</span>
          <span style="color: var(--text-primary); font-size: 16px; font-weight: 600;">${clients}</span>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-muted); font-size: 12px;">Open Databases</span>
          <span style="color: var(--text-primary); font-size: 16px; font-weight: 600;">${databases}</span>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-muted); font-size: 12px;">Snapshots Today</span>
          <span style="color: var(--text-primary); font-size: 16px; font-weight: 600;">${snapshots}</span>
        </div>

        ${conflicts > 0 ? `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--accent-warning); font-size: 12px;">⚠ Conflicts</span>
          <span style="color: var(--accent-warning); font-size: 16px; font-weight: 600;">${conflicts}</span>
        </div>
        ` : ''}

        <div style="margin-top: var(--space-sm);">
          <a href="/filedb.html" style="display: block; text-align: center; padding: var(--space-sm); background: rgba(124,77,255,0.1); color: var(--filedb, #7c4dff); border-radius: var(--radius-sm); text-decoration: none; font-size: 12px; font-weight: 600; transition: var(--transition);" onmouseover="this.style.background='rgba(124,77,255,0.2)'" onmouseout="this.style.background='rgba(124,77,255,0.1)'">
            Open ForgeFileDB →
          </a>
        </div>
      </div>
    `;
  }
}

customElements.define('widget-filedb', WidgetFiledb);
