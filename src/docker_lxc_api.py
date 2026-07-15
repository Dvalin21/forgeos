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
import threading
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

# ── update / run / wipe lifecycle (0040) ────────────────────────────────────
# In-flight image pulls. In-memory is correct here: forgeos-api is a single
# uvicorn process by design; a pull surviving an API restart just means the
# next poll re-checks the image and finds it present or re-pulls.
_PULLING: set = set()
_PULL_LOCK = threading.Lock()


def _image_ref_valid(ref: str) -> bool:
    """Registry refs only; blocks argument injection (leading '-') and shell
    metacharacters. Admin+audit is the trust boundary; this stops mistakes."""
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._\-/:@]*", ref or ""))


def _inspect(kind: str, ref: str) -> dict | None:
    """docker {container|image} inspect -> first object, or None."""
    r = _run_docker([kind, "inspect", ref])
    if not r["success"]:
        return None
    try:
        out = json.loads(r["stdout"])
        return out[0] if out else None
    except (json.JSONDecodeError, IndexError):
        return None


def _host_arch() -> str:
    import platform
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(
        platform.machine(), platform.machine())


def _remote_config_digest(image: str) -> str | None:
    """Remote image's CONFIG digest via `docker manifest inspect -v` — no
    pull. A local docker image ID IS its config digest, so equality with
    `docker image inspect .Id` means up-to-date. Experimental-CLI is enabled
    by default since Docker 20.10 (Debian 13 ships 26.x+)."""
    r = _run_docker(["manifest", "inspect", "-v", image], timeout=20)
    if not r["success"]:
        return None
    try:
        data = json.loads(r["stdout"])
    except json.JSONDecodeError:
        return None
    entries = data if isinstance(data, list) else [data]
    arch = _host_arch()

    def cfg_digest(entry: dict) -> str | None:
        # key differs by manifest flavor (SchemaV2Manifest / OCIManifest…);
        # hunt for any sub-object shaped like {config: {digest: ...}}
        for v in entry.values():
            if isinstance(v, dict) and isinstance(v.get("config"), dict):
                return v["config"].get("digest")
        return None

    match = None
    for e in entries:
        plat = e.get("Descriptor", {}).get("platform") or e.get("Platform") or {}
        if plat.get("os") == "linux" and plat.get("architecture") == arch:
            match = e
            break
    return cfg_digest(match or entries[0])


def _image_local_id(image: str) -> str | None:
    info = _inspect("image", image)
    return info.get("Id") if info else None


def _start_pull(image: str, background_tasks: BackgroundTasks) -> None:
    with _PULL_LOCK:
        if image in _PULLING:
            return
        _PULLING.add(image)

    def _task():
        try:
            r = _run_docker(["pull", image], timeout=1800)
            if not r["success"]:
                logger.error("docker pull %s failed: %s", image,
                             r.get("stderr") or r.get("error", ""))
        finally:
            with _PULL_LOCK:
                _PULLING.discard(image)

    background_tasks.add_task(_task)


def _pull_202(image: str) -> JSONResponse:
    return JSONResponse(status_code=202, content={
        "pulling": True, "image": image,
        "detail": f"Pulling {image} — poll this endpoint until it returns 200"})


@router.get("/update-check")
async def update_check(user=Depends(verify_token)):
    """Compare each running container's image (its ID == config digest)
    against the registry's current config digest. No pulls; one small
    manifest fetch per unique image, fetched concurrently."""
    ps = _run_docker(["ps", "--format", "json"])
    if not ps["success"]:
        raise HTTPException(status_code=500,
                            detail=ps.get("error") or ps.get("stderr", ""))
    rows = _parse_ndjson(ps["stdout"])

    import asyncio
    loop = asyncio.get_event_loop()
    images = sorted({r.get("Image", "") for r in rows if r.get("Image")})
    digests = dict(zip(images, await asyncio.gather(
        *(loop.run_in_executor(None, _remote_config_digest, i) for i in images))))

    out = []
    for r in rows:
        name, image = r.get("Names", ""), r.get("Image", "")
        info = _inspect("container", name)
        running_id = (info or {}).get("Image")
        remote = digests.get(image)
        out.append({
            "name": name, "image": image,
            # None = could not determine (private image, rate limit, offline)
            "update_available": (None if not remote or not running_id
                                 else remote != running_id),
        })
    return {"containers": out}


