// window-manager.js - Floating window system
class ForgeWindowManager {
  constructor() {
    this.windows = new Map();
    this.zIndex = 1000;
    this.activeWindow = null;
  }
  
  createWindow(id, options = {}) {
    const defaults = {
      title: 'Window',
      width: 600,
      height: 400,
      x: 100,
      y: 100,
      resizable: true,
      minimizable: true,
      maximizable: true,
      closable: true
    };
    const config = { ...defaults, ...options };
    
    const windowEl = document.createElement('div');
    windowEl.className = 'forge-window';
    windowEl.id = `window-${id}`;
    windowEl.style.cssText = `
      left: ${config.x}px;
      top: ${config.y}px;
      width: ${config.width}px;
      height: ${config.height}px;
      z-index: ${++this.zIndex};
    `;
    
    windowEl.innerHTML = `
      <div class="window-titlebar">
        <span class="window-title">${config.title}</span>
        <div class="window-controls">
          ${config.minimizable ? '<button class="win-btn-minimize">_</button>' : ''}
          ${config.maximizable ? '<button class="win-btn-maximize">□</button>' : ''}
          ${config.closable ? '<button class="win-btn-close">×</button>' : ''}
        </div>
      </div>
      <div class="window-content" id="window-content-${id}"></div>
    `;
    
    // Add drag functionality
    const titlebar = windowEl.querySelector('.window-titlebar');
    this.makeDraggable(windowEl, titlebar);
    
    // Add close functionality
    const closeBtn = windowEl.querySelector('.win-btn-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.closeWindow(id));
    }
    
    // Minimizing
    const minBtn = windowEl.querySelector('.win-btn-minimize');
    if (minBtn) {
      minBtn.addEventListener('click', () => this.minimizeWindow(id));
    }
    
    // Focus on click
    windowEl.addEventListener('mousedown', () => this.focusWindow(id));
    
    // Add to desktop
    const desktop = document.getElementById('desktop');
    if (desktop) {
      desktop.appendChild(windowEl);
    }
    
    this.windows.set(id, { window: windowEl, config });
    
    return windowEl;
  }
  
  makeDraggable(windowEl, handle) {
    let isDragging = false;
    let startX, startY, startLeft, startTop;
    
    handle.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      startLeft = windowEl.offsetLeft;
      startTop = windowEl.offsetTop;
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
    });
    
    const onDrag = (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      windowEl.style.left = (startLeft + dx) + 'px';
      windowEl.style.top = (startTop + dy) + 'px';
    };
    
    const stopDrag = () => {
      isDragging = false;
      document.removeEventListener('mousemove', onDrag);
      document.removeEventListener('mouseup', stopDrag);
    };
  }
  
  focusWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.style.zIndex = ++this.zIndex;
      this.activeWindow = id;
    }
  }
  
  closeWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.remove();
      this.windows.delete(id);
    }
  }
  
  minimizeWindow(id) {
    const win = this.windows.get(id);
    if (win) {
      win.window.style.display = 'none';
    }
  }
}

// Global instance
window.forgeOS = window.forgeOS || {};
window.forgeOS.windows = window.forgeOS.windows || new ForgeWindowManager();
window.forgeOS.openWindow = (id, options) => {
  return window.forgeOS.windows.createWindow(id, options);
};

document.addEventListener('DOMContentLoaded', () => {
  window.forgeOS.windows = new ForgeWindowManager();
});