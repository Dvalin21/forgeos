/**
 * ForgeOS Mobile Tab Bar
 * Bottom navigation for mobile/tablet devices
 */

(function() {
  'use strict';
  
  // Only show on mobile/tablet
  if (window.innerWidth > 1024) return;
  
  // Create mobile tab bar
  function createMobileTabBar() {
    const existing = document.getElementById('mobile-tabbar');
    if (existing) return;
    
    const tabs = [
      { id: 'dashboard', icon: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>', label: 'Dashboard' },
      { id: 'storage', icon: '<svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>', label: 'Storage' },
      { id: 'files', icon: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 12h16"/><path d="M12 4v16"/></svg>', label: 'Files' },
      { id: 'settings', icon: '<svg viewBox="0 0 24 24"><path d="M12 2L2 22h20z"/><circle cx="12" cy="14" r="2"/></svg>', label: 'Settings' },
    ];
    
    const bar = document.createElement('div');
    bar.id = 'mobile-tabbar';
    bar.style.cssText = `
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      height: 60px;
      background: rgba(0,0,0,0.95);
      backdrop-filter: blur(20px);
      border-top: 1px solid rgba(255,255,255,0.1);
      display: flex;
      justify-content: space-around;
      align-items: center;
      z-index: 999;
      padding: 0 10px;
    `;
    
    tabs.forEach(tab => {
      const btn = document.createElement('div');
      btn.className = 'mobile-tab';
      btn.dataset.tab = tab.id;
      btn.style.cssText = `
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        padding: 8px 12px;
        color: #888;
        font-size: 10px;
        cursor: pointer;
        transition: color 0.2s;
      `;
      
      btn.innerHTML = `
        <div style="width:20px; height:20px; color:inherit;">${tab.icon}</div>
        <span>${tab.label}</span>
      `;
      
      btn.addEventListener('click', () => {
        // Remove active from all
        document.querySelectorAll('.mobile-tab').forEach(t => {
          t.style.color = '#888';
        });
        // Activate this
        btn.style.color = '#00d4ff';
        
        // Handle tab action
        handleMobileTab(tab.id);
      });
      
      bar.appendChild(btn);
    });
    
    document.body.appendChild(bar);
    
    // Adjust window height
    const windows = document.querySelectorAll('.window');
    windows.forEach(w => {
      w.style.height = 'calc(100vh - 60px)';
    });
  }
  
  // Handle mobile tab click
  function handleMobileTab(tabId) {
    switch(tabId) {
      case 'dashboard':
        toggleWindow('dashboard');
        break;
      case 'storage':
        toggleWindow('storage');
        break;
      case 'files':
        toggleWindow('filestation');
        break;
      case 'settings':
        toggleWindow('settings');
        break;
    }
  }
  
  // Initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createMobileTabBar);
  } else {
    createMobileTabBar();
  }
  
  // Handle resize
  window.addEventListener('resize', function() {
    const bar = document.getElementById('mobile-tabbar');
    if (window.innerWidth > 1024) {
      if (bar) bar.remove();
    } else {
      if (!bar) createMobileTabBar();
    }
  });
  
  // Export for main window-manager
  window.ForgeOSMobile = {
    init: createMobileTabBar,
    handleTab: handleMobileTab,
  };
})();