@router.post("/containers/{container}/update")
async def update_container(container: str, background_tasks: BackgroundTasks,
                           user=Depends(verify_token)):
    """Pull the container's image and recreate it with its existing config
    (admin, audited). 202 while the pull runs — poll to completion. Rollback:
    the old container is renamed, not removed, until the new one starts."""
    _require_admin(user)
    _valid_ref(container, "container")
    info = _inspect("container", container)
    if info is None:
        raise HTTPException(status_code=404, detail=f"no container {container!r}")
    labels = (info.get("Config", {}) or {}).get("Labels") or {}
    if "com.docker.compose.project" in labels:
        return {"ok": False, "compose_managed": True,
                "hint": "manage via `docker compose pull && docker compose up -d`"}

    image = (info.get("Config", {}) or {}).get("Image", "")
    if not image or image.startswith("sha256:"):
        raise HTTPException(status_code=409,
                            detail="container runs a pinned image ID — nothing to update to")

    with _PULL_LOCK:
        pulling = image in _PULLING
    if pulling:
        return _pull_202(image)

    local_id = _image_local_id(image)
    remote = _remote_config_digest(image)
    if remote and local_id != remote:
        _start_pull(image, background_tasks)
        return _pull_202(image)

    if local_id is None:
        _start_pull(image, background_tasks)
        return _pull_202(image)

    if info.get("Image") == local_id:
        return {"ok": True, "updated": False, "detail": "already up to date"}

    _recreate_from(info, container, image)
    _audit(user["sub"], "docker.update", "success", f"{container} -> {image}")
    return {"ok": True, "updated": True, "container": container}


def _recreate_from(info: dict, container: str, image: str) -> None:
    """Stop + rename old, run new from `info`'s config; rollback on failure.
    Preserves env, ports, binds, named-volume mounts, restart policy and
    network mode. Exotic HostConfig (devices, caps) is NOT carried — the
    rollback path exists precisely so that failure is non-destructive."""
    cfg = info.get("Config", {}) or {}
    host = info.get("HostConfig", {}) or {}
    img = _inspect("image", image) or {}
    img_cfg = img.get("Config", {}) or {}

    args = ["run", "-d", "--name", container]
    rp = (host.get("RestartPolicy") or {}).get("Name") or ""
    if rp and rp != "no":
        mrc = (host.get("RestartPolicy") or {}).get("MaximumRetryCount") or 0
        args += ["--restart", rp + (f":{mrc}" if rp == "on-failure" and mrc else "")]
    nm = host.get("NetworkMode", "")
    if nm and nm not in ("default", "bridge"):
        args += ["--network", nm]
    for env in cfg.get("Env") or []:
        args += ["-e", env]
    for cport, bindings in (host.get("PortBindings") or {}).items():
        for b in bindings or []:
            hp = b.get("HostPort", "")
            hip = b.get("HostIp", "")
            if hp:
                args += ["-p", (f"{hip}:" if hip else "") + f"{hp}:{cport}"]
    for bind in host.get("Binds") or []:
        args += ["-v", bind]
    for m in info.get("Mounts") or []:
        if m.get("Type") == "volume" and m.get("Name") and m.get("Destination"):
            spec = f"{m['Name']}:{m['Destination']}"
            if not any(a.startswith(f"{m['Name']}:") for a in args):
                args += ["-v", spec]
    if cfg.get("Entrypoint") and cfg.get("Entrypoint") != img_cfg.get("Entrypoint"):
        ep = cfg["Entrypoint"]
        args += ["--entrypoint", ep[0] if isinstance(ep, list) else str(ep)]
    args.append(image)
    if cfg.get("Cmd") and cfg.get("Cmd") != img_cfg.get("Cmd"):
        cmd = cfg["Cmd"]
        args += cmd if isinstance(cmd, list) else [str(cmd)]

    was_running = (info.get("State") or {}).get("Running", False)
    old = f"{container}-forgeos-old"
    _run_docker(["stop", container], timeout=60)
    r = _run_docker(["rename", container, old])
    if not r["success"]:
        raise HTTPException(status_code=500, detail=f"rename failed: {r.get('stderr','')}"[:300])
    r = _run_docker(args, timeout=120)
    if not r["success"]:
        _run_docker(["rm", "-f", container])          # partial new, if any
        _run_docker(["rename", old, container])
        if was_running:
            _run_docker(["start", container])
        raise HTTPException(status_code=500,
                            detail=f"recreate failed, rolled back: "
                                   f"{r.get('stderr') or r.get('error','')}"[:300])
    _run_docker(["rm", old])


