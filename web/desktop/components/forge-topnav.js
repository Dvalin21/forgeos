// forge-topnav.js - Top navigation bar (modernized)
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
          background: linear-gradient(135deg, var(--bg-surface), var(--bg-elevated));
          border-bottom: 1px solid var(--border);
          z-index: 1000;
          backdrop-filter: blur(10px);
        }
        nav {
          display: flex;
          align-items: center;
          height: 100%;
          padding: 0 var(--space-lg);
          max-width: 1400px;
          margin: 0 auto;
        }
        .left { display: flex; align-items: center; gap: var(--space-md); }
        .right { display: flex; align-items: center; gap: var(--space-md); margin-left: auto; }
        
        .logo { 
          font-size: 20px; 
          font-weight: 700; 
          background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          cursor: pointer; 
          letter-spacing: 1px;
        }
        
        .nav-item { 
          padding: var(--space-md) var(--space-lg); 
          color: var(--text-secondary); 
          cursor: pointer; 
          border-radius: var(--radius-md); 
          font-size: 14px; 
          font-weight: 500;
          transition: var(--transition);
          border: none;
          background: transparent;
        }
        .nav-item:hover { 
          background: rgba(0,180,216,0.1); 
          color: var(--text-primary); 
        }
        .nav-item.active { 
          background: var(--accent-primary); 
          color: white; 
          box-shadow: var(--glow-sm);
        }
        
.icon-btn { 
  background: linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)); 
  border: 1px solid rgba(255,255,255,0.15); 
  color: var(--text-secondary); 
  cursor: pointer; 
  padding: var(--space-md); 
  border-radius: var(--radius-lg); 
  font-size: 18px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  position: relative;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.icon-btn:hover { 
  background: linear-gradient(135deg, rgba(0,180,216,0.2), rgba(0,180,216,0.1)); 
  border-color: var(--accent-primary);
  color: var(--accent-primary);
  box-shadow: 0 4px 16px rgba(0,180,216,0.3), var(--glow-sm);
  transform: translateY(-1px);
}
.icon-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(0,180,216,0.2);
}
.icon-btn .badge {
  position: absolute;
  top: -4px;
  right: -4px;
  background: linear-gradient(135deg, #ff4757, #ff6b81);
  color: white;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 10px;
  min-width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 4px rgba(255,71,87,0.4);
  animation: pulse-badge 2s infinite;
}
@keyframes pulse-badge {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
}
        
.profile-btn { 
  background: linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)); 
  border: 1px solid rgba(255,255,255,0.15); 
  color: var(--text-primary); 
  cursor: pointer; 
  padding: var(--space-md) var(--space-lg); 
  border-radius: var(--radius-lg); 
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: var(--space-md);
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.profile-btn:hover { 
  background: linear-gradient(135deg, rgba(0,180,216,0.2), rgba(0,180,216,0.1)); 
  border-color: var(--accent-primary);
  box-shadow: 0 4px 16px rgba(0,180,216,0.3), var(--glow-sm);
  transform: translateY(-1px);
}
.profile-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(0,180,216,0.2);
}
.profile-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  box-shadow: 0 2px 8px rgba(0,180,216,0.3);
}
        
        .profile-menu { 
          position: absolute; 
          top: 100%; 
          right: 0; 
          background: linear-gradient(135deg, var(--bg-surface), var(--bg-elevated)); 
          border: 1px solid rgba(255,255,255,0.15); 
          border-radius: var(--radius-lg); 
          min-width: 200px; 
          z-index: 1001;
          box-shadow: 0 8px 32px rgba(0,0,0,0.3), var(--glow-sm);
          overflow: hidden;
          margin-top: var(--space-sm);
          animation: slide-down 0.2s ease-out;
        }
        @keyframes slide-down {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .profile-menu-item { 
          display: flex; 
          align-items: center;
          gap: var(--space-md);
          width: 100%; 
          padding: var(--space-md) var(--space-lg); 
          text-align: left; 
          background: none; 
          border: none; 
          color: var(--text-primary); 
          cursor: pointer; 
          font-size: 14px;
          transition: all 0.2s ease;
          border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .profile-menu-item:last-child {
          border-bottom: none;
        }
        .profile-menu-item:hover { 
          background: linear-gradient(135deg, rgba(0,180,216,0.15), rgba(0,180,216,0.05)); 
          color: var(--accent-primary);
          padding-left: calc(var(--space-lg) + 4px);
        }
        .menu-icon {
          font-size: 16px;
          width: 20px;
          text-align: center;
        }
      </style>
      <nav>
        <div class="left">
          <span class="logo" data-page="dashboard">ForgeOS</span>
          <button class="nav-item active" data-page="dashboard">
            <svg class="svg-icon svg-icon-sm" viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
              <rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
            Dashboard
          </button>
          <button class="nav-item" data-page="filestation">
            <svg class="svg-icon svg-icon-sm" viewBox="0 0 24 24">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            File Station
          </button>
          <button class="nav-item" data-page="docker">
            <svg class="svg-icon svg-icon-sm" viewBox="0 0 24 24">
              <rect x="2" y="3" width="20" height="14" rx="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            Docker
          </button>
          ${this.mailInstalled ? '<button class="nav-item" data-page="mail"><svg class="svg-icon svg-icon-sm" viewBox="0 0 24 24"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> Mail</button>' : ''}
        </div>
        <div class="right">
          <button class="icon-btn-svg" title="Notifications">
            <svg class="svg-icon" viewBox="0 0 24 24">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
            <span class="badge">3</span>
          </button>
          <button class="icon-btn-svg" title="App Center">
            <svg class="svg-icon" viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
              <rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </button>
          <div style="position: relative;">
            <button class="profile-btn" id="profile-btn">
              <div class="profile-avatar">
                <svg class="svg-icon svg-icon-lg" viewBox="0 0 24 24" style="color: white;">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
              <span>admin</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" style="opacity: 0.6;">
                <path d="M6 8L1 3h10z"/>
              </svg>
            </button>
            <div class="profile-menu hidden" id="profile-menu">
              <button class="profile-menu-item" data-action="profile">Profile</button>
              <button class="profile-menu-item" data-action="settings">Settings</button>
              <button class="profile-menu-item" data-action="logout">Logout</button>
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
      
      // Profile menu item clicks
      profileMenu.querySelectorAll('.profile-menu-item').forEach(item => {
        item.addEventListener('click', () => {
          const action = item.dataset.action;
          if (action === 'settings') {
            this.navigateTo('settings');
          } else if (action === 'logout') {
            console.log('Logout clicked');
            // TODO: Implement logout
          } else if (action === 'profile') {
            console.log('Profile clicked');
            // TODO: Implement profile view
          }
          profileMenu.classList.add('hidden');
        });
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
