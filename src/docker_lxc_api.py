"""
ForgeOS Docker & LXC Management API
Full Docker Compose + LXC container lifecycle management.

Provides:
- Docker: ps, start, stop, restart, logs, exec, compose up/down/ps/restart
- Docker Compose: Full lifecycle (up -d, down, stop, start, restart, logs, build, pull)
- LXC: Create, start, stop, restart, destroy, snapshot, exec, info
- Prune: system prune, volume prune, network prune, image prune
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from forgeos_auth import verify_token

import re

# ── Router ──
router = APIRouter(prefix="/api/docker", tags=["Docker Management"],
                   dependencies=[Depends(verify_token)])

# ── Trust boundary: validate names before they reach the docker CLI ──
# Argument injection is real even without shell=True — a name like "-foo" could
# be read as a flag. Docker names/images allow [a-zA-Z0-9][a-zA-Z0-9_.-/:@] but
# must not start with '-'. Keep it strict.
_DOCKER_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/:@-]{0,127}\Z")


def _valid_ref(ref: str, what: str = "name") -> str:
    if not _DOCKER_NAME_RE.match(ref or ""):
        raise HTTPException(400, detail=f"invalid {what}: {ref!r}")
    return ref


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, detail="admin required")

# ── Configuration ──
COMPOSE_PROJECT_NAME = os.environ.get("FORGEOS_COMPOSE_PROJECT", "forgeos")
DOCKER_COMPOSE_FILE = os.environ.get(
    "FORGEOS_COMPOSE_FILE", 
    "/opt/forgeos/docker-compose.yml"
)

# ── Helpers ──
def _run_docker(args: list, timeout: int = 30) -> dict:
    """Run docker command safely."""
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _run_compose(args: list, timeout: int = 60) -> dict:
    """Run docker-compose command safely."""
    try:
        # Try docker compose (v2) first, fallback to docker-compose (v1)
        for cmd in [["docker", "compose"], ["docker-compose"]]:
            try:
                result = subprocess.run(
                    cmd + args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**os.environ, "COMPOSE_PROJECT_NAME": COMPOSE_PROJECT_NAME}
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode
                }
            except FileNotFoundError:
                continue
        return {"success": False, "error": "docker compose not found"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════
# DOCKER CONTAINERS
# ═══════════════════════════════════════════════════════

@router.get("/containers")
async def list_containers(all: bool = Query(default=False)):
    """List Docker containers."""
    args = ["ps", "--format", "json"]
    if all:
        args.append("-a")
    
    result = _run_docker(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to list containers"))
    
    try:
        containers = json.loads(result["stdout"]) if result["stdout"] else []
        if isinstance(containers, dict):
            containers = [containers]
        return {"containers": containers}
    except json.JSONDecodeError:
        # Parse non-JSON output
        lines = result["stdout"].splitlines()
        return {"containers": [], "raw": lines}

@router.post("/containers/{container}/start")
async def start_container(container: str, user=Depends(verify_token)):
    _valid_ref(container, "container")
    """Start a container."""
    result = _run_docker(["start", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "started"}

@router.post("/containers/{container}/stop")
async def stop_container(container: str, user=Depends(verify_token)):
    _valid_ref(container, "container")
    """Stop a container."""
    result = _run_docker(["stop", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "stopped"}

@router.post("/containers/{container}/restart")
async def restart_container(container: str, user=Depends(verify_token)):
    _valid_ref(container, "container")
    """Restart a container."""
    result = _run_docker(["restart", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "restarted"}

@router.delete("/containers/{container}")
async def remove_container(container: str, force: bool = Query(default=False), user=Depends(verify_token)):
    _require_admin(user)
    _valid_ref(container, "container")
    """Remove a container."""
    args = ["rm", container]
    if force:
        args.insert(1, "-f")
    result = _run_docker(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "removed"}

@router.get("/containers/{container}/logs")
async def get_container_logs(container: str, tail: int = Query(default=100), user=Depends(verify_token)):
    _valid_ref(container, "container")
    """Get container logs."""
    result = _run_docker(["logs", f"--tail={tail}", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"container": container, "logs": result["stdout"]}

@router.post("/containers/{container}/exec")
async def exec_in_container(container: str, body: dict, user=Depends(verify_token)):
    _require_admin(user)
    _valid_ref(container, "container")
    """Execute command in container."""
    cmd = body.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="No command provided")
    
    result = _run_docker(["exec", container, "sh", "-c", cmd])
    return {
        "container": container,
        "command": cmd,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "success": result["success"]
    }

# ═══════════════════════════════════════════════════════
# DOCKER IMAGES
# ═══════════════════════════════════════════════════════

@router.get("/images")
async def list_images():
    """List Docker images."""
    result = _run_docker(["images", "--format", "json"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to list images"))
    
    try:
        images = json.loads(result["stdout"]) if result["stdout"] else []
        if isinstance(images, dict):
            images = [images]
        return {"images": images}
    except json.JSONDecodeError:
        return {"images": [], "raw": result["stdout"]}

@router.delete("/images/{image}")
async def remove_image(image: str, force: bool = Query(default=False), user=Depends(verify_token)):
    _require_admin(user)
    _valid_ref(image, "image")
    """Remove a Docker image."""
    args = ["rmi"]
    if force:
        args.append("-f")
    args.append(image)
    
    result = _run_docker(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "image": image, "action": "removed"}

# ═══════════════════════════════════════════════════════
# DOCKER PRUNE
# ═══════════════════════════════════════════════════════

@router.post("/prune/system")
async def prune_system(user=Depends(verify_token)):
    _require_admin(user)
    """Prune all unused Docker objects (containers, networks, images, volumes)."""
    result = _run_docker(["system", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/volumes")
async def prune_volumes(user=Depends(verify_token)):
    _require_admin(user)
    """Remove unused local volumes."""
    result = _run_docker(["volume", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/images")
async def prune_images(user=Depends(verify_token)):
    _require_admin(user)
    """Remove unused images."""
    result = _run_docker(["image", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/networks")
async def prune_networks(user=Depends(verify_token)):
    _require_admin(user)
    """Remove unused networks."""
    result = _run_docker(["network", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

# ═══════════════════════════════════════════════════════
# DOCKER COMPOSE
# ═══════════════════════════════════════════════════════

@router.get("/compose/services")
async def compose_ps():
    """List containers in compose project."""
    result = _run_compose(["ps", "--format", "json"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose ps failed"))
    
    try:
        services = json.loads(result["stdout"]) if result["stdout"] else []
        return {"services": services, "project": COMPOSE_PROJECT_NAME}
    except json.JSONDecodeError:
        return {"services": [], "raw": result["stdout"]}

@router.post("/compose/up")
async def compose_up(background_tasks: BackgroundTasks, detach: bool = Query(default=True)):
    """Start all services in docker-compose.yml."""
    args = ["up"]
    if detach:
        args.append("-d")
    
    # Run in background to avoid timeout
    def _up_task():
        _run_compose(args, timeout=300)
    
    background_tasks.add_task(_up_task)
    return {"ok": True, "action": "up", "detach": detach, "status": "starting"}

@router.post("/compose/down")
async def compose_down(volumes: bool = Query(default=False)):
    """Stop and remove containers, networks."""
    args = ["down"]
    if volumes:
        args.append("-v")
    
    result = _run_compose(args, timeout=120)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose down failed"))
    return {"ok": True, "action": "down", "output": result["stdout"]}

@router.post("/compose/stop")
async def compose_stop():
    """Stop all services."""
    result = _run_compose(["stop"], timeout=120)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose stop failed"))
    return {"ok": True, "action": "stop"}

@router.post("/compose/start")
async def compose_start():
    """Start all stopped services."""
    result = _run_compose(["start"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose start failed"))
    return {"ok": True, "action": "start"}

@router.post("/compose/restart")
async def compose_restart():
    """Restart all services."""
    result = _run_compose(["restart"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose restart failed"))
    return {"ok": True, "action": "restart"}

@router.get("/compose/logs")
async def compose_logs(service: Optional[str] = Query(default=None), tail: int = Query(default=100)):
    """Get logs for compose services."""
    args = ["logs", f"--tail={tail}"]
    if service:
        args.append(service)
    
    result = _run_compose(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose logs failed"))
    return {"logs": result["stdout"], "service": service}

@router.post("/compose/pull")
async def compose_pull():
    """Pull latest images."""
    result = _run_compose(["pull"], timeout=300)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose pull failed"))
    return {"ok": True, "action": "pull"}

@router.post("/compose/build")
async def compose_build():
    """Build or rebuild services."""
    result = _run_compose(["build"], timeout=600)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose build failed"))
    return {"ok": True, "action": "build"}

# ═══════════════════════════════════════════════════════
# DOCKER COMPOSE UI INTEGRATION
# ═══════════════════════════════════════════════════════

@router.get("/compose-file")
async def get_compose_file():
    """Get current docker-compose.yml content."""
    path = Path(DOCKER_COMPOSE_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail="docker-compose.yml not found")
    return {"content": path.read_text(), "path": DOCKER_COMPOSE_FILE}

@router.put("/compose-file")
async def update_compose_file(body: dict):
    """Update docker-compose.yml and optionally reload."""
    content = body.get("content", "")
    reload = body.get("reload", False)
    
    if not content:
        raise HTTPException(status_code=400, detail="No content provided")
    
    path = Path(DOCKER_COMPOSE_FILE)
    path.write_text(content)
    
    if reload:
        _run_compose(["up", "-d", "--force-recreate"])
    
    return {"ok": True, "path": DOCKER_COMPOSE_FILE, "reloaded": reload}

# ═══════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════

__all__ = ["router"]
