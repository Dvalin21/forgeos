// widget-storage.js - Storage Overview widget
class WidgetStorage extends ForgeWidget {
  constructor() {
    super();
    this.title = 'Storage Overview';
    this.refreshIntervalMs = 60000; // 60 seconds
  }
  
  async loadData() {
    try {
      const res = await fetch('/api/storage/pools');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = await res.json();
      this.update(this.data);
    } catch (err) {
      console.error('Failed to load storage data:', err);
      this.showError('Unable to load storage info');
    }
  }
  
  update(data) {
    const content = this.shadowRoot.querySelector('.content');
    if (!content) return;
    
    const pools = data.pools || [];
    const html = pools.map(pool => `
      <div class="pool-row">
        <span class="pool-name">${pool.name}</span>
        <span class="pool-size">${pool.used}/${pool.total} (${pool.percent}%)</span>
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${pool.percent}%"></div>
        </div>
      </div>
    `).join('');
    
    content.innerHTML = html || '<div class="empty">No storage pools found</div>';
  }
}

customElements.define('widget-storage', WidgetStorage);
