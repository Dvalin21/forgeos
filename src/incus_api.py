"""ForgeOS — Incus API surface.

Incus manages system containers and virtual machines. This module is the
ForgeOS web API over the local `incus` CLI.

Why the CLI and not the REST API: Incus listens on /var/lib/incus/unix.socket.
A browser cannot reach a Unix socket, and reaching it over TLS instead would
mean exposing :8443 and putting a client certificate in the browser — exactly
the ceremony ForgeOS exists to remove. The API already owns the box, so it
shells out to `incus` locally and the browser talks only to ForgeOS.

Instances are NOT stored in the ForgeOS config DB. Incus is the source of
truth for instances (exactly as Docker is for containers); the config DB only
carries Incus *settings* (see forgeos_config.IncusConfig).

Verified against Incus 6.0.4 on Debian 13 before this was written:
  incus launch <image> <name> --config limits.memory=... --config limits.cpu=...
  incus list --format json      -> name/status/type/config/state
  incus exec <name> -- sh -c    -> stdout
Mount matters: `incus exec <name> --` (double dash) stops Incus from parsing
the guest command's own flags.

Hardened per the trust-boundary rules:
  - instance/snapshot names are validated before they reach the CLI, so a name
    like "-foo" or "a;b" cannot become a flag or an injection (argument
    injection is real even without shell=True).
  - destructive / code-exec ops (delete, exec, snapshot) require admin.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from forgeos_auth import verify_token
import forgeos_config as fc

router = APIRouter(prefix="/api/incus", tags=["Incus Management"],
                   dependencies=[Depends(verify_token)])

_audit: Optional[Callable[..., None]] = None

# CREATE pulls an image over the network and can run for minutes.
_CREATE_TIMEOUT = 900


def set_helpers(audit: Callable[..., None]) -> None:
    global _audit
    _audit = audit


# ── trust boundary ──────────────────────────────────────────────────────────
_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,62}\Z")


def _valid_name(name: str) -> str:
    """Reject anything that isn't a safe Incus instance/snapshot name.
    Prevents a leading '-' becoming a CLI flag and blocks shell metacharacters."""
    if not _NAME_RE.match(name or ""):
        raise HTTPException(400, detail=f"invalid instance name: {name!r}")
    return name


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, detail="admin required")


def _installed() -> bool:
    return shutil.which("incus") is not None


def _require_incus() -> None:
    if not _installed():
        raise HTTPException(503, detail="incus is not installed on this system")


def _forgeos_pool() -> str:
    """The ForgeOS pool mountpoint — the only place user data may live.
    Incus storage lives ON it (<pool>/containers, <pool>/vms), never on the
    OS disk's /var/lib/incus."""
    try:
        import forgeos_config as _fc
        pools = [p.resolved_mountpoint() for p in _fc.load().storage.pools]
    except Exception:
        pools = []
    if not pools:
        raise HTTPException(
            409, "No storage pool yet — create one first; containers and VMs "
                 "live on the pool, not the OS disk.")
    return pools[0]


def _ensure_storage_pool(kind: str) -> str:
    """Create the Incus dir storage pool for `kind` on the ForgeOS pool if
    missing, and return its name. Idempotent; never touches /var/lib/incus."""
    pool_root = _forgeos_pool()
    name = f"forgeos-{kind}"
    src = f"{pool_root}/{kind}"
    Path(src).mkdir(parents=True, exist_ok=True)
    res = _run_json(["storage", "list", "--format", "json"], timeout=30) or []
    existing = {p.get("name") for p in res if isinstance(p, dict)}
    if name not in existing:
        r = _run(["storage", "create", name, "dir", f"source={src}"], timeout=60)
        if not r["success"]:
            raise HTTPException(400, detail=r.get("stderr") or
                                f"could not create Incus pool {name}")
    return name


def _run(args: list[str], timeout: int = 60) -> dict:
    """Run an incus command via argv (never shell=True)."""
    try:
        r = subprocess.run(["incus"] + args, capture_output=True,
                           text=True, timeout=timeout)
        return {"success": r.returncode == 0, "stdout": r.stdout.strip(),
                "stderr": r.stderr.strip(), "returncode": r.returncode}
    except FileNotFoundError:
        raise HTTPException(503, detail="incus is not installed on this system")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, detail="incus command timed out")


