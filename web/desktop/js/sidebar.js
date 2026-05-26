// sidebar.js - Collapsible sidebar component
class ForgeSidebar {
  constructor() {
    this.collapsed = false;
    this.init();
  }
  
  init() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    
    const toggle = document.getElementById('sidebar-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => this.toggle());
    }
    
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === '[') this.toggle();
    });
  }
  
  toggle() {
    this.collapsed = !this.collapsed;
    document.body.classList.toggle('sidebar-collapsed', this.collapsed);
    localStorage.setItem('sidebar-collapsed', this.collapsed);
  }
  
  restore() {
    const saved = localStorage.getItem('sidebar-collapsed') === 'true';
    if (saved) {
      this.collapsed = true;
      document.body.classList.add('sidebar-collapsed');
    }
  }
}

// Initialized by forgeOS.js