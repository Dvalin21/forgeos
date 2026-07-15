"""
ForgeOS Docker & LXC Management API
Full Docker Compose + LXC container lifecycle management.

Provides:
- Docker: ps, start, stop, restart, logs, exec, compose up/down/ps/restart
- Docker Compose: Full lifecycle (up -d, down, stop, start, restart, logs, build, pull)
- LXC: Create, start, stop, restart, destroy, snapshot, exec, info
- Prune: system prune, volume prune, network prune, image prune
"""

import logging
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
logger = logging.getLogger("forgeos-api")

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

# ── audit injection (same pattern as data_connect_api) ──
__audit_impl__ = None


def set_audit(fn) -> None:
    global __audit_impl__
    __audit_impl__ = fn


def _audit(who: str, action: str, status: str, detail: str | None = None) -> None:
    if __audit_impl__:
        try:
            __audit_impl__(who, action, status, detail)
        except Exception:
            pass

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

def _parse_ndjson(stdout: str) -> list:
    """docker/compose `--format json` emit NDJSON: one object PER LINE.
    Whole-blob json.loads only parses 0 or 1 objects — the bug class that
    made /containers silently render empty at >=2 (fixed there in 0036;
    /images and compose ps had the identical latent bug)."""
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass                    # ponytail: skip malformed line, keep rest
    return out