def _run_json(args: list[str], timeout: int = 60):
    res = _run(args, timeout=timeout)
    if not res["success"]:
        raise HTTPException(500, detail=res.get("stderr") or res.get("stdout")
                            or "incus command failed")
    if not res["stdout"]:
        return []
    try:
        return json.loads(res["stdout"])
    except json.JSONDecodeError:
        raise HTTPException(500, detail="could not parse incus output")


# ── view shaping ───────────────────────────────────────────────────────────
def _bytes_human(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


_SIZE_RE = re.compile(r"\A([0-9]{1,7})\s*([KMGT]?)i?B?\Z", re.IGNORECASE)
_SIZE_MULT = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}


def _parse_size(v) -> int:
    """Incus reports a volume's size as a HUMAN string ("20GiB"), not an
    integer. int("20GiB") raises, which previously made every sized disk read
    as "unlimited". Parse it; return 0 for absent/meaningless."""
    if isinstance(v, (int, float)):
        return int(v)
    m = _SIZE_RE.match(str(v or "").strip())
    if not m:
        return 0
    return int(m.group(1)) * _SIZE_MULT[m.group(2).upper()]


def _view(inst: dict) -> dict:
    """One Incus instance -> the shape the UI renders. Everything here is read
    from Incus, never from ForgeOS config."""
    cfg = inst.get("config") or {}
    state = inst.get("state") or {}
    mem = state.get("memory") or {}
    net = (state.get("network") or {})
    addrs = []
    for dev in net.values():
        for a in (dev.get("addresses") or []):
            if a.get("family") == "inet" and a.get("scope") == "global":
                addrs.append(a.get("address", ""))
    disk = 0
    for d in (inst.get("expanded_devices") or {}).values():
        if d.get("type") == "disk" and d.get("path") == "/":
            disk = _parse_size(d.get("size"))
            break
    return {
        "name": inst.get("name", ""),
        "status": (inst.get("status") or "Unknown"),
        "type": inst.get("type") or "container",
        "image": (cfg.get("image.description") or cfg.get("image.os", "")
                  or cfg.get("image.release", "")),
        "image_alias": cfg.get("image.alias", "") or cfg.get("image.release", ""),
        "ipv4": addrs[0] if addrs else "",
        "cpu_limit": cfg.get("limits.cpu", "") or "",
        "memory_limit": cfg.get("limits.memory", "") or "",
        "memory_bytes": mem.get("usage"),
        "memory_display": _bytes_human(mem.get("usage")),
        "disk_bytes": disk or None,
        "disk_display": _bytes_human(disk) if disk else "unlimited",
        "created": inst.get("created_at", "") or "",
        "snapshots": len(inst.get("snapshots") or []),
    }


# ── state ──────────────────────────────────────────────────────────────────
@router.get("/status")
async def incus_status(user=Depends(verify_token)):
    """Is Incus installed, initialised and running? Drives the install gate."""
    if not _installed():
        return {"installed": False, "initialised": False, "running": False,
                "version": ""}
    ver = _run(["version"], timeout=15)
    cfg = fc.load()
    pools = [p for p in (_run(["storage", "list", "--format", "csv", "-c", "n"],
                             timeout=20)["stdout"] or "").splitlines() if p.strip()]
    return {
        "installed": True,
        "initialised": bool(pools),
        "running": bool(ver["success"]) and bool(pools),
        "version": (ver["stdout"] or "").splitlines()[0] if ver["stdout"] else "",
        "bridge": cfg.incus.bridge,
        "storage_pool": cfg.incus.storage_pool,
        "storage_pools": pools,
    }


# ── instances ──────────────────────────────────────────────────────────────
@router.get("/instances")
async def list_instances(user=Depends(verify_token)):
    _require_incus()
    raw = _run_json(["list", "--format", "json"])
    return {"instances": [_view(i) for i in raw]}


def _instance_view(name: str) -> dict:
    """Sync helper: read one instance and return the UI view.

    Deliberately not an endpoint function. The start/stop/restart/update
    handlers all want to return the refreshed instance, and `return
    get_instance(...)` from an async endpoint yields a coroutine that FastAPI
    does not await — it tries to serialise the coroutine instead."""
    raw = _run_json(["list", name, "--format", "json"])
    if not raw:
        raise HTTPException(404, detail=f"no such instance: {name}")
    return _view(raw[0])


