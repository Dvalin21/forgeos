// topbar.js - Top bar component
class ForgeTopBar {
  constructor() {
    this.init();
  }
  
  init() {
    const userBtn = document.getElementById('user-menu-btn');
    const userMenu = document.getElementById('user-menu');
    if (userBtn && userMenu) {
      userBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        userMenu.classList.toggle('hidden');
      });
      
      userMenu.addEventListener('click', (e) => {
        e.stopPropagation();
      });
    }
    
    document.addEventListener('click', () => {
      if (userMenu) userMenu.classList.add('hidden');
    });
    
    const searchInput = document.getElementById('global-search');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
    }
  }
  
  handleSearch(query) {
    console.log('Search:', query);
    window.forgeOS?.dispatch?.('search', { query });
  }
  
  setTitle(title) {
    const titleEl = document.getElementById('context-title');
    if (titleEl) titleEl.textContent = title;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.forgeTopBar = new ForgeTopBar();
});