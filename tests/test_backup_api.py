"""Tests for the Backup API (src/backup_api.py).

Covers auth enforcement, CRUD validation, and the run-now dispatch path.
Helpers are injected with lightweight fakes so the router is exercised in
isolation — no real borg/restic/rclone binaries, no background-task infra.

This module also regresses a real bug: run_backup_job_now() calls
_execute_backup_job(), which used to be undefined in this module's namespace
(NameError at runtime). It is now injected via set_helpers(); test_run_now_dispatches
fails loudly if that wiring breaks again.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backup_api


# ── lightweight fakes ────────────────────────────────────────
_jobs: dict = {}
_tasks: dict = {}
_calls: list = []
_jobs_lock = threading.Lock()
_task_lock = threading.Lock()


def _fake_start_task(cmd, tool, action, timeout=600, job_id=None):
    tid = str(uuid.uuid4())
    _tasks[tid] = {"id": tid, "cmd": list(cmd), "status": "running", "started_at": 0}
    _calls.append(("start_task", tool, action, list(cmd)))
    return tid


def _fake_execute(job_id: str) -> None:
    _calls.append(("execute", job_id))


def _fake_persist() -> None:
    pass


def _fake_audit(*a, **k) -> None:
    pass


def _fake_update(task_id, status, error=None) -> None:
    pass


@pytest.fixture
def client():
    _jobs.clear()
    _tasks.clear()
    _calls.clear()
    backup_api.set_helpers(
        start_task=_fake_start_task,
        audit=_fake_audit,
        backup_jobs=_jobs,
        jobs_lock=_jobs_lock,
        background_tasks=_tasks,
        task_lock=_task_lock,
        persist_jobs=_fake_persist,
        update_job_from_task=_fake_update,
        execute_job=_fake_execute,
    )
    app = FastAPI()
    app.include_router(backup_api.router)
    return TestClient(app)


# ── auth enforcement ────────────────────────────────────────
def test_auth_required(client):
    assert client.get("/api/backup/jobs").status_code == 401
    assert client.post("/api/backup/jobs", json={"tool": "borg"}).status_code == 401


# ── tool status (no tool binary required; _check_tool returns False) ──
def test_tool_status_endpoints(client, auth_headers):
    for path in ("borg", "restic", "rclone"):
        r = client.get(f"/api/backup/{path}/status", headers=auth_headers)
        assert r.status_code == 200
        assert "installed" in r.json()


# ── create validation ───────────────────────────────────────
def test_create_rejects_bad_tool(client, auth_headers):
    r = client.post(
        "/api/backup/jobs",
        json={"tool": "rsync", "source": "/x", "destination": "/y"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_create_requires_source(client, auth_headers):
    r = client.post(
        "/api/backup/jobs",
        json={"tool": "borg", "destination": "/backup"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_create_requires_destination(client, auth_headers):
    r = client.post(
        "/api/backup/jobs",
        json={"tool": "borg", "source": "/home"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_create_valid_borg(client, auth_headers):
    r = client.post(
        "/api/backup/jobs",
        json={"tool": "borg", "source": ["/home"], "destination": "/backup"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "id" in data and data["tool"] == "borg"
    assert data["enabled"] is True


# ── CRUD lifecycle ──────────────────────────────────────────
def test_list_get_update_delete(client, auth_headers):
    created = client.post(
        "/api/backup/jobs",
        json={"tool": "restic", "source": ["/data"], "destination": "/backup/restic",
              "name": "nightly"},
        headers=auth_headers,
    ).json()
    jid = created["id"]

    r = client.get("/api/backup/jobs", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()["jobs"]) == 1

    r = client.get(f"/api/backup/jobs/{jid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["name"] == "nightly"

    r = client.put(f"/api/backup/jobs/{jid}", json={"enabled": False}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False

    r = client.delete(f"/api/backup/jobs/{jid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["deleted"] == jid

    r = client.get(f"/api/backup/jobs/{jid}", headers=auth_headers)
    assert r.status_code == 404


def test_get_missing_404(client, auth_headers):
    assert client.get("/api/backup/jobs/nope", headers=auth_headers).status_code == 404


def test_update_missing_404(client, auth_headers):
    assert client.put("/api/backup/jobs/nope", json={"enabled": False},
                      headers=auth_headers).status_code == 404


def test_delete_missing_404(client, auth_headers):
    assert client.delete("/api/backup/jobs/nope", headers=auth_headers).status_code == 404


# ── run-now dispatch (regression for missing _execute_backup_job) ──
def test_run_now_dispatches(client, auth_headers):
    created = client.post(
        "/api/backup/jobs",
        json={"tool": "rclone", "source": ["/home"], "destination": "/dest"},
        headers=auth_headers,
    ).json()
    jid = created["id"]
    r = client.post(f"/api/backup/jobs/{jid}/run", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "triggered"
    assert ("execute", jid) in [(c[0], c[1]) for c in _calls]


def test_run_missing_404(client, auth_headers):
    assert client.post("/api/backup/jobs/nope/run", headers=auth_headers).status_code == 404


# ── task status ─────────────────────────────────────────────
def test_task_status_404(client, auth_headers):
    assert client.get("/api/backup/task/does-not-exist",
                      headers=auth_headers).status_code == 404


# ── admin gate (regression for C4: backup was open to any authed user) ──
def test_create_requires_admin(client, user_headers):
    r = client.post(
        "/api/backup/jobs",
        json={"tool": "borg", "source": ["/home"], "destination": "/backup"},
        headers=user_headers,
    )
    assert r.status_code == 403