@router.get("/instances/{name}")
async def get_instance(name: str, user=Depends(verify_token)):
    _require_incus()
    _valid_name(name)
    return _instance_view(name)


@router.post("/instances")
async def create_instance(body: dict, user=Depends(verify_token)):
    """Create and start an instance.

    Hardware values are taken EXACTLY as supplied. Presets are a UI
    convenience that fills these fields in editable form — the API never
    clamps or substitutes them, because a user who typed 3GB means 3GB.
    """
    _require_admin(user)
    _require_incus()
    name = _valid_name(str(body.get("name", "")).strip())
    image = str(body.get("image", "")).strip()
    if not image:
        raise HTTPException(400, detail="image is required")
    vtype = str(body.get("type", "container")).strip()
    if vtype not in ("container", "virtual-machine"):
        raise HTTPException(400, detail="type must be 'container' or 'virtual-machine'")

    # Validate every field BEFORE touching the CLI. Half the point of
    # validating at all is that a typo is a 400 with a readable message rather
    # than an opaque daemon error minutes later.
    cpu = str(body.get("cpu_limit", "")).strip()
    if cpu and not re.fullmatch(r"[0-9]{1,4}", cpu):
        raise HTTPException(400, detail="cpu_limit must be a whole number of cores")

    mem = str(body.get("memory", "")).strip()
    if mem and not re.fullmatch(r"[0-9]{1,5}([KMGT]i?B?|[KMGT])?", mem):
        raise HTTPException(400, detail="memory must look like 2GiB or 512MB")

    disk = str(body.get("disk", "")).strip()
    if disk and not re.fullmatch(r"[0-9]{1,6}([KMGT]i?B?|[KMGT])?", disk):
        raise HTTPException(400, detail="disk must look like 20GiB or 500MB")

    res = _run(["list", name, "--format", "csv", "-c", "n"], timeout=30)
    if res["success"] and res["stdout"].strip():
        raise HTTPException(409, detail=f"an instance called {name} already exists")

    # Storage lives on the ForgeOS pool: containers in <pool>/containers,
    # VMs in <pool>/vms. Creating the Incus dir pool here (idempotent) is
    # what keeps instance data off the OS disk. Also the pool gate: no
    # ForgeOS pool -> nothing can be created (see _forgeos_pool).
    pool = _ensure_storage_pool("vms" if vtype == "virtual-machine"
                                else "containers")

    args = ["launch", image, name, "-s", pool]
    if vtype == "virtual-machine":
        args.append("--vm")

    # Resource limits: pass through what the user typed. Each --config is a
    # separate argv element, so a value cannot break out into another flag.
    if cpu:
        args += ["--config", f"limits.cpu={cpu}"]
    if mem:
        args += ["--config", f"limits.memory={mem}"]
    if disk:
        args += ["--device", f"{name},root,disk,path=/,size={disk},pool={pool}"]

    profile = str(body.get("profile", "")).strip()
    if profile:
        args += ["--profile", profile]

    # Note: Incus 6.0.4 has no "create but don't start" flag (verified against
    # `incus launch --help` — there is no --instance-only). Every instance is
    # created running, which is also what the UI wants: create, then watch it
    # boot.

    res = _run(args, timeout=_CREATE_TIMEOUT)
    if not res["success"]:
        raise HTTPException(400, detail=res.get("stderr") or res.get("stdout")
                            or "incus could not create the instance")
    if _audit:
        _audit(user["sub"], "incus.instance.create", "success",
               f"{name} ({vtype}) from {image}")
    return _instance_view(name)


@router.post("/instances/{name}/start")
async def start_instance(name: str, user=Depends(verify_token)):
    _require_incus()
    _valid_name(name)
    res = _run(["start", name], timeout=180)
    if not res["success"]:
        raise HTTPException(500, detail=res.get("stderr") or "could not start")
    return _instance_view(name)


@router.post("/instances/{name}/stop")
async def stop_instance(name: str, user=Depends(verify_token)):
    _require_incus()
    _valid_name(name)
    res = _run(["stop", name], timeout=180)
    if not res["success"]:
        raise HTTPException(500, detail=res.get("stderr") or "could not stop")
    return _instance_view(name)


