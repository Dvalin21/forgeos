"""ForgeOS LXC/Incus container management — SEPARATE from Docker.

Docker and LXC are distinct concerns with distinct pages; this module owns LXC
only. Runtime operations on live containers (start/stop/snapshot/exec/info) —
these are live ops, not declarative config, so they shell out to `lxc` and read
current state (the right model for runtime control).

Hardened per trust-boundary rules:
  - container/snapshot names are validated before they reach `lxc`, so a name
    like "-foo" or "a;b" can't become a flag or injection (argument injection
    is real even without shell=True).
  - destructive / code-exec ops (destroy, exec, snapshot) require admin.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Depends, Query

from forgeos_auth import verify_token

router = APIRouter(prefix="/api/lxc", tags=["LXC / Incus Management"],
                   dependencies=[Depends(verify_token)])

# Injected by the main module (audit logger).
_audit: Optional[Callable[..., None]] = None


def set_helpers(audit: Callable[..., None]) -> None:
    global _audit
    _audit = audit


# --- trust boundary: validate names before they reach the lxc CLI ----------

_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,62}\Z")


def _valid_name(name: str) -> str:
    """Reject anything that isn't a safe LXC container/snapshot name. Prevents
    argument injection (leading '-' becoming a flag) and shell metacharacters.
    """
    if not _NAME_RE.match(name or ""):
        raise HTTPException(400, detail=f"invalid container name: {name!r}")
    return name


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, detail="admin required")


def _run_lxc(args: list, timeout: int = 30) -> dict:
    """Run an lxc command via argv (never shell=True)."""
    try:
        result = subprocess.run(["lxc"] + args, capture_output=True,
                                text=True, timeout=timeout)
        return {"success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode}
    except FileNotFoundError:
        raise HTTPException(503, detail="lxc is not installed on this system")
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "command timed out"}


@router.get("/containers")
async def list_lxc_containers(user=Depends(verify_token)):
    result = _run_lxc(["list", "--format=json"])
    if not result["success"]:
        raise HTTPException(500, detail=result.get("error") or result.get("stderr")
                            or "failed to list LXC containers")
    try:
        return {"containers": json.loads(result["stdout"]) if result["stdout"] else []}
    except json.JSONDecodeError:
        containers = []
        for line in result["stdout"].splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                containers.append({"name": parts[0], "state": parts[1],
                                   "ipv4": parts[2], "ipv6": parts[3]})
        return {"containers": containers}


@router.post("/containers/{name}/start")
async def start_lxc_container(name: str, user=Depends(verify_token)):
    _valid_name(name)
    result = _run_lxc(["start", name])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": name, "action": "started"}


@router.post("/containers/{name}/stop")
async def stop_lxc_container(name: str, user=Depends(verify_token)):
    _valid_name(name)
    result = _run_lxc(["stop", name])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": name, "action": "stopped"}


@router.post("/containers/{name}/restart")
async def restart_lxc_container(name: str, user=Depends(verify_token)):
    _valid_name(name)
    result = _run_lxc(["restart", name])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": name, "action": "restarted"}


@router.post("/containers/{name}/destroy")
async def destroy_lxc_container(name: str, user=Depends(verify_token)):
    _require_admin(user)
    _valid_name(name)
    result = _run_lxc(["delete", name, "--force"])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    if _audit:
        _audit(user["sub"], "lxc.destroy", "success", f"LXC container '{name}' destroyed")
    return {"ok": True, "container": name, "action": "destroyed"}


@router.post("/containers/{name}/snapshot")
async def snapshot_lxc_container(name: str, snapshot_name: str = Query(...),
                                 user=Depends(verify_token)):
    _require_admin(user)
    _valid_name(name)
    _valid_name(snapshot_name)
    result = _run_lxc(["snapshot", name, snapshot_name])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    return {"ok": True, "container": name, "snapshot": snapshot_name}


@router.post("/containers/{name}/exec")
async def exec_in_lxc_container(name: str, body: dict, user=Depends(verify_token)):
    # exec is arbitrary in-container code execution by design — admin only,
    # name validated. ponytail: the command itself is intentionally arbitrary
    # (that's what exec is); we gate WHO can call it and validate the target.
    _require_admin(user)
    _valid_name(name)
    cmd = body.get("command", "")
    if not cmd:
        raise HTTPException(400, detail="no command provided")
    result = _run_lxc(["exec", name, "--", "sh", "-c", cmd])
    if _audit:
        _audit(user["sub"], "lxc.exec", "success", f"exec in LXC '{name}'")
    return {"container": name, "command": cmd, "stdout": result["stdout"],
            "stderr": result["stderr"], "success": result["success"]}


@router.get("/containers/{name}/info")
async def get_lxc_container_info(name: str, user=Depends(verify_token)):
    _valid_name(name)
    result = _run_lxc(["info", name])
    if not result["success"]:
        raise HTTPException(500, detail=result["stderr"] or result.get("error"))
    return {"container": name, "info": result["stdout"]}
