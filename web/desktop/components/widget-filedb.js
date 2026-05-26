// widget-filedb.js - ForgeFileDB Status widget
class WidgetFiledb extends ForgeWidget {
  constructor() {
    super();
    this.title = 'ForgeFileDB';
    this.icon = '<svg viewBox="0 0 24 24" style="width: 18px; height: 18px; stroke: var(--filedb, #7c4dff); stroke-width: 2; fill: none; vertical-align: middle;"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>';
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
      <style>
        .filedb-link {
          display: block; text-align: center; padding: var(--space-sm);
          background: rgba(124,77,255,0.1); color: var(--filedb, #7c4dff);
          border-radius: var(--radius-sm); text-decoration: none;
          font-size: 12px; font-weight: 600; transition: var(--transition);
        }
        .filedb-link:hover { background: rgba(124,77,255,0.2); }
      </style>
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
          <span style="color: var(--accent-warning); font-size: 12px;"><svg viewBox="0 0 24 24" style="width: 14px; height: 14px; stroke: var(--accent-warning); stroke-width: 2; fill: none; vertical-align: middle; margin-right: 2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Conflicts</span>
          <span style="color: var(--accent-warning); font-size: 16px; font-weight: 600;">${conflicts}</span>
        </div>
        ` : ''}

        <div style="margin-top: var(--space-sm);">
          <a href="/filedb.html" class="filedb-link">Open ForgeFileDB →</a>
        </div>
      </div>
    `;
  }
}

customElements.define('widget-filedb', WidgetFiledb);
