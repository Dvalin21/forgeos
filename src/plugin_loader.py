"""
ForgeOS Plugin Loader
Discovers, validates, and manages plugins.

Features:
  - Scan /etc/forgeos/plugins.d/*.json
  - Validate against plugin-manifest.json schema
  - Start/stop plugin processes
  - Register/remove plugin routes
  - Monitor plugin health (heartbeat)
"""

import json
import os
import subprocess
import time
import signal
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse


# ── Configuration ──
PLUGINS_DIR = Path("/etc/forgeos/plugins.d")
SCHEMA_FILE = Path("schema/plugin-manifest.json")
PLUGIN_PROCESS: Dict[str, subprocess.Popen] = {}  # {plugin_id: process}
PLUGIN_ROUTERS: Dict[str, APIRouter] = {}  # {prefix: router}


# ── Plugin Manifest Schema ──
def validate_manifest(manifest: dict) -> tuple[bool, str]:
    """
    Validate plugin manifest against schema.
    Returns: (is_valid, error_message)
    """
    required = ["id", "name", "version", "entrypoint", "permissions"]
    
    # Check required fields
    for field in required:
        if field not in manifest:
            return False, f"Missing required field: {field}"
    
    # Validate ID format
    import re
    if not re.match(r"^[a-z0-9-]+$", manifest["id"]):
        return False, "ID must be lowercase alphanumeric with hyphens"
    
    # Validate version format
    if not re.match(r"^\d+\.\d+\.\d+$", manifest["version"]):
        return False, "Version must be semantic (e.g., 1.0.0)"
    
    # Validate permissions
    valid_permissions = [
        "filesystem:read", "filesystem:write",
        "network:outbound", "network:inbound",
        "system:info", "system:restart",
        "docker:read", "docker:write",
        "lxc:read", "lxc:write",
        "storage:read", "storage:write",
    ]
    for perm in manifest.get("permissions", []):
        if perm not in valid_permissions:
            return False, f"Invalid permission: {perm}"
    
    return True, ""


# ── Plugin Discovery ──
def discover_plugins() -> List[dict]:
    """
    Scan plugins.d directory for plugin manifests.
    Returns: List of validated plugin manifests.
    """
    if not PLUGINS_DIR.exists():
        return []
    
    plugins = []
    for manifest_file in PLUGINS_DIR.glob("*.json"):
        try:
            manifest = json.loads(manifest_file.read_text())
            
            # Validate
            is_valid, error = validate_manifest(manifest)
            if not is_valid:
                print(f"Plugin validation failed for {manifest_file}: {error}")
                continue
            
            # Check if entrypoint exists
            plugin_dir = manifest_file.parent
            entrypoint = plugin_dir / manifest["id"] / manifest["entrypoint"]
            if not entrypoint.exists():
                print(f"Entrypoint not found: {entrypoint}")
                continue
            
            plugins.append(manifest)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {manifest_file}: {e}")
        except Exception as e:
            print(f"Error loading {manifest_file}: {e}")
    
    return plugins


