// forge-topnav.js - Top navigation bar
class ForgeTopnav extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.mailInstalled = false; // TODO: Check from API
  }
  
  connectedCallback() {
    this.render();
    this.setupEventListeners();
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          height: var(--topnav-height);
          background: var(--bg-surface);
          border-bottom: 1px solid var(--border);
          z-index: 1000;
        }
        nav {
          display: flex;
          align-items: center;
          height: 100%;
          padding: 0 var(--space-md);
        }
        .left { display: flex; align-items: center; gap: var(--space-md); }
        .right { display: flex; align-items: center; gap: var(--space-sm); margin-left: auto; }
        .logo { font-size: 18px; font-weight: bold; color: var(--accent-primary); cursor: pointer; }
        .nav-item { padding: var(--space-sm) var(--space-md); color: var(--text-secondary); cursor: pointer; border-radius: var(--radius-sm); }
        .nav-item:hover { background: var(--bg-elevated); color: var(--text-primary); }
        .nav-item.active { background: var(--accent-primary); color: white; }
        .icon-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; padding: var(--space-sm); }
        .icon-btn:hover { color: var(--text-primary); }
      </style>
      <nav>
        <div class="left">
          <span class="logo" data-page="dashboard">ForgeOS</span>
          <span class="nav-item active" data-page="dashboard">Dashboard</span>
          <span class="nav-item" data-page="filestation">File Station</span>
          <span class="nav-item" data-page="docker">Docker</span>
          ${this.mailInstalled ? '<span class="nav-item" data-page="mail">Mail</span>' : ''}
        </div>
        <div class="right">
          <button class="icon-btn" title="Search">🔍</button>
          <button class="icon-btn" title="Notifications">🔔</button>
          <button class="icon-btn" title="App Center">⊞</button>
          <button class="icon-btn" title="Settings">⚙️</button>
          <button class="icon-btn" title="User Menu">👤</button>
        </div>
      </nav>
    `;
  }
    
  setupEventListeners() {
    // Navigation items
    this.shadowRoot.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', () => {
        const page = item.dataset.page;
        this.navigateTo(page);
      });
    });
    
    // Logo click (go to dashboard)
    this.shadowRoot.querySelector('.logo').addEventListener('click', () => {
      this.navigateTo('dashboard');
    });
  }
  
  navigateTo(page) {
    // Update active state
    this.shadowRoot.querySelectorAll('.nav-item').forEach(item => {
      item.classList.remove('active');
    });
    const activeItem = this.shadowRoot.querySelector(`[data-page="${page}"]`);
    if (activeItem) activeItem.classList.add('active');
    
    // Navigate to page
    window.location.href = `/desktop/${page}.html`;
  }
}

customElements.define('forge-topnav', ForgeTopnav);