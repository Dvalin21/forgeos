# ForgeOS WebGUI + API Architecture (Review & Fix)

## Current Problems Identified

1. **Multiple servers running** - Port conflicts, wrong directories
2. **File locations wrong** - `filedb.html` was in `/web/` instead of `/web/desktop/`
3. **CSS paths broken** - Relative vs absolute path confusion
4. **API binding to 127.0.0.1** - Not accessible from network (10.0.0.239)
5. **Python import fails** - `filedb-api.py` (hyphen) renamed to `filedb_api.py` (underscore)

## Clean Architecture

### File Structure
```
forgeos-review/.worktrees/phase1-features/
├── web/                          # Web server root (port 5080)
│   ├── dev-server.py              # Simple HTTP server (NO-CACHE)
│   ├── desktop/                  # Main WebGUI
│   │   ├── index.html          # Dashboard with widgets
│   │   ├── filedb.html        # ForgeFileDB UI
│   │   ├── css/forgeos.css   # Glassmorphism theme
│   │   ├── components/        # Widgets + topnav
│   │   └── backgrounds/       # Background options
│   └── dev-server.py            # Should be here or project root
└── src/                          # API server (port 5082)
    ├── forgeos-api.py             # Main FastAPI application
    └── filedb_api.py             # ForgeFileDB endpoints (mock mode)
```

### Server Architecture

| Server | Port | Directory Served | Purpose |
|--------|------|-------------------|---------|
| `dev-server.py` | 5080 | `web/` | Serves WebGUI (NO-CACHE) |
| `forgeos-api.py` | 5082 | N/A (API) | REST + WebSocket API |

### Critical Rules

1. **`dev-server.py` must serve from `web/` directory** (relative to script location)
2. **`forgeos-api.py` binds to `0.0.0.0`** (accessible from 10.0.0.239)
3. **ALL HTML files in `web/desktop/`** - not `web/` root
4. **CSS paths relative** - `css/forgeos.css` (not `/desktop/css/`)
5. **Python files use underscores** - `filedb_api.py` (not hyphens)

### How to Start (Clean)

```bash
# Terminal 1: Web Server (port 5080)
cd /home/keith/forgeos-review/.worktrees/phase1-features/web/
python3 dev-server.py 5080 &
# Serves from web/ directory

# Terminal 2: API Server (port 5082)
cd /home/keith/forgeos-review/.worktrees/phase1-features/src/
python3 forgeos-api.py &
# Binds to 0.0.0.0:5082
```

### Verification

```bash
# WebGUI should show:
# - Dashboard: http://10.0.0.239:5080/desktop/
# - ForgeFileDB: http://10.0.0.239:5080/desktop/filedb.html
# - Backgrounds working, glassmorphism theme

# API should respond:
curl http://10.0.0.239:5082/health
# {"status":"ok","ts":...}

# ForgeFileDB endpoint:
TOKEN=$(curl -s -X POST http://10.0.0.239:5082/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeMe"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  http://10.0.0.239:5082/api/filedb/status
```

## Root Causes Fixed

| Issue | Root Cause | Fix |
|-------|-------------|-----|
| Changes not reflecting | `dev-server.py` served from wrong directory | Serve from `web/` |
| CSS not loading | Absolute paths (`/desktop/css/`) wrong | Relative paths (`css/`) |
| API not accessible | Bound to `127.0.0.1` only | Bind to `0.0.0.0` |
| Python import failed | File named `filedb-api.py` | Renamed to `filedb_api.py` |
| Port conflicts | Multiple servers, wrong ports | Clean start procedure |

## Status: READY FOR TESTING

All code committed:
- `4a00ee4` fix(arch): Remove duplicate forgeos-filedb.py
- `739d09f` fix(filedb): Correct CSS path after move to desktop/
- `ee2d24e` fix(filedb): Move to desktop dir and fix CSS path (ROOT CAUSE FIX)
- `ab8f743` fix(webgui): Use absolute path for forgeos.css
- `c99c388` fix(filedb): Update CSS to use ForgeOS glassmorphism theme
- `7df10c5` fix(api): Rename filedb-api.py to filedb_api.py
- `230a226` feat(widgets): Add ForgeFileDB dashboard widget
- `8fa1c0a` feat(filedb): Add ForgeFileDB API with mock data and UI integration
- `a47f933` feat(widgets): Complete API integration for all dashboard widgets
