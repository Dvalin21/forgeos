// wallpaper-selector.js - Load and display wallpapers from manifest
async function loadWallpapers() {
  try {
    const res = await fetch('/desktop/backgrounds/manifest.json');
    if (!res.ok) throw new Error('Failed to load manifest');
    const data = await res.json();
    
    const grid = document.querySelector('.wallpaper-grid');
    if (!grid) return;
    
    grid.innerHTML = data.wallpapers.map(wp => `
      <div class="wallpaper-item" data-filename="${wp.filename}" onclick="selectWallpaper(this, '${wp.css}')">
        <div class="wallpaper-preview" style="background: #1a1a2e; height: 120px; border-radius: var(--radius-md); cursor: pointer; display: flex; align-items: center; justify-content: center; border: 2px solid var(--border); overflow: hidden;">
          <img src="/desktop/backgrounds/${wp.filename}" alt="${wp.name}" style="width: 100%; height: 100%; object-fit: cover; opacity: 0.9;" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
          <span style="color: var(--text-muted); display: none; position: absolute;">${wp.name}</span>
        </div>
        <div class="wallpaper-name" style="margin-top: var(--space-sm); font-size: 12px; color: var(--text-secondary); text-align: center;">${wp.name}</div>
      </div>
    `).join('');
    
  } catch (err) {
    console.error('Failed to load wallpapers:', err);
    // Show fallback options
    const grid = document.querySelector('.wallpaper-grid');
    if (grid) {
      grid.innerHTML = '<div style="color: var(--text-muted); padding: var(--space-md);">Failed to load wallpapers. Check /desktop/backgrounds/ folder.</div>';
    }
  }
}

function selectWallpaper(item, css) {
  // Remove selection from all items
  document.querySelectorAll('.wallpaper-item').forEach(i => {
    i.querySelector('.wallpaper-preview').style.borderColor = 'var(--border)';
    i.querySelector('.wallpaper-preview').style.boxShadow = 'none';
  });
  
  // Highlight selected
  const preview = item.querySelector('.wallpaper-preview');
  preview.style.borderColor = 'var(--accent-primary)';
  preview.style.boxShadow = 'var(--glow-md)';
  
  // Apply wallpaper to body
  document.body.style = css;
  
  // Save preference (in production, save to API/localStorage)
  localStorage.setItem('forgeos-wallpaper', css);
  console.log('Applied wallpaper:', item.dataset.filename);
}

// Load saved wallpaper on page load
function loadSavedWallpaper() {
  const saved = localStorage.getItem('forgeos-wallpaper');
  if (saved) {
    document.body.style = saved;
  }
}

// Initialize
if (document.querySelector('.wallpaper-grid')) {
  loadWallpapers();
  loadSavedWallpaper();
}

// Load on page load
if (document.querySelector('.wallpaper-grid')) {
  loadWallpapers();
}