@router.post("/wipe")
async def wipe_container(body: dict, user=Depends(verify_token)):
    """Remove a container, its anonymous volumes (`rm -v`), and its image
    (best effort — a shared image stays). Admin, audited."""
    _require_admin(user)
    name = str(body.get("name", "")).strip()
    _valid_ref(name, "container")
    info = _inspect("container", name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"no container {name!r}")
    image_id = info.get("Image", "")
    _run_docker(["stop", name], timeout=60)
    r = _run_docker(["rm", "-v", name])
    if not r["success"]:
        raise HTTPException(status_code=500,
                            detail=(r.get("stderr") or r.get("error", ""))[:300])
    img_removed = False
    if image_id:
        img_removed = _run_docker(["rmi", image_id])["success"]
    _audit(user["sub"], "docker.wipe", "success",
           f"{name} (image {'removed' if img_removed else 'kept'})")
    return {"ok": True, "container": name, "image_removed": img_removed}


@router.post("/run")
async def run_container(body: dict, background_tasks: BackgroundTasks,
                        user=Depends(verify_token)):
    """Create a container (admin, audited, validated). 202 while the image
    pulls — poll to completion, then the retry creates the container."""
    _require_admin(user)
    name = str(body.get("name", "")).strip()
    image = str(body.get("image", "")).strip()
    _valid_ref(name, "container")
    if not _image_ref_valid(image):
        raise HTTPException(status_code=400, detail=f"invalid image reference {image!r}")
    if _inspect("container", name) is not None:
        raise HTTPException(status_code=409, detail=f"container {name!r} already exists")

    args = ["run", "-d", "--name", name]
    restart = str(body.get("restart", "")).strip()
    if restart and restart != "no":
        if restart not in ("always", "unless-stopped", "on-failure"):
            raise HTTPException(status_code=400, detail=f"invalid restart policy {restart!r}")
        args += ["--restart", restart]
    for p in body.get("ports") or []:
        if not re.fullmatch(r"\d{1,5}:\d{1,5}(/(tcp|udp))?", str(p)):
            raise HTTPException(status_code=400, detail=f"invalid port mapping {p!r}")
        args += ["-p", str(p)]
    for v in body.get("volumes") or []:
        parts = str(v).split(":")
        if len(parts) < 2 or not (parts[0].startswith("/")
                                  or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", parts[0])) \
                or not parts[1].startswith("/") \
                or (len(parts) > 2 and parts[2] not in ("ro", "rw")):
            raise HTTPException(status_code=400, detail=f"invalid volume {v!r}")
        args += ["-v", str(v)]
    for e in body.get("env") or []:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", str(e), re.S):
            raise HTTPException(status_code=400, detail=f"invalid env entry {e!r}")
        args += ["-e", str(e)]
    for n in body.get("networks") or []:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", str(n)):
            raise HTTPException(status_code=400, detail=f"invalid network {n!r}")
        args += ["--network", str(n)]
    for k, v in (body.get("labels") or {}).items():
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", str(k)):
            raise HTTPException(status_code=400, detail=f"invalid label key {k!r}")
        args += ["--label", f"{k}={v}"]
    if body.get("workdir"):
        wd = str(body["workdir"])
        if not wd.startswith("/"):
            raise HTTPException(status_code=400, detail="workdir must be absolute")
        args += ["-w", wd]
    if body.get("cpu_limit"):
        args += ["--cpus", str(body["cpu_limit"])]
    if body.get("mem_limit"):
        args += ["--memory", str(body["mem_limit"])]
    hc = body.get("healthcheck") or {}
    if hc.get("test"):
        args += ["--health-cmd", str(hc["test"]),
                 "--health-interval", str(hc.get("interval", "30s")),
                 "--health-retries", str(int(hc.get("retries", 3)))]
    if body.get("entrypoint"):
        args += ["--entrypoint", str(body["entrypoint"])]
    args.append(image)
    if body.get("command"):
        import shlex
        args += shlex.split(str(body["command"]))

    with _PULL_LOCK:
        pulling = image in _PULLING
    if pulling:
        return _pull_202(image)
    if _image_local_id(image) is None:
        _start_pull(image, background_tasks)
        return _pull_202(image)

    r = _run_docker(args, timeout=120)
    if not r["success"]:
        raise HTTPException(status_code=500,
                            detail=(r.get("stderr") or r.get("error", ""))[:300])
    _audit(user["sub"], "docker.run", "success", f"{name} ({image})")
    return {"ok": True, "container": name}


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