# ── Plugin Lifecycle ──
def start_plugin(manifest: dict) -> bool:
    """
    Start a plugin process.
    Returns: True if started successfully.
    """
    plugin_id = manifest["id"]
    plugin_dir = PLUGINS_DIR / plugin_id
    entrypoint = plugin_dir / manifest["entrypoint"]
    
    if not entrypoint.exists():
        print(f"Entrypoint not found: {entrypoint}")
        return False
    
    try:
        # Start plugin as subprocess
        proc = subprocess.Popen(
            ["python3", str(entrypoint)],
            cwd=str(plugin_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        PLUGIN_PROCESS[plugin_id] = proc
        print(f"Started plugin: {plugin_id} (PID: {proc.pid})")
        return True
    except Exception as e:
        print(f"Failed to start plugin {plugin_id}: {e}")
        return False


def stop_plugin(plugin_id: str) -> bool:
    """
    Stop a plugin process.
    Returns: True if stopped successfully.
    """
    proc = PLUGIN_PROCESS.get(plugin_id)
    if not proc:
        return False
    
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGKILL)
        
        del PLUGIN_PROCESS[plugin_id]
        print(f"Stopped plugin: {plugin_id}")
        return True
    except Exception as e:
        print(f"Failed to stop plugin {plugin_id}: {e}")
        return False


def restart_plugin(plugin_id: str) -> bool:
    """Restart a plugin."""
    # Find manifest
    manifest_file = PLUGINS_DIR / f"{plugin_id}.json"
    if not manifest_file.exists():
        return False
    
    manifest = json.loads(manifest_file.read_text())
    
    stop_plugin(plugin_id)
    return start_plugin(manifest)


# ── Plugin API Integration ──
def register_plugin_routes(app: FastAPI, manifest: dict) -> None:
    """
    Register plugin API routes with the main app.
    Creates a proxy to the plugin's API.
    """
    plugin_id = manifest["id"]
    api_prefix = manifest.get("api_prefix", f"/api/plugins/{plugin_id}")
    
    # Create a router for this plugin
    router = APIRouter(prefix=api_prefix)
    
    @router.get("/status")
    async def plugin_status():
        """Get plugin status."""
        proc = PLUGIN_PROCESS.get(plugin_id)
        if proc and proc.poll() is None:
            return {"status": "running", "pid": proc.pid}
        return {"status": "stopped"}
    
    # Add router to app
    app.include_router(router)
    PLUGIN_ROUTERS[api_prefix] = router
    print(f"Registered routes for plugin: {plugin_id} at {api_prefix}")


def unregister_plugin_routes(plugin_id: str) -> None:
    """Remove plugin routes from main app."""
    # Note: FastAPI doesn't support dynamic route removal easily
    # In production, would need to restart or use more advanced routing
    pass


# ── Health Monitoring ──
def check_plugin_health(plugin_id: str) -> dict:
    """
    Check if plugin is healthy.
    Returns: Health status dict.
    """
    proc = PLUGIN_PROCESS.get(plugin_id)
    if not proc:
        return {"healthy": False, "reason": "Not running"}
    
    # Check if process is alive
    if proc.poll() is not None:
        return {"healthy": False, "reason": f"Exited with code {proc.returncode}"}
    
    # TODO: In production, would make HTTP request to plugin's health endpoint
    return {"healthy": True, "pid": proc.pid}


# ── API Endpoints for Plugin Management ──
def get_plugins_endpoint() -> dict:
    """List all discovered plugins."""
    plugins = discover_plugins()
    return {
        "plugins": [
            {
                "id": p["id"],
                "name": p["name"],
                "version": p["version"],
                "status": "running" if p["id"] in PLUGIN_PROCESS else "stopped",
            }
            for p in plugins
        ],
        "count": len(plugins),
    }


def start_plugin_endpoint(plugin_id: str) -> dict:
    """Start a plugin by ID."""
    manifest_file = PLUGINS_DIR / f"{plugin_id}.json"
    if not manifest_file.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": f"Plugin {plugin_id} not found"}
        )
    
    manifest = json.loads(manifest_file.read_text())
    if start_plugin(manifest):
        return {"ok": True, "message": f"Plugin {plugin_id} started"}
    return JSONResponse(
        status_code=500,
        content={"detail": f"Failed to start plugin {plugin_id}"}
    )


def stop_plugin_endpoint(plugin_id: str) -> dict:
    """Stop a plugin by ID."""
    if stop_plugin(plugin_id):
        return {"ok": True, "message": f"Plugin {plugin_id} stopped"}
    return JSONResponse(
        status_code=404,
        content={"detail": f"Plugin {plugin_id} not running"}
    )


# ── Initialize Plugin System ──
def init_plugins(app: FastAPI) -> None:
    """Initialize plugin system on startup."""
    print("Initializing plugin system...")
    
    # Discover and validate plugins
    plugins = discover_plugins()
    print(f"Found {len(plugins)} plugin(s)")
    
    # Start enabled plugins
    for manifest in plugins:
        if manifest.get("autostart", True):
            start_plugin(manifest)
            register_plugin_routes(app, manifest)
    
    print("Plugin system initialized")
