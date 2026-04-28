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
        .right { display: flex; align-items: center; gap: var(--space-md); margin-left: auto; }
        .logo { font-size: 18px; font-weight: bold; color: var(--accent-primary); cursor: pointer; }
        .nav-item { padding: var(--space-md) var(--space-lg); color: var(--text-secondary); cursor: pointer; border-radius: var(--radius-sm); font-size: 14px; }
        .nav-item:hover { background: var(--bg-elevated); color: var(--text-primary); }
        .nav-item.active { background: var(--accent-primary); color: white; }
        .icon-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; padding: var(--space-md); font-size: 16px; }
        .icon-btn:hover { color: var(--text-primary); }
        .profile-btn { background: none; border: 1px solid var(--border); color: var(--text-primary); cursor: pointer; padding: var(--space-sm) var(--space-md); border-radius: var(--radius-sm); display: flex; align-items: center; gap: var(--space-sm); }
        .profile-btn:hover { background: var(--bg-elevated); }
        .profile-menu { position: absolute; top: 100%; right: 0; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); min-width: 150px; z-index: 1001; }
        .profile-menu-item { display: block; width: 100%; padding: var(--space-sm) var(--space-md); text-align: left; background: none; border: none; color: var(--text-primary); cursor: pointer; }
        .profile-menu-item:hover { background: var(--bg-elevated); }
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
          <button class="icon-btn" title="Notifications">🔔</button>
          <button class="icon-btn" title="App Center">⊞</button>
          <div style="position: relative;">
            <button class="profile-btn" id="profile-btn">
              <span>👤</span>
              <span>admin</span>
            </button>
            <div class="profile-menu hidden" id="profile-menu">
              <button class="profile-menu-item">Profile</button>
              <button class="profile-menu-item">Settings</button>
              <button class="profile-menu-item">Logout</button>
            </div>
          </div>
        </div>
          </div>
        </div>
          </div>
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
    
    // Profile button toggle
    const profileBtn = this.shadowRoot.querySelector('#profile-btn');
    const profileMenu = this.shadowRoot.querySelector('#profile-menu');
    
    if (profileBtn && profileMenu) {
      profileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        profileMenu.classList.toggle('hidden');
      });
      
      // Close menu when clicking outside
      document.addEventListener('click', (e) => {
        if (!profileBtn.contains(e.target) && !profileMenu.contains(e.target)) {
          profileMenu.classList.add('hidden');
        }
      });
    }
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