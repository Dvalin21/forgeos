# Plan: Connect ForgeOS Widgets + ForgeFileDB (Option A)

## Context
- ForgeOS WebGUI (dashboard widgets) needs real API data
- ForgeFileDB (`forgedb.html`) is a complete UI with NO backend API
- 15 files committed with glassmorphism/SVG icons/backgrounds ready
- API server running on port 5082 (from `/.worktrees/phase1-features/src/`)

## Phase 1: Connect ForgeOS Dashboard Widgets to API

### 1.1 Fix API Authentication
- [ ] Check if API requires auth token (getting "Not authenticated" on `/api/system/stats`)
- [ ] Update widget fetch calls to include credentials/token
- [ ] Test: `curl http://localhost:5082/api/system/stats`

### 1.2 Update Widget Components
- [ ] `widget-system.js` → `GET /api/system/stats` (CPU, RAM, temp, uptime)
- [ ] `widget-storage.js` → `GET /api/storage/df` (disk usage)
- [ ] `widget-network.js` → `GET /api/network` (interface stats)
- [ ] `widget-alerts.js` → `GET /api/notifications` (recent alerts)

### 1.3 Add Real-time Updates
- [ ] Create WebSocket endpoint in API (`/ws/system`)
- [ ] Update widgets to subscribe to WebSocket for live updates
- [ ] Add fallback polling (30s interval) if WebSocket fails

### 1.4 Dashboard Page Polish
- [ ] Add loading states to widgets (spinner/skeleton)
- [ ] Add error handling (retry button)
- [ ] Animate value changes (smooth number transitions)

## Phase 2: Add ForgeFileDB API Endpoints

### 2.1 Create ForgeFileDB API Module
- [ ] Create `src/filedb-api.py` with all endpoints:
  - `GET /api/filedb/status` → connected_clients, open_databases, snapshots_today, total_conflicts
  - `GET /api/filedb/clients` → list of SMB clients with open files
  - `GET /api/filedb/databases` → discovered DB files grouped by directory
  - `GET /api/filedb/locks` → current file lock registry
  - `GET /api/filedb/snapshots` → list of snapshots
  - `POST /api/filedb/snapshot` → create snapshot for a DB directory
  - `POST /api/filedb/restore` → restore snapshot (in-place or to new location)
  - `GET/PUT /api/filedb/settings` → get/update settings (debounce, max_snapshots, watch_root)
  - `GET /api/filedb/log` → daemon log (last N lines)

### 2.2 Add WebSocket for ForgeFileDB
- [ ] Create `/ws/filedb` endpoint for real-time updates
- [ ] Broadcast: client_connect, client_disconnect, lock_acquired, lock_released, snapshot_created, restore_complete

### 2.3 Mock Mode for Development
- [ ] Add mock data mode (no actual ForgeFileDB daemon running)
- [ ] Return realistic sample data for all endpoints
- [ ] Toggle mock mode via config/env variable

## Phase 3: Connect ForgeFileDB UI to API

### 3.1 Update `forgedb.html` JavaScript
- [ ] Replace `const API = ''` with actual API base URL
- [ ] Update `connectWS()` to use `/ws/filedb` endpoint
- [ ] Update `loadDatabases()` → `GET /api/filedb/databases`
- [ ] Update `loadSnapshots()` → `GET /api/filedb/snapshots`
- [ ] Update `loadSettings()` → `GET /api/filedb/settings`
- [ ] Update `saveSettings()` → `PUT /api/filedb/settings`
- [ ] Update `loadLogs()` → `GET /api/filedb/log`
- [ ] Update `snapDir()` → `POST /api/filedb/snapshot`
- [ ] Update `restore` functionality → `POST /api/filedb/restore`

### 3.2 Add Navigation to ForgeOS
- [ ] Add "FileDB" nav item to `forge-topnav.js`
- [ ] Link to `/desktop/forgedb.html` from dashboard
- [ ] Add ForgeFileDB widget to dashboard (show client count, DB count)

## Phase 4: Production Hardening

### 4.1 Authentication
- [ ] Add JWT token auth to all new endpoints
- [ ] Update ForgeFileDB UI to handle 401 responses
- [ ] Redirect to login if not authenticated

### 4.2 Error Handling
- [ ] Add proper error messages (not just console.log)
- [ ] Show user-friendly error toasts
- [ ] Retry logic for transient failures

### 4.3 Testing
- [ ] Add tests for all new API endpoints
- [ ] Add tests for WebSocket functionality
- [ ] Test ForgeFileDB UI with mock data

## Files to Modify
1. `src/forgeos-api.py` - Add ForgeFileDB endpoints
2. `src/filedb-api.py` - New file, ForgeFileDB API implementation
3. `web/desktop/components/widget-*.js` - Connect to real API
4. `web/desktop/forgedb.html` - Update JS to use real API
5. `web/desktop/components/forge-topnav.js` - Add FileDB nav item

## Verification
- [ ] `curl http://localhost:5082/api/system/stats` returns real data
- [ ] Dashboard widgets show live system stats
- [ ] `curl http://localhost:5082/api/filedb/status` returns mock/real data
- [ ] ForgeFileDB page loads and connects to API
- [ ] WebSocket updates flow to all components

## Notes
- ForgeFileDB daemon may not exist yet - use mock data initially
- Keep backward compatibility with existing API consumers
- WebSocket path must not conflict with future endpoints
- All new endpoints must follow existing API response format: `{"status": "ok", "data": {...}}