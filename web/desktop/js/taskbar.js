// taskbar.js - Bottom taskbar with 4 pins
class ForgeTaskbar {
  constructor() {
    this.pins = [
      { id: 'dashboard', icon: '◈', label: 'Dashboard' },
      { id: 'apps', icon: '◉', label: 'Apps' },
      { id: 'storage', icon: '⬡', label: 'Storage' },
      { id: 'settings', icon: '⚙', label: 'Settings' }
    ];
    this.activePanel = null;
    this.init();
  }
  
  init() {
    const pinsContainer = document.getElementById('tb-pins');
    if (!pinsContainer) return;
    
    pinsContainer.innerHTML = '';
    
    this.pins.forEach(pin => {
      const btn = document.createElement('div');
      btn.className = 'tb-pin';
      btn.dataset.panel = pin.id;
      btn.innerHTML = `<span class="p-ico">${pin.icon}</span><span class="p-lbl">${pin.label}</span>`;
      btn.addEventListener('click', () => this.openPanel(pin.id));
      pinsContainer.appendChild(btn);
    });
    
    this.updateActive('dashboard');
  }
  
  openPanel(id) {
    this.updateActive(id);
    window.forgeOS?.openWindow?.(id);
  }
  
  updateActive(id) {
    this.activePanel = id;
    document.querySelectorAll('.tb-pin').forEach(pin => {
      pin.classList.toggle('open', pin.dataset.panel === id);
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.forgeTaskbar = new ForgeTaskbar();
});