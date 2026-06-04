"""ForgeOS — Backup API surface.

Mounts under the existing FastAPI app via:

    from backup_api import router as backup_router, set_helpers as set_backup_helpers
    set_backup_helpers(
        start_task=_start_task,
        audit=_audit,
        backup_jobs=_backup_jobs,
        jobs_lock=_jobs_lock,
        background_tasks=_background_tasks,
        task_lock=_task_lock,
        persist_jobs=_persist_jobs,
        update_job_from_task=_update_job_from_task,
    )
    app.include_router(backup_router)

Routes (16): borg/restic/rclone status + create/snapshot/sync/list,
backup-jobs CRUD + run-now, task query.

Helpers + state are injected by the main module because the
background-task and scheduler infrastructure must hook into the
FastAPI lifespan (which lives in the main module).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_start_task: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None
_backup_jobs: Optional[dict] = None
_jobs_lock: Any = None
_background_tasks: Optional[dict] = None
_task_lock: Any = None
_persist_jobs: Optional[Callable[[], None]] = None
_update_job_from_task: Optional[Callable[..., None]] = None


def set_helpers(
    start_task: Callable[..., str],
    audit: Callable[..., None],
    backup_jobs: dict,
    jobs_lock: Any,
    background_tasks: dict,
    task_lock: Any,
    persist_jobs: Callable[[], None],
    update_job_from_task: Callable[..., None],
) -> None:
    global _start_task, _audit, _backup_jobs, _jobs_lock
    global _background_tasks, _task_lock, _persist_jobs, _update_job_from_task
    _start_task = start_task
    _audit = audit
    _backup_jobs = backup_jobs
    _jobs_lock = jobs_lock
    _background_tasks = background_tasks
    _task_lock = task_lock
    _persist_jobs = persist_jobs
    _update_job_from_task = update_job_from_task


# ────────────────────────────────────────────────────────────
# BACKUP HELPERS
# ────────────────────────────────────────────────────────────


def _check_tool(name: str, version_args: list[str] | None = None) -> bool:
    """Check if a CLI tool is installed and executable."""
    try:
        cmd = [name]
        if version_args:
            cmd.extend(version_args)
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _require_tool(name: str, version_args: list[str] | None = None) -> None:
    """Like _check_tool but raises HTTPException if not found."""
    if not _check_tool(name, version_args):
        raise HTTPException(status_code=500, detail=f"{name} not installed")


# ────────────────────────────────────────────────────────────
# BORG BACKUP
# ────────────────────────────────────────────────────────────


@router.get("/api/backup/borg/status")
async def borg_status(user=Depends(verify_token)):
    """Get Borg backup status and jobs"""
    installed = _check_tool("borg", ["version"])
    jobs = []
    if installed:
        try:
            list_result = subprocess.run(
                ["borg", "list", "--json", "/backup"],
                capture_output=True, text=True, timeout=30
            )
            if list_result.returncode == 0:
                try:
                    jobs = json.loads(list_result.stdout)
                except Exception as e:
                    logger.warning("borg list JSON parse failed: %s", e)
                    jobs = []
        except subprocess.TimeoutExpired:
            pass  # jobs stays []
    return {"installed": installed, "jobs": jobs}


@router.post("/api/backup/borg/create")
async def borg_create(body: dict, user=Depends(verify_token)):
    """Create new Borg backup job (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("borg", ["version"])
    
    name = body.get("name", "backup")
    source = body.get("source", "")
    destination = body.get("destination", "/backup")
    
    if not source:
        raise HTTPException(status_code=400, detail="Source required")
    
    archive_name = f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cmd = ["borg", "create", f"{destination}::{archive_name}", source]
    task_id = _start_task(cmd, "borg", "create", timeout=600)
    _audit(user["sub"], "backup.borg.create", "success",
            f"Borg archive '{archive_name}' from {source} to {destination}")
    return {"task_id": task_id, "archive": archive_name, "status": "running"}


@router.get("/api/backup/borg/list")
async def borg_list(destination: str, user=Depends(verify_token)):
    """List archives in repository"""
    _require_tool("borg", ["version"])
    
    try:
        result = subprocess.run(
            ["borg", "list", "--json", destination],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Listing archives timed out")
    if result.returncode == 0:
        try:
            return {"archives": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"archives": []}
    raise HTTPException(status_code=500, detail="Failed to list archives")


# ────────────────────────────────────────────────────────────
# RESTIC BACKUP
# ────────────────────────────────────────────────────────────


@router.get("/api/backup/restic/status")
async def restic_status(user=Depends(verify_token)):
    """Get Restic status"""
    return {"installed": _check_tool("restic", ["version"])}


@router.post("/api/backup/restic/snapshot")
async def restic_snapshot(body: dict, user=Depends(verify_token)):
    """Create Restic snapshot (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("restic", ["version"])
    
    repo = body.get("repo", "/backup/restic")
    paths = body.get("paths", [])
    
    if not paths:
        raise HTTPException(status_code=400, detail="Paths required")
    
    cmd = ["restic", "-r", repo, "snapshot"] + paths
    task_id = _start_task(cmd, "restic", "snapshot", timeout=600)
    _audit(user["sub"], "backup.restic.snapshot", "success",
            f"Restic snapshot of {len(paths)} paths to {repo}")
    return {"task_id": task_id, "status": "running"}


@router.get("/api/backup/restic/snapshots")
async def restic_snapshots(repo: str, user=Depends(verify_token)):
    """List restic snapshots"""
    _require_tool("restic", ["version"])
    
    cmd = ["restic", "-r", repo, "snapshots", "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"snapshots": []}
    if result.returncode == 0:
        try:
            return {"snapshots": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"snapshots": []}
    return {"snapshots": []}


# ────────────────────────────────────────────────────────────
# RCLONE SYNC
# ────────────────────────────────────────────────────────────


@router.get("/api/backup/rclone/status")
async def rclone_status(user=Depends(verify_token)):
    """Get RClone status"""
    return {"installed": _check_tool("rclone", ["version"])}


@router.post("/api/backup/rclone/sync")
async def rclone_sync(body: dict, user=Depends(verify_token)):
    """Run RClone sync (async — returns task_id, poll GET /api/backup/task/{id})"""
    _require_tool("rclone", ["version"])
    
    source = body.get("source", "")
    destination = body.get("destination", "")
    config = body.get("config", None)
    
    if not source or not destination:
        raise HTTPException(status_code=400, detail="Source and destination required")
    
    cmd = ["rclone", "sync", source, destination]
    if config:
        cmd.extend(["--config", config])
    task_id = _start_task(cmd, "rclone", "sync", timeout=600)
    _audit(user["sub"], "backup.rclone.sync", "success",
            f"Rclone sync from {source} to {destination}")
    return {"task_id": task_id, "status": "running"}


@router.get("/api/backup/rclone/configs")
async def rclone_configs(user=Depends(verify_token)):
    """List RClone configs"""
    if not _check_tool("rclone", ["version"]):
        return {"remotes": []}
    
    try:
        result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {"remotes": []}
    if result.returncode == 0:
        remotes = [r for r in result.stdout.strip().split("\n") if r]
        return {"remotes": remotes}
    return {"remotes": []}


# ────────────────────────────────────────────────────────────
# SCHEDULED BACKUP JOBS — CRUD
# ────────────────────────────────────────────────────────────


@router.get("/api/backup/jobs")
async def list_backup_jobs(user=Depends(verify_token)):
    """List all configured backup jobs."""
    with _jobs_lock:
        jobs = sorted(
            _backup_jobs.values(),
            key=lambda j: j.get("created_at", ""),
            reverse=True,
        )
    return {"jobs": jobs}


@router.post("/api/backup/jobs")
async def create_backup_job(body: dict, user=Depends(verify_token)):
    """Create a new scheduled backup job."""
    tool = body.get("tool", "")
    if tool not in ("borg", "restic", "rclone"):
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool}")
    if not body.get("source"):
        raise HTTPException(status_code=400, detail="source required")
    if not body.get("destination"):
        raise HTTPException(status_code=400, detail="destination required")

    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with _jobs_lock:
        _backup_jobs[job_id] = {
            "id": job_id,
            "name": body.get("name", f"{tool} backup"),
            "tool": tool,
            "enabled": body.get("enabled", True),
            "source": body.get("source", []),
            "destination": body.get("destination", ""),
            "schedule": body.get("schedule", "daily"),
            "retention": body.get("retention", {}),
            "created_at": now,
            "updated_at": now,
            "last_run": None,
            "last_run_ts": 0,
            "last_status": None,
            "last_task_id": None,
        }
    _persist_jobs()
    name = body.get("name", f"{tool} backup")
    _audit(user["sub"], "backup.job.create", "success",
            f"Created {tool} backup job '{name}' ({job_id})")
    return _backup_jobs[job_id]


@router.get("/api/backup/jobs/{job_id}")
async def get_backup_job(job_id: str, user=Depends(verify_token)):
    """Get a single backup job by ID."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/api/backup/jobs/{job_id}")
async def update_backup_job(job_id: str, body: dict, user=Depends(verify_token)):
    """Update an existing backup job."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Only update fields that are provided
    updatable = {"name", "tool", "enabled", "source", "destination",
                 "schedule", "retention"}
    updated_fields = []
    with _jobs_lock:
        for key in updatable:
            if key in body:
                old = job.get(key)
                if old != body[key]:
                    updated_fields.append(key)
                job[key] = body[key]
        job["updated_at"] = datetime.now().isoformat()
    _persist_jobs()
    _audit(user["sub"], "backup.job.update", "success",
            f"Updated job '{job.get('name', job_id)}': {', '.join(updated_fields)}")
    return job


@router.delete("/api/backup/jobs/{job_id}")
async def delete_backup_job(job_id: str, user=Depends(verify_token)):
    """Delete a backup job."""
    with _jobs_lock:
        if job_id not in _backup_jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        name = _backup_jobs[job_id].get("name", job_id)
        del _backup_jobs[job_id]
    _persist_jobs()
    _audit(user["sub"], "backup.job.delete", "success",
            f"Deleted backup job '{name}' ({job_id})")
    return {"ok": True, "deleted": job_id}


@router.post("/api/backup/jobs/{job_id}/run")
async def run_backup_job_now(job_id: str, user=Depends(verify_token)):
    """Trigger an immediate run of a backup job."""
    with _jobs_lock:
        job = _backup_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _execute_backup_job(job_id)
    _audit(user["sub"], "backup.job.run", "success",
            f"Triggered backup job '{job.get('name', job_id)}'")
    return {"ok": True, "job_id": job_id, "status": "triggered"}


# ────────────────────────────────────────────────────────────
# BACKGROUND TASK STATUS
# ────────────────────────────────────────────────────────────


@router.get("/api/backup/task/{task_id}")
async def get_task_status(task_id: str, user=Depends(verify_token)):
    """Poll background task status."""
    with _task_lock:
        t = _background_tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return t


@router.get("/api/backup/tasks")
async def list_tasks(user=Depends(verify_token)):
    """List all recent background tasks (newest first)."""
    with _task_lock:
        tasks = list(_background_tasks.values())
    return {"tasks": sorted(tasks, key=lambda x: x.get("started_at", 0), reverse=True)}


