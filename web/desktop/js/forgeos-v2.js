/* ForgeOS v2.0 Main JavaScript
 * Navigation, panels, and interactions
 */

// Configuration
const CONFIG = {
  apiBase: '/api',
  refreshInterval: 30000, // 30 seconds
  animationDuration: 250
};

// State
let state = {
  currentPanel: 'dashboard',
  sidebarCollapsed: false,
  data: {}
};

// Navigation items
const NAV_ITEMS = [
  { id: 'dashboard', icon: '◈', label: 'Dashboard', section: 'main' },
  { id: 'storage', icon: '⬡', label: 'Storage', section: 'main' },
  { id: 'docker', icon: '◉', label: 'Apps', section: 'main' },
  { id: 'network', icon: '⬢', label: 'Network', section: 'main' },
  { id: 'backup', icon: '◫', label: 'Backup', section: 'main' },
  { id: 'shares', icon: '▤', label: 'Shares', section: 'main' },
  { id: 'mail', icon: '✉', label: 'Mail', section: 'services' },
  { id: 'auth', icon: '⚿', label: 'Authentication', section: 'services' },
  { id: 'monitoring', icon: '◉', label: 'Monitoring', section: 'services' },
  { id: 'imaging', icon: '⬢', label: 'Imaging', section: 'tools' },
  { id: 'settings', icon: '⚙', label: 'Settings', section: 'system' }
];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initHeader();
  loadPanel('dashboard');
  startAutoRefresh();
});

// Sidebar
function initSidebar() {
  const nav = document.getElementById('nav-main');
  if (!nav) return;
  
  // Group by section
  const sections = {};
  NAV_ITEMS.forEach(item => {
    if (!sections[item.section]) sections[item.section] = [];
    sections[item.section].push(item);
  });
  
  // Build navigation
  Object.entries(sections).forEach(([section, items]) => {
    // Section title
    const title = document.createElement('div');
    title.className = 'nav-section-title';
    title.textContent = section.charAt(0).toUpperCase() + section.slice(1);
    nav.appendChild(title);
    
    // Items
    items.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'nav-item';
      btn.dataset.panel = item.id;
      btn.innerHTML = `<span class="nav-icon">${item.icon}</span><span class="nav-label">${item.label}</span>`;
      btn.onclick = () => loadPanel(item.id);
      nav.appendChild(btn);
    });
  });
}

// Header actions
function initHeader() {
  // Toggle sidebar
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (toggleBtn) {
    toggleBtn.onclick = toggleSidebar;
  }
  
  // Refresh button
  const refreshBtn = document.getElementById('header-refresh');
  if (refreshBtn) {
    refreshBtn.onclick = refreshData;
  }
}

// Toggle sidebar
function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) {
    sidebar.classList.toggle('collapsed', state.sidebarCollapsed);
  }
}

// Load panel
async function loadPanel(panelId) {
  // Update nav
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.panel === panelId);
  });
  
  // Update header
  const panelTitle = document.getElementById('header-title');
  if (panelTitle) {
    const navItem = NAV_ITEMS.find(n => n.id === panelId);
    panelTitle.textContent = navItem ? navItem.label : panelId;
  }
  
  // Show panel content
  state.currentPanel = panelId;
  
  // Load panel data
  await loadPanelData(panelId);
}

// Load panel data
async function loadPanelData(panelId) {
  const endpoints = {
    'dashboard': '/system/stats',
    'storage': '/storage/pools',
    'docker': '/docker/containers',
    'network': '/network/interfaces',
    'backup': '/backup/status',
    'shares': '/samba/shares',
    'mail': '/mail/status',
    'auth': '/auth/users',
    'monitoring': '/monitoring/metrics',
    'imaging': '/imaging/status',
    'settings': '/settings'
  };
  
  const endpoint = endpoints[panelId];
  if (!endpoint) return;
  
  try {
    const response = await fetch(CONFIG.apiBase + endpoint);
    state.data[panelId] = await response.json();
    renderPanel(panelId, state.data[panelId]);
  } catch (error) {
    console.error('Failed to load', panelId, error);
  }
}

// Render panels
function renderPanel(panelId, data) {
  const container = document.getElementById(`panel-${panelId}`);
  if (!container) return;
  
  // Already rendered
  if (container.dataset.loaded) return;
  
  // Render based on panel type
  const renderers = {
    'dashboard': renderDashboard,
    'storage': renderStorage,
    'docker': renderDocker,
    'backup': renderBackup,
    'network': renderNetwork
  };
  
  const render = renderers[panelId];
  if (render) {
    render(container, data);
  }
  
  container.dataset.loaded = 'true';
}

