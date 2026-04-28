// wallpaper-selector.js - Load and display wallpapers from manifest
async function loadWallpapers() {
  try {
    const res = await fetch('/desktop/wallpapers/manifest.json');
    if (!res.ok) throw new Error('Failed to load manifest');
    const data = await res.json();
    
    const grid = document.querySelector('.wallpaper-grid');
    if (!grid) return;
    
    grid.innerHTML = data.wallpapers.map(wp => `
      <div class="wallpaper-item" data-filename="${wp.filename}">
        <div class="wallpaper-preview" style="background: #1a1a2e; height: 120px; border-radius: var(--radius-md); cursor: pointer; display: flex; align-items: center; justify-content: center; border: 2px solid var(--border); hover: border-color: var(--accent-primary);">
          <span style="color: var(--text-muted);">${wp.name}</span>
        </div>
        <div class="wallpaper-name" style="margin-top: var(--space-sm); font-size: 12px; color: var(--text-secondary); text-align: center;">${wp.name}</div>
      </div>
    `).join('');
    
    // Add click handlers
    grid.querySelectorAll('.wallpaper-item').forEach(item => {
      item.addEventListener('click', () => {
        grid.querySelectorAll('.wallpaper-item').forEach(i => i.querySelector('.wallpaper-preview').style.borderColor = 'var(--border)');
        item.querySelector('.wallpaper-preview').style.borderColor = 'var(--accent-primary)';
        
        // Apply wallpaper (in real implementation, save to settings)
        console.log('Selected wallpaper:', item.dataset.filename);
      });
    });
    
  } catch (err) {
    console.error('Failed to load wallpapers:', err);
  }
}

// Load on page load
if (document.querySelector('.wallpaper-grid')) {
  loadWallpapers();
}