def _run_compose(args: list, timeout: int = 60, compose_file: str | None = None) -> dict:
    """Run docker compose against the ForgeOS compose file (or an explicit one)."""
    try:
        # Try docker compose (v2) first, fallback to docker-compose (v1)
        # -f is mandatory: the service's cwd has no compose file, so without
        # it every compose op silently targeted an empty project.
        for cmd in [["docker", "compose"], ["docker-compose"]]:
            try:
                result = subprocess.run(
                    cmd + ["-f", compose_file or DOCKER_COMPOSE_FILE] + args,
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
    """List Docker containers.

    Docker being absent or its daemon being down is a truthful STATE, not a
    server error — returning 500 for it produced a permanent log storm on
    boxes without Docker. Those states are 200 with available=false so the
    UI can render them; only unexpected failures stay 500.
    """
    args = ["ps", "--format", "json"]
    if all:
        args.append("-a")

    result = _run_docker(args)
    if not result["success"]:
        err = result.get("error", "")
        stderr = result.get("stderr", "")
        if "No such file or directory" in err:
            return {"containers": [], "available": False,
                    "reason": "Docker is not installed"}
        if "Cannot connect to the Docker daemon" in stderr:
            return {"containers": [], "available": False,
                    "reason": "Docker daemon is not running"}
        # genuine failure — keep the 500 but stop dropping the evidence
        raise HTTPException(status_code=500,
                            detail=err or stderr or "Failed to list containers")

    return {"containers": _parse_ndjson(result["stdout"]), "available": True}

@router.post("/containers/{container}/start")
async def start_container(container: str, user=Depends(verify_token)):
    """Start a container (admin — mutates docker state)."""
    _require_admin(user)
    _valid_ref(container, "container")
    result = _run_docker(["start", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "started"}

@router.post("/containers/{container}/stop")
async def stop_container(container: str, user=Depends(verify_token)):
    """Stop a container (admin — mutates docker state)."""
    _require_admin(user)
    _valid_ref(container, "container")
    result = _run_docker(["stop", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "stopped"}

@router.post("/containers/{container}/restart")
async def restart_container(container: str, user=Depends(verify_token)):
    """Restart a container (admin — mutates docker state)."""
    _require_admin(user)
    _valid_ref(container, "container")
    result = _run_docker(["restart", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": container, "action": "restarted"}

@router.delete("/containers/{container}")
async def remove_container(container: str, force: bool = Query(default=False), user=Depends(verify_token)):
    """Remove a container (admin, audited)."""
    _require_admin(user)
    _valid_ref(container, "container")
    args = ["rm", container]
    if force:
        args.insert(1, "-f")
    result = _run_docker(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    _audit(user["sub"], "docker.rm", "success", container)
    return {"ok": True, "container": container, "action": "removed"}

@router.get("/containers/{container}/logs")
async def get_container_logs(container: str, tail: int = Query(default=100), user=Depends(verify_token)):
    """Get container logs (read — any authenticated user). Docker writes
    container logs to BOTH streams; without stderr half the output vanished."""
    _valid_ref(container, "container")
    tail = max(1, min(tail, 5000))
    result = _run_docker(["logs", f"--tail={tail}", container])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    logs = "\n".join(x for x in (result["stdout"], result["stderr"]) if x)
    return {"container": container, "logs": logs}

@router.post("/containers/{container}/exec")
async def exec_in_container(container: str, body: dict, user=Depends(verify_token)):
    """Execute a command in a container (admin, audited)."""
    _require_admin(user)
    _valid_ref(container, "container")
    cmd = body.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="No command provided")
    
    result = _run_docker(["exec", container, "sh", "-c", cmd])
    _audit(user["sub"], "docker.exec", "success" if result["success"] else "failure",
           f"{container}: {cmd[:120]}")
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
    
    return {"images": _parse_ndjson(result["stdout"])}

@router.delete("/images/{image}")
async def remove_image(image: str, force: bool = Query(default=False), user=Depends(verify_token)):
    """Remove a Docker image (admin, audited)."""
    _require_admin(user)
    _valid_ref(image, "image")
    args = ["rmi"]
    if force:
        args.append("-f")
    args.append(image)
    
    result = _run_docker(args)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result.get("error"))
    _audit(user["sub"], "docker.rmi", "success", image)
    return {"ok": True, "image": image, "action": "removed"}

# ═══════════════════════════════════════════════════════
# DOCKER PRUNE
# ═══════════════════════════════════════════════════════

@router.post("/prune/system")
async def prune_system(user=Depends(verify_token)):
    """Prune all unused Docker objects (containers, networks, images, volumes)."""
    _require_admin(user)
    result = _run_docker(["system", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/volumes")
async def prune_volumes(user=Depends(verify_token)):
    """Remove unused local volumes."""
    _require_admin(user)
    result = _run_docker(["volume", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/images")
async def prune_images(user=Depends(verify_token)):
    """Remove unused images."""
    _require_admin(user)
    result = _run_docker(["image", "prune", "-f"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Prune failed"))
    return {"ok": True, "output": result["stdout"]}

@router.post("/prune/networks")
async def prune_networks(user=Depends(verify_token)):
    """Remove unused networks."""
    _require_admin(user)
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
    
    return {"services": _parse_ndjson(result["stdout"]),
            "project": COMPOSE_PROJECT_NAME}

@router.post("/compose/up")
async def compose_up(background_tasks: BackgroundTasks,
                     detach: bool = Query(default=True),
                     user=Depends(verify_token)):
    """Start all services (admin). Runs in the background — a first `up`
    pulls images and would blow any proxy timeout — but the result is now
    LOGGED instead of discarded (the silent-failure class)."""
    _require_admin(user)
    args = ["up"]
    if detach:
        args.append("-d")

    def _up_task():
        r = _run_compose(args, timeout=600)
        if not r["success"]:
            logger.error("compose up failed: %s",
                         r.get("stderr") or r.get("error", ""))

    background_tasks.add_task(_up_task)
    return {"ok": True, "action": "up", "detach": detach, "status": "starting"}

@router.post("/compose/down")
async def compose_down(volumes: bool = Query(default=False), user=Depends(verify_token)):
    _require_admin(user)
    """Stop and remove containers, networks."""
    args = ["down"]
    if volumes:
        args.append("-v")
    
    result = _run_compose(args, timeout=120)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose down failed"))
    _audit(user["sub"], "docker.compose_down", "success",
           "volumes removed" if volumes else "")
    return {"ok": True, "action": "down", "output": result["stdout"]}

@router.post("/compose/stop")
async def compose_stop(user=Depends(verify_token)):
    _require_admin(user)
    """Stop all services."""
    result = _run_compose(["stop"], timeout=120)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose stop failed"))
    return {"ok": True, "action": "stop"}

@router.post("/compose/start")
async def compose_start(user=Depends(verify_token)):
    _require_admin(user)
    """Start all stopped services."""
    result = _run_compose(["start"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose start failed"))
    return {"ok": True, "action": "start"}

@router.post("/compose/restart")
async def compose_restart(user=Depends(verify_token)):
    _require_admin(user)
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
async def compose_pull(user=Depends(verify_token)):
    _require_admin(user)
    """Pull latest images."""
    result = _run_compose(["pull"], timeout=300)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose pull failed"))
    return {"ok": True, "action": "pull"}

@router.post("/compose/build")
async def compose_build(user=Depends(verify_token)):
    _require_admin(user)
    """Build or rebuild services."""
    result = _run_compose(["build"], timeout=600)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Compose build failed"))
    return {"ok": True, "action": "build"}

# ═══════════════════════════════════════════════════════
# DOCKER COMPOSE UI INTEGRATION
# ═══════════════════════════════════════════════════════

@router.get("/compose-file")
async def get_compose_file(user=Depends(verify_token)):
    """Get current docker-compose.yml content (admin — may contain secrets)."""
    _require_admin(user)
    path = Path(DOCKER_COMPOSE_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail="docker-compose.yml not found")
    return {"content": path.read_text(), "path": DOCKER_COMPOSE_FILE}

@router.put("/compose-file")
async def update_compose_file(body: dict, user=Depends(verify_token)):
    """Update docker-compose.yml (admin, validated, atomic, audited).

    The old version wrote whatever it was sent straight over the live file —
    one bad paste and every compose op breaks with no way back."""
    _require_admin(user)
    content = body.get("content", "")
    reload = body.get("reload", False)

    if not content:
        raise HTTPException(status_code=400, detail="No content provided")

    path = Path(DOCKER_COMPOSE_FILE)
    tmp = path.with_suffix(".yml.new")
    tmp.write_text(content)
    check = _run_compose(["config", "-q"], compose_file=str(tmp))
    if not check["success"]:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400,
                            detail=f"compose file invalid: "
                                   f"{check.get('stderr') or check.get('error','')}"[:400])
    tmp.replace(path)                      # atomic on same filesystem
    _audit(user["sub"], "docker.compose_file", "success",
           f"{len(content)} bytes" + (", reloaded" if reload else ""))

    if reload:
        r = _run_compose(["up", "-d", "--force-recreate"], timeout=600)
        if not r["success"]:
            raise HTTPException(status_code=500,
                                detail=(r.get("stderr") or r.get("error",""))[:400])

    return {"ok": True, "path": DOCKER_COMPOSE_FILE, "reloaded": reload}

# ═══════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════

__all__ = ["router"]