// Dashboard renderer
function renderDashboard(container, data) {
  container.innerHTML = `
    <div class="widget-grid">
      <div class="widget stat-card">
        <span class="stat-label">CPU Usage</span>
        <span class="stat-value">${data.cpu || 0}%</span>
        <div class="progress"><div class="progress-bar" style="width: ${data.cpu || 0}%"></div></div>
      </div>
      <div class="widget stat-card">
        <span class="stat-label">Memory</span>
        <span class="stat-value">${data.memory || 0}%</span>
        <span class="text-secondary text-sm">${data.memoryUsed || 0}GB / ${data.memoryTotal || 0}GB</span>
      </div>
      <div class="widget stat-card">
        <span class="stat-label">Storage</span>
        <span class="stat-value">${data.storage || 0}%</span>
        <span class="text-secondary text-sm">${data.storageUsed || 0}TB / ${data.storageTotal || 0}TB</span>
      </div>
      <div class="widget stat-card">
        <span class="stat-label">Containers</span>
        <span class="stat-value">${data.containers || 0}</span>
        <span class="text-secondary text-sm">${data.containersRunning || 0} running</span>
      </div>
    </div>
  `;
}

// Storage renderer
function renderStorage(container, data) {
  const pools = (data.pools || []).map(pool => `
    <div class="card mb-md">
      <div class="card-header">
        <span class="card-title">${pool.name}</span>
        <span class="status-dot ${pool.state}"></span>
      </div>
      <div class="flex justify-between items-center">
        <span>${pool.used} / ${pool.total}</span>
        <span class="text-secondary">${pool.usage}%</span>
      </div>
      <div class="progress mt-sm">
        <div class="progress-bar" style="width: ${pool.usage}%"></div>
      </div>
    </div>
  `).join('');
  
  container.innerHTML = pools || '<p class="text-muted">No storage pools configured</p>';
}

// Docker renderer
function renderDocker(container, data) {
  const containers = (data.containers || []).map(c => `
    <div class="card mb-sm">
      <div class="flex items-center justify-between">
        <div>
          <span class="font-semibold">${c.name}</span>
          <span class="text-sm text-secondary ml-sm">${c.image}</span>
        </div>
        <span class="status-dot ${c.status}"></span>
      </div>
      <div class="flex gap-sm mt-sm">
        <button class="btn btn-ghost btn-sm" onclick="dockerAction('${c.name}', 'start')">Start</button>
        <button class="btn btn-ghost btn-sm" onclick="dockerAction('${c.name}', 'stop')">Stop</button>
        <button class="btn btn-ghost btn-sm" onclick="dockerAction('${c.name}', 'restart')">Restart</button>
      </div>
    </div>
  `).join('');
  
  container.innerHTML = containers || '<p class="text-muted">No containers running</p>';
}

// Backup renderer
function renderBackup(container, data) {
  const tools = ['borg', 'restic', 'rclone', 'fog'];
  const toolCards = tools.map(tool => `
    <div class="card">
      <div class="card-header">
        <span class="card-title">${tool.toUpperCase()}</span>
        <span class="status-dot ${data[tool]?.installed ? 'online' : 'offline'}"></span>
      </div>
      <p class="text-secondary">${data[tool]?.jobs?.length || 0} backup jobs</p>
      <button class="btn btn-primary mt-md" onclick="createBackupJob('${tool}')">+ New Job</button>
    </div>
  `).join('');
  
  container.innerHTML = `<div class="grid grid-4">${toolCards}</div>`;
}

// Network renderer
function renderNetwork(container, data) {
  const interfaces = (data.interfaces || []).map(iface => `
    <div class="card mb-sm">
      <div class="flex justify-between items-center">
        <span class="font-semibold">${iface.name}</span>
        <span class="text-secondary">${iface.address}</span>
      </div>
      <div class="text-sm text-muted mt-xs">
        ${iface.state} • ${iface.speed} • ${iface.type}
      </div>
    </div>
  `).join('');
  
  container.innerHTML = interfaces || '<p class="text-muted">No interfaces found</p>';
}

// Docker actions
async function dockerAction(name, action) {
  try {
    await fetch(`/api/docker/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    loadPanelData('docker');
  } catch (error) {
    console.error('Docker action failed:', error);
  }
}

// Create backup job
async function createBackupJob(tool) {
  // This would open a modal
  const name = prompt(`Enter backup job name for ${tool}:`);
  if (!name) return;
  
  try {
    await fetch(`/api/backup/${tool}/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    loadPanelData('backup');
  } catch (error) {
    console.error('Create backup job failed:', error);
  }
}

// Auto refresh
let refreshTimer;
function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    if (state.currentPanel) {
      loadPanelData(state.currentPanel);
    }
  }, CONFIG.refreshInterval);
}

function refreshData() {
  if (state.currentPanel) {
    loadPanelData(state.currentPanel);
  }
}

// API helpers
async function forgeAPI(path, options = {}) {
  const defaults = {
    headers: { 'Content-Type': 'application/json' }
  };
  const config = { ...defaults, ...options };
  
  try {
    const response = await fetch(CONFIG.apiBase + path, config);
    return await response.json();
  } catch (error) {
    console.error('API error:', error);
    throw error;
  }
}

// Format bytes
function fmtBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Export for global use
window.ForgeOS = {
  CONFIG,
  state,
  loadPanel,
  dockerAction,
  createBackupJob,
  forgeAPI,
  fmtBytes,
  refreshData
};