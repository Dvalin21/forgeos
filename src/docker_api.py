"""ForgeOS — DOCKER API surface.

Mounts under the existing FastAPI app via:

    from docker_api import router as docker_router, set_helpers as set_docker_helpers
    set_docker_helpers(run_args=_run_args, audit=_audit)
    app.include_router(docker_router)

Routes (/api/docker/*): apps list, install
"""
from __future__ import annotations

import subprocess
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# ── Admin gate ──
def require_admin(user=Depends(verify_token)):
    """Installing a container runs `docker run` as root — admin only."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
) -> None:
    global _run_args, _audit
    _run_args = run_args
    _audit = audit


# Docker app catalog — module-level constant.
DOCKER_APPS = [
    {"name": "nginx", "image": "nginx:latest", "port": 80, "category": "web"},
    {"name": "jellyfin", "image": "jellyfin/jellyfin:latest", "port": 8096, "category": "media"},
    {"name": "adguard", "image": "adguard/adguardhome:latest", "port": 3000, "category": "network"},
    {"name": "portainer", "image": "portainer/portainer-ce:latest", "port": 9000, "category": "admin"},
    {"name": "homarr", "image": "ghcr.io/axistent/homarr:latest", "port": 3000, "category": "dashboard"},
    {"name": "nextcloud", "image": "nextcloud:latest", "port": 80, "category": "cloud"},
    {"name": "rustfs", "image": "rustfs/rustfs:latest", "port": 9000, "admin_port": 9001, "category": "storage", "s3_api": True, "console": True},
    {"name": "rustfs-console", "image": "rustfs/console:latest", "port": 9001, "category": "storage", "type": "console"},
    {"name": "prometheus", "image": "prom/prometheus:latest", "port": 9090, "category": "monitoring"},
    {"name": "grafana", "image": "grafana/grafana:latest", "port": 3000, "category": "monitoring"},
    {"name": "immich", "image": "ghcr.io/immich-app/immich-server:latest", "port": 2283, "category": "media"},
]


@router.get("/api/docker/apps")
async def docker_apps(user=Depends(verify_token)):
    """Get available Docker apps for one-click install"""
    return {"apps": DOCKER_APPS}


@router.post("/api/docker/install")
async def docker_install(app: str, image: str = None, ports: List[str] = None, user=Depends(require_admin)):
    """Install Docker app from curated list"""
    app_info = next((a for a in DOCKER_APPS if a["name"] == app), None)
    if not app_info:
        app_info = {"name": app, "image": image or app, "ports": ports or []}

    port_args = []
    if app_info.get("port"):
        port_args = ["-p", f"{app_info['port']}:{app_info['port']}"]

    cmd = ["docker", "run", "-d", "--name", app_info["name"]] + port_args + [app_info["image"]]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Docker pull timed out")

    if result.returncode == 0:
        _audit(user["sub"], "docker.install", "success",
                f"App '{app_info['name']}' installed (image: {app_info['image']})")
        return {"status": "installed", "app": app_info["name"]}
    _audit(user["sub"], "docker.install", "failure",
            f"App '{app_info['name']}' install failed: {result.stderr.strip()[:200]}")
    raise HTTPException(status_code=500, detail=result.stderr.strip() or "docker run failed")


