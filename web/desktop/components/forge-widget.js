// forge-widget.js - Base widget class using Shadow DOM
class ForgeWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.data = null;
    this.refreshInterval = null;
  }
  
  async connectedCallback() {
    this.render();
    await this.loadData();
    this.startAutoRefresh();
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
        }
        h3 { 
          color: var(--text-primary); 
          margin-bottom: var(--space-sm);
          font-size: 16px;
        }
        .content { 
          color: var(--text-secondary); 
        }
      </style>
      <div class="widget">
        <h3>${this.title || 'Widget'}</h3>
        <div class="content">Loading...</div>
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
  
  disconnectedCallback() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }
}

customElements.define('forge-widget', ForgeWidget);
