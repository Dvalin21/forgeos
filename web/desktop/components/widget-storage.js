// widget-storage.js - Storage Overview widget
class WidgetStorage extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Storage Overview';
    this.refreshIntervalMs = 60000; // 60 seconds
  }

  async loadData() {
    this.showLoading();
    try {
      const data = await this._apiCall('/api/storage/df');
      this.data = data;
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load storage data:', err);
      this.showError('Unable to load storage info');
    }
  }

  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;

    const filesystems = data.filesystems || [];
    const html = filesystems.map(fs => {
      const usedPercent = fs.use_percent || 0;
      const barColor = usedPercent > 90 ? 'var(--color-danger)' :
                       usedPercent > 70 ? 'var(--color-warning)' :
                       'var(--color-success)';

      return `
        <div class="storage-row">
          <span class="fs-device" title="${fs.mountpoint}">${fs.device}</span>
          <span class="fs-size">${fs.used} / ${fs.size} (${usedPercent}%)</span>
          <div class="progress-bar">
            <div class="progress-fill" style="width: ${usedPercent}%; background: ${barColor};"></div>
          </div>
        </div>
      `;
    }).join('');

    content.innerHTML = html || '<div class="empty">No storage filesystems found</div>';
  }
}

customElements.define('widget-storage', WidgetStorage);
