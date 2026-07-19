"""ForgeOS — Audit log API surface.

Mounts under the existing FastAPI app via:

    from audit_api import router as audit_router, set_helpers as set_audit_helpers
    set_audit_helpers(get_db=_get_db)
    app.include_router(audit_router)

Routes:
  • GET /api/audit — query audit log (newest first, filterable, paginated)

Reads directly from the SQLite audit_log table via the injected _get_db
helper. Schema: id, timestamp, who, action, status, detail.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional

from fastapi import APIRouter, Depends

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_get_db: Optional[Callable[[], sqlite3.Connection]] = None


def set_helpers(get_db: Callable[[], sqlite3.Connection]) -> None:
    global _get_db
    _get_db = get_db


@router.get("/api/audit")
async def list_audit_log(user=Depends(verify_token),
                         limit: int = 100, offset: int = 0,
                         action: str | None = None,
                         prefix: str | None = None,
                         who: str | None = None):
    """Query the audit log. Newest first, with optional filters.

    Query params:
      limit   — max entries to return (default 100, max 1000)
      offset  — skip N entries from the front (for pagination)
      action  — filter by exact action name (e.g. "backup.job.create")
      prefix  — filter by action prefix (e.g. "storage." for the storage feed)
      who     — filter by username
    """
    assert _get_db is not None
    limit = min(limit, 1000)
    conn = _get_db()
    where = []
    params: list = []
    if action:
        where.append("action = ?")
        params.append(action)
    if prefix:
        where.append("action LIKE ?")
        params.append(prefix.replace("%", "") + "%")
    if who:
        where.append("who = ?")
        params.append(who)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = conn.execute(
        f"SELECT count(*) FROM audit_log{where_clause}", params
    ).fetchone()
    total = total_row[0] if total_row else 0
    rows = conn.execute(
        f"SELECT timestamp, who, action, status, detail FROM audit_log{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    columns = ["timestamp", "who", "action", "status", "detail"]
    return {
        "entries": [dict(zip(columns, r)) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