@router.post("/instances/{name}/restart")
async def restart_instance(name: str, user=Depends(verify_token)):
    _require_incus()
    _valid_name(name)
    res = _run(["restart", name], timeout=180)
    if not res["success"]:
        raise HTTPException(500, detail=res.get("stderr") or "could not restart")
    return _instance_view(name)


@router.post("/instances/{name}/update")
async def update_instance(name: str, body: dict, user=Depends(verify_token)):
    """Change the limits of an EXISTING instance.

    Same pass-through discipline as create: the value the user typed is the
    value Incus gets. Incus applies a memory limit live and refuses to lower
    one below current usage, so a rejection surfaces as a 400 with its own
    message rather than being silently clamped.
    """
    _require_admin(user)
    _require_incus()
    _valid_name(name)

    cpu = body.get("cpu_limit")
    if cpu is not None:
        cpu = str(cpu).strip()
        if cpu and not re.fullmatch(r"[0-9]{1,4}", cpu):
            raise HTTPException(400, detail="cpu_limit must be a whole number of cores")
        key = "limits.cpu"
        res = _run(["config", "set", name, key, cpu] if cpu else
                   ["config", "unset", name, key], timeout=60)
        if not res["success"]:
            raise HTTPException(400, detail=res.get("stderr") or "could not set CPU limit")

    mem = body.get("memory")
    if mem is not None:
        mem = str(mem).strip()
        if mem and not re.fullmatch(r"[0-9]{1,5}([KMGT]i?B?|[KMGT])?", mem):
            raise HTTPException(400, detail="memory must look like 2GiB or 512MB")
        key = "limits.memory"
        res = _run(["config", "set", name, key, mem] if mem else
                   ["config", "unset", name, key], timeout=60)
        if not res["success"]:
            err = res.get("stderr") or ""
            # Incus refuses to set a memory limit below what the running
            # instance is already using, and reports it only as a cgroup
            # error (verified on the box). Say the useful thing instead.
            if "cgroup" in err.lower():
                raise HTTPException(
                    400,
                    detail="That is smaller than the memory this instance is "
                           "currently using. Stop it first, or choose a "
                           "larger size.")
            raise HTTPException(400, detail=err or "could not set memory limit")

    if _audit:
        _audit(user["sub"], "incus.instance.update", "success", name)
    return _instance_view(name)


@router.post("/instances/{name}/snapshot")
async def snapshot_instance(name: str, body: dict, user=Depends(verify_token)):
    _require_admin(user)
    _require_incus()
    _valid_name(name)
    snap = _valid_name(str(body.get("name", "")).strip())
    res = _run(["snapshot", "create", name, snap], timeout=300)
    if not res["success"]:
        raise HTTPException(400, detail=res.get("stderr") or "snapshot failed")
    if _audit:
        _audit(user["sub"], "incus.snapshot.create", "success", f"{name}/{snap}")
    return {"ok": True, "instance": name, "snapshot": snap}


@router.post("/instances/{name}/exec")
async def exec_instance(name: str, body: dict, user=Depends(verify_token)):
    """Run a command inside an instance. Admin only, target validated; the
    command is intentionally arbitrary — that is what exec is."""
    _require_admin(user)
    _require_incus()
    _valid_name(name)
    cmd = str(body.get("command", "")).strip()
    if not cmd:
        raise HTTPException(400, detail="no command provided")
    # `--` stops Incus parsing guest flags. sh -c runs the string as a shell
    # command, which is the point; argv keeps the host side injection-free.
    res = _run(["exec", name, "--", "sh", "-c", cmd], timeout=120)
    if _audit:
        _audit(user["sub"], "incus.exec", "success", name)
    return {"instance": name, "command": cmd, "stdout": res["stdout"],
            "stderr": res["stderr"], "success": res["success"]}


@router.delete("/instances/{name}")
async def delete_instance(name: str, user=Depends(verify_token)):
    """Delete an instance. force=true is required because Incus refuses to
    remove a running instance otherwise, and the UI must be explicit."""
    _require_admin(user)
    _require_incus()
    _valid_name(name)
    res = _run(["delete", name, "--force"], timeout=300)
    if not res["success"]:
        err = res.get("stderr") or ""
        if "not found" in err.lower():
            raise HTTPException(404, detail=f"no such instance: {name}")
        raise HTTPException(400, detail=err or "could not delete")
    if _audit:
        _audit(user["sub"], "incus.instance.delete", "success", name)
    return {"ok": True, "deleted": name}