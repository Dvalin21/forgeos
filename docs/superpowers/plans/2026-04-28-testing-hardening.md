# ForgeOS WebGUI & API - Testing & Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test all WebGUI and API integrations, add WebSocket endpoints, and harden the system for production use.

**Architecture:** WebGUI (port 5080) ↔ API (port 5082) with JWT auth. ForgeFileDB API with mock mode.

**Tech Stack:** FastAPI (Python), Vanilla JS (Web Components), JWT auth, WebSocket

---

### Task 1: Test WebGUI Serving

**Files:**
- Modify: `web/dev-server.py:26-35`
- Test: `curl http://10.0.0.239:5080/desktop/`

- [ ] **Step 1: Kill all processes on port 5080**

```bash
sudo kill -9 $(lsof -t -i :5080) 2>/dev/null
sleep 2
lsof -i :5080 2>/dev/null || echo "Port 5080 is FREE"
```

- [ ] **Step 2: Start Web Server (from correct directory)**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/web/
python3 dev-server.py 5080 &
sleep 3
```

- [ ] **Step 3: Verify WebGUI loads**

```bash
curl -s http://10.0.0.239:5080/desktop/ | head -20
# Should show: <!DOCTYPE html>...<widget-filedb></widget-filedb>...

curl -s http://10.0.0.239:5080/desktop/filedb.html | head -20
# Should show: ForgeFileDB page with glassmorphism theme
```

- [ ] **Step 4: Verify backgrounds load**

```bash
curl -s http://10.0.0.239:5080/desktop/ | grep "backgrounds"
# Should show backgrounds option in dashboard
```

- [ ] **Step 5: Commit if any fixes needed**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/
git add -A && git status
# Only commit if there are actual changes
```

---

### Task 2: Test API Server

**Files:**
- Modify: `src/forgeos-api.py:95-100`
- Test: `curl http://10.0.0.239:5082/health`

- [ ] **Step 1: Kill all processes on port 5082**

```bash
sudo kill -9 $(lsof -t -i :5082) 2>/dev/null
sleep 2
```

- [ ] **Step 2: Start API Server**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/src/
python3 forgeos-api.py &
sleep 3
```

- [ ] **Step 3: Verify API health endpoint**

```bash
curl -s http://10.0.0.239:5082/health
# Should return: {"status":"ok","ts":...}
```

- [ ] **Step 4: Get JWT token**

```bash
TOKEN=$(curl -s -X POST http://10.0.0.239:5082/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeMe"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token: ${TOKEN:0:50}..."
```

- [ ] **Step 5: Test all widget endpoints**

```bash
# System stats
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/system/stats | python3 -m json.tool | head -20

# Storage
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/storage/df | python3 -m json.tool | head -20

# Network
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/network | python3 -m json.tool | head -20

# Notifications
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/notifications?limit=5 | python3 -m json.tool | head -20
```

- [ ] **Step 6: Test ForgeFileDB endpoints (mock mode)**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/filedb/status | python3 -m json.tool

curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/filedb/databases | python3 -m json.tool | head -30
```

---

### Task 3: Add WebSocket Endpoints for Real-time Updates

**Files:**
- Create: `src/websocket-handler.py`
- Modify: `src/forgeos-api.py:95-100` (add WebSocket routes)
- Test: WebSocket client connection

- [ ] **Step 1: Create WebSocket handler module**

```python
# src/websocket-handler.py
"""
WebSocket handlers for real-time updates.
"""
import asyncio
import json
from typing import Dict

from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)
    
    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)

manager = ConnectionManager()
```

- [ ] **Step 2: Add WebSocket endpoints to API**

```python
# Add to src/forgeos-api.py after line 100
from websocket_handler import manager

@app.websocket("/ws/system")
async def websocket_system(ws: WebSocket):
    await manager.connect(ws, "system")
    try:
        while True:
            # Send system stats every 2 seconds
            data = await get_system_stats()  # Existing function
            await ws.send_json({"type": "system_update", "data": data})
            await asyncio.sleep(2)
    except Exception:
        manager.disconnect("system")

@app.websocket("/ws/filedb")
async def websocket_filedb(ws: WebSocket):
    await manager.connect(ws, "filedb")
    try:
        while True:
            # Send FileDB status updates
            data = get_filedb_status()  # Existing function from filedb_api
            await ws.send_json({"type": "filedb_update", "data": data})
            await asyncio.sleep(5)
    except Exception:
        manager.disconnect("filedb")
```

- [ ] **Step 3: Update widgets to use WebSocket (optional, keep polling as fallback)**

```javascript
// Add to widget-system.js loadData() as optional enhancement
if ("WebSocket" in window) {
    const ws = new WebSocket(`ws://${window.location.host}/ws/system`);
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "system_update") {
            this.data = data.data;
            this.update(this.data);
        }
    };
}
```

- [ ] **Step 4: Test WebSocket connection**

```bash
# Use wscat or similar tool
pip3 install websockets 2>/dev/null

# Test system WebSocket
python3 -c "
import asyncio, websockets
async def test():
    uri = 'ws://10.0.0.239:5082/ws/system'
    async with websockets.connect(uri) as ws:
        msg = await ws.recv()
        print('Received:', msg)
asyncio.run(test())
"
```

- [ ] **Step 5: Commit WebSocket implementation**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/
git add src/websocket-handler.py src/forgeos-api.py
git commit -m "feat(api): Add WebSocket endpoints for real-time updates

- Add /ws/system endpoint (system stats every 2s)
- Add /ws/filedb endpoint (FileDB updates every 5s)
- ConnectionManager for handling multiple clients
- Optional WebSocket support in widgets (fallback to polling)"
```

---

### Task 4: Add Production Hardening

**Files:**
- Modify: `web/desktop/components/forge-widget.js`
- Modify: `web/desktop/components/widget-*.js`
- Modify: `src/forgeos-api.py`

- [ ] **Step 1: Add error toasts in WebGUI**

```javascript
// Add to forge-widget.js or index.html
function showToast(message, type='error') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
```

- [ ] **Step 2: Handle 401 responses (redirect to login)**

```javascript
// Add to forge-widget.js _apiCall method
if (r.status === 401) {
    // Token missing or expired
    localStorage.removeItem('forgeos_token');
    showToast('Session expired. Please login again.', 'warning');
    setTimeout(() => window.location.href = '/desktop/login.html', 2000);
    return null;
}
```

- [ ] **Step 3: Add retry logic for transient failures**

```javascript
// Add to forge-widget.js
async _apiCall(endpoint, retries=3, delay=1000) {
    for (let i = 0; i < retries; i++) {
        try {
            const r = await fetch(endpoint, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('forgeos_token') || ''}`
                }
            });
            if (r.ok) return await r.json();
            if (r.status === 401) throw new Error('Unauthorized');
        } catch (e) {
            if (i === retries - 1) throw e;
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }
}
```

- [ ] **Step 4: Add rate limiting to API (if not present)**

```python
# Check src/forgeos-api.py for rate limiting
# Should have: from slowapi import Limiter
# If not, add rate limiting to auth endpoint
```

- [ ] **Step 5: Commit hardening changes**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/
git add web/desktop/
git commit -m "fix(webgui): Add production hardening

- Add error toasts for user feedback
- Handle 401 responses (redirect to login)
- Add retry logic for transient failures
- Ensure rate limiting on auth endpoint"
```

---

### Task 5: Add Tests for New Endpoints

**Files:**
- Create: `tests/test_filedb_api.py`
- Create: `tests/test_websocket.py`
- Modify: existing test files

- [ ] **Step 1: Create ForgeFileDB API tests**

```python
# tests/test_filedb_api.py
import pytest
from fastapi.testclient import TestClient
from src.forgeos_api import app

client = TestClient(app)

def test_filedb_status_mock():
    """Test ForgeFileDB status endpoint in mock mode."""
    response = client.get("/api/filedb/status")
    assert response.status_code == 200
    data = response.json()
    assert "daemon_running" in data
    assert "connected_clients" in data

def test_filedb_databases():
    """Test databases endpoint."""
    response = client.get("/api/filedb/databases")
    assert response.status_code == 200
    data = response.json()
    assert "databases" in data
```

- [ ] **Step 2: Create WebSocket tests**

```python
# tests/test_websocket.py
import pytest
from fastapi.testclient import TestClient
from src.forgeos_api import app

def test_websocket_system():
    """Test WebSocket connection."""
    client = TestClient(app)
    with client.websocket_connect("/ws/system") as websocket:
        data = websocket.receive_json()
        assert "type" in data
```

- [ ] **Step 3: Run all tests**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/
python3 -m pytest tests/ -v
# All tests should pass
```

- [ ] **Step 4: Commit tests**

```bash
cd /home/keith/forgeos-review/.worktrees/phase1-features/
git add tests/
git commit -m "test: Add tests for ForgeFileDB API and WebSocket endpoints"
```

---

## Verification Checklist

After completing all tasks:

- [ ] WebGUI serves from `http://10.0.0.239:5080/desktop/`
- [ ] All 5 widgets load and show live data
- [ ] ForgeFileDB page loads with glassmorphism theme
- [ ] API responds on `http://10.0.0.239:5082/health`
- [ ] All widget endpoints return valid JSON
- [ ] ForgeFileDB endpoints work (mock mode)
- [ ] WebSocket endpoints push real-time updates
- [ ] Error toasts show for failures
- [ ] 401 responses redirect to login
- [ ] All tests pass

---

## Next Steps

After this plan is complete:

1. **Push to GitHub:** `git push origin feature/phase1-features`
2. **Create Pull Request** to merge into `main`
3. **Deploy to test environment** (if available)
4. **Monitor logs** for any runtime errors

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-28-testing-hardening.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
