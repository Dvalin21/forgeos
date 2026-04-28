// forge-widget.js - Base widget class using Shadow DOM
class ForgeWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.data = null;
    this.refreshInterval = null;
    this._loaded = false;
  }
  
  async connectedCallback() {
    this.render();
    await this.loadData();
    this.startAutoRefresh();
  }

  async loadData() {
    this.showLoading();
    // Override in subclasses - call super.loadData() first or not at all
    console.warn('loadData() should be implemented by subclass');
  }
  
  async _apiCall(endpoint) {
    try {
      const r = await fetch(endpoint, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('forgeos_token') || ''}`
        }
      });
      if (r.status === 401) {
        // Token missing or expired
        this.showError('Session expired. Please refresh the page.');
        return null;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      console.error('API call failed:', e);
      return null;
    }
  }
  
  async loadData() {
    // Override in subclasses
    console.warn('loadData() should be implemented by subclass');
  }
  
  update(data) {
    // Override in subclasses
    console.warn('update() should be implemented by subclass');
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { 
          display: block; 
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-md);
          transition: var(--transition);
        }
        :host(:hover) {
          border-color: var(--accent-primary);
        }
        h3 { 
          color: var(--text-primary); 
          margin-bottom: var(--space-sm);
          font-size: 16px;
          display: flex;
          align-items: center;
          gap: var(--space-sm);
        }
        .content { 
          color: var(--text-secondary); 
        }
        .loading {
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 80px;
          color: var(--text-muted);
          font-size: 13px;
        }
        .error {
          color: var(--accent-danger);
          font-size: 13px;
          padding: var(--space-md);
          text-align: center;
        }
        .error button {
          margin-left: var(--space-sm);
          padding: var(--space-xs) var(--space-sm);
          background: var(--accent-primary);
          color: white;
          border: none;
          border-radius: var(--radius-sm);
          cursor: pointer;
          font-size: 12px;
        }
      </style>
      <div class="widget">
        <h3>${this.title || 'Widget'} ${this.icon || ''}</h3>
        <div class="content"><div class="loading">Loading...</div></div>
      </div>
    `;
  }
  
  startAutoRefresh() {
    if (this.refreshIntervalMs && !this.refreshInterval) {
      this.refreshInterval = setInterval(() => {
        this.loadData();
      }, this.refreshIntervalMs);
    }
  }
  
  showError(message) {
    const content = this.shadowRoot.querySelector('.content');
    if (content) {
      content.innerHTML = `<div class="error">${message} <button onclick="this.getRootNode().host.loadData()">Retry</button></div>`;
    }
  }
  
  showLoading() {
    const content = this.shadowRoot.querySelector('.content');
    if (content) {
      content.innerHTML = '<div class="loading">Loading...</div>';
    }
  }
  
  disconnectedCallback() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }
}

customElements.define('forge-widget', ForgeWidget);
