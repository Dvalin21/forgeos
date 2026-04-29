# ForgeOS Phase 2: Mobile + Plugins + API Documentation

**Date:** 2026-04-29  
**Branch:** feature/phase2-security-monitoring  
**Status:** In Progress  

---

## 5. Mobile Responsive Design

### 5.1 Current State
- WebGUI is DSM-7 inspired desktop-only design
- No mobile breakpoints or responsive layout
- Window management assumes mouse/keyboard

### 5.2 Design Goals
- Responsive layout for tablets (768px+) and phones (320px+)
- Touch-friendly interactions (swipe, tap, long-press)
- Simplified mobile navigation (bottom tab bar)
- Collapsible sidebar for tablet mode

### 5.3 Implementation

**CSS Media Queries:**
```css
/* Tablet */
@media (max-width: 1024px) {
    .sidebar { transform: translateX(-100%); }
    .sidebar.active { transform: translateX(0); }
    .taskbar { display: none; }
    .mobile-tabbar { display: flex; }
}

/* Phone */
@media (max-width: 480px) {
    .window { 
        width: 100% !important;
        height: calc(100vh - 60px) !important;
        top: 0 !important;
        left: 0 !important;
    }
}
```

**Mobile Tab Bar (bottom of screen):**
- Dashboard, Storage, Network, Files, Settings

**Touch Gestures:**
- Swipe left/right to switch windows
- Long press for context menu
- Pinch to zoom (file previews)

---

## 6. Plugin System Architecture

### 6.1 Design Principles
- **Isolation:** Each plugin runs in separate process/sandbox
- **API:** RESTful + WebSocket for real-time
- **Discovery:** Plugins register via `/etc/forgeos/plugins.d/*.json`
- **Permissions:** Explicit grants (filesystem, network, system)

### 6.2 Plugin Manifest (plugin.json)
```json
{
  "id": "photo-gallery",
  "name": "Photo Gallery",
  "version": "1.0.0",
  "entrypoint": "/opt/forgeos/plugins/photo-gallery/main.py",
  "permissions": ["filesystem:read", "network:outbound"],
  "hooks": ["file:upload", "menu:tools"],
  "api_prefix": "/api/plugins/photo-gallery"
}
```

### 6.3 Plugin Loader (src/plugin_loader.py)
- Scan `/etc/forgeos/plugins.d/*.json`
- Validate manifest schema
- Start plugin process (FastAPI/uvicorn)
- Proxy requests via `httpx` to plugin API
- Monitor health (heartbeat every 30s)

### 6.4 Plugin API (for plugin developers)
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/plugins/my-plugin/items")
def get_items():
    return {"items": []}

# Plugins can register hooks
@app.post("/api/plugins/my-plugin/hooks/file:upload")
def on_file_upload(file_info: dict):
    # Process uploaded file
    pass
```

### 6.5 WebGUI Integration
- Plugins appear in main sidebar (custom icons)
- Window content loaded via `<iframe>` or native JS
- Settings page for enabling/disabling plugins

---

## 7. OpenAPI Documentation

### 7.1 Enable Swagger UI
```python
app = FastAPI(
    title="ForgeOS API",
    version="1.0",
    docs_url="/api/docs",  # Enable Swagger
    redoc_url="/api/redoc",  # Enable ReDoc
    openapi_url="/api/openapi.json",
)
```

### 7.2 Add OpenAPI Extensions
- Security schemes (JWT, API key, OAuth2)
- Example requests/responses
- Response models for all endpoints
- Tags for grouping (Auth, Storage, Docker, etc.)

### 7.3 Generate Static Docs
```bash
# Generate OpenAPI spec
curl http://localhost:5080/api/openapi.json > openapi.json

# Generate static HTML docs
npx @redocly/redocly-cli build-docs openapi.json --output docs/api-docs.html
```

### 7.4 API Versioning Strategy
- Current: `/api/v1/` (implicit)
- Future: `/api/v2/` for breaking changes
- Deprecation headers: `X-Deprecated: true`, `X-Sunset: 2026-12-31`

---

## 8. Implementation Priority

1. **OpenAPI docs** (quick win - enable Swagger)
2. **Mobile responsive CSS** (CSS media queries)
3. **Mobile tab bar** (HTML + JS)
4. **Plugin manifest schema** (JSON schema)
5. **Plugin loader** (scan + validate + start)
6. **Plugin API examples** (sample plugins)

---

## 9. Files to Create/Modify

**Mobile:**
- `web/desktop/css/mobile.css` - Media queries
- `web/desktop/js/mobile-tabbar.js` - Touch navigation
- `web/desktop/index.html` - Add mobile tab bar

**Plugins:**
- `src/plugin_loader.py` - Plugin manager
- `src/plugin_api.py` - Plugin API helpers
- `schema/plugin-manifest.json` - JSON schema
- `plugins/example/` - Sample plugin

**API Docs:**
- Modify `src/forgeos-api.py` - Enable Swagger/ReDoc
- `docs/api/README.md` - API documentation guide
- `scripts/generate-api-docs.sh` - Automation

---

## 10. Success Criteria

- [ ] Swagger UI accessible at `/api/docs`
- [ ] Mobile layout works on 320px+ screens
- [ ] Bottom tab bar on mobile (<768px)
- [ ] Plugins can be loaded from `/etc/forgeos/plugins.d/`
- [ ] Plugin API has example and documentation
- [ ] All API endpoints documented with examples
- [ ] Response models for all endpoints
