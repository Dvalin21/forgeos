"""ForgeOS data-scrub (btrfs scrub) scheduler + runner.

`btrfs scrub` is the check that makes the rest of the storage promise true: it
reads every block, verifies the checksums btrfs already wrote, and on a
redundant profile REPAIRS what it finds from the good copy. ForgeOS could
always run one — but only from a button, which means in practice it never ran.
This module makes it scheduled, so the "healthy" the UI shows is a standing
condition rather than a snapshot.

Shape copied from forgeos_osbackup (the ReaR timer), deliberately: render the
units as pure text, inject the side effects, keep the whole thing testable
without root or a real pool.

Honest limit, surfaced in the UI too: on a `single` profile there is no second
copy, so a scrub DETECTS corruption and reports it but cannot repair it. A
scheduled scrub never invents redundancy you did not configure.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from forgeos_atomic import atomic_write as _atomic_write

SERVICE_UNIT = "/etc/systemd/system/forgeos-scrub.service"
TIMER_UNIT = "/etc/systemd/system/forgeos-scrub.timer"
TIMER_NAME = "forgeos-scrub.timer"

# Same shape as generators/rear.py so both schedules read alike in the UI.
SCHEDULE_ONCALENDAR = {
    "daily": "*-*-* 02:30:00",
    "weekly": "Sun *-*-* 02:30:00",
    "monthly": "*-*-01 02:30:00",
}


def oncalendar(schedule: str) -> str:
    """Translate a schedule word to a systemd OnCalendar string. A raw
    OnCalendar is passed through, which is how an operator can pick a time the
    UI does not offer."""
    s = (schedule or "").strip()
    return SCHEDULE_ONCALENDAR.get(s.lower(), s)


def render_service_unit() -> str:
    return (
        "# ForgeOS data scrub (btrfs scrub) — GENERATED\n"
        "[Unit]\n"
        "Description=ForgeOS data scrub (btrfs scrub)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        # Bare command name: systemd resolves a non-absolute ExecStart against
        # its default PATH (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin),
        # so this works whether pip installed the console script into
        # /usr/local/bin or a distro path. No -B: the blocking form returns a
        # real exit status when the scrub finishes, which is what tells us
        # whether to report a problem.
        "ExecStart=forgeos-storage scrub run\n"
    )


def render_timer_unit(calendar: str) -> str:
    return (
        "# ForgeOS data scrub schedule — GENERATED\n"
        "[Unit]\n"
        "Description=ForgeOS data scrub schedule\n\n"
        "[Timer]\n"
        f"OnCalendar={calendar}\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


@dataclass
class ScrubRunner:
    """Runs scrubs and reports the outcome. `run`/`notify`/`audit` are
    injected so tests never need root, a pool, or a mail server."""

    run: object = None
    notify: object = None
    audit: object = None

    def __post_init__(self):
        if self.run is None:
            self.run = lambda cmd, timeout=60: subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=timeout
            )
        if self.notify is None:
            self.notify = _default_notify
        if self.audit is None:
            self.audit = _default_audit

    # ---- timer management ----

    def setup_timer(self, calendar: str, *, write=None, reload_daemon=True) -> None:
        writer = write or _atomic_write
        writer(SERVICE_UNIT, render_service_unit(), 0o644)
        writer(TIMER_UNIT, render_timer_unit(calendar), 0o644)
        if reload_daemon:
            self.run(["systemctl", "daemon-reload"])
            self.run(["systemctl", "enable", "--now", TIMER_NAME])

    def disable_timer(self) -> None:
        self.run(["systemctl", "disable", "--now", TIMER_NAME])

    def timer_status(self) -> dict:
        r = self.run(["systemctl", "is-active", TIMER_NAME])
        state = (getattr(r, "stdout", "") or "").strip()
        return {"active": state == "active", "state": state or "unknown"}

    # ---- the run ----

    def scrub_pools(self, targets: list[tuple[str, str]], *, timeout=86400) -> dict:
        """Scrub each (pool_name, mountpoint). `targets` is a list of pairs so
        the caller resolves config→mountpoint once and this stays testable.

        Returns { ok, checked, failed, errors: {pool: detail} }. A pool whose
        scrub exits non-zero is reported, not raised: one bad pool must not
        stop the others, and a partial result is still worth recording."""
        checked: list[str] = []
        failed: list[str] = []
        errors: dict[str, str] = {}
        for name, mount in targets:
            try:
                r = self.run(["btrfs", "scrub", "start", mount], timeout=timeout)
            except Exception as exc:                      # noqa: BLE001
                failed.append(name)
                errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            checked.append(name)
            if getattr(r, "returncode", 1) != 0:
                failed.append(name)
                detail = (getattr(r, "stderr", "") or getattr(r, "stdout", "") or "").strip()
                errors[name] = detail[-500:] or "scrub exited non-zero"
        result = {
            "ok": not failed,
            "checked": checked,
            "failed": failed,
            "errors": errors,
        }
        # The detail must NAME the pools: /api/storage/scrub-schedule derives
        # "last checked" per pool from this row, so a bare count would leave
        # every pool looking never-checked.
        self.audit("system", "storage.pool.scrub_scheduled", "success" if result["ok"] else "warning",
                   "scrubbed: " + (", ".join(checked) or "none")
                   + (f"; problems: {', '.join(failed)}" if failed else ""))
        if failed:
            detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            self.notify("critical", "Data scrub found problems",
                        f"{', '.join(failed)} — {detail}")
        return result


def _default_notify(level: str, title: str, message: str) -> None:
    try:
        from notifications_api import record
        record(level, title, message)
    except Exception:                                       # noqa: BLE001
        pass


def _default_audit(who: str, action: str, status: str, detail: str | None = None) -> None:
    """Write the audit row directly.

    The real `_audit` lives in the main module, whose filename contains a
    hyphen (`forgeos-api.py`) and so cannot be imported by name from here. This
    mirrors its INSERT against the same table. It must NOT be a no-op: the
    Storage page derives "last checked" from these rows, so a scheduled scrub
    that recorded nothing would leave the panel frozen forever — which is
    exactly the bug this replaced."""
    import sqlite3
    from datetime import datetime
    try:
        data_dir = Path(os.environ.get("FORGEOS_DATA_DIR", "/var/lib/forgeos"))
        conn = sqlite3.connect(str(data_dir / "forgeos.db"), timeout=10)
        try:
            conn.execute(
                "INSERT INTO audit_log (timestamp, who, action, status, detail) VALUES (?,?,?,?,?)",
                (datetime.now().isoformat(), who, action, status, detail or ""),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:                                       # noqa: BLE001
        pass


def target_pools(cfg, *, resolver=None) -> list[tuple[str, str]]:
    """Resolve the scrub config to (name, mountpoint) pairs.

    `resolver` maps a pool name to its mountpoint; it defaults to the pool's
    configured mountpoint. Pools with an empty list mean "every configured
    pool". A pool that isn't mounted is skipped rather than scrubbed — btrfs
    needs a live path."""
    scrub = cfg.storage.scrub
    wanted = [p.lower() for p in scrub.pools] if scrub.pools else None
    out: list[tuple[str, str]] = []
    for pool in cfg.storage.pools:
        if wanted is not None and pool.name.lower() not in wanted:
            continue
        mount = resolver(pool.name) if resolver else pool.resolved_mountpoint
        if mount:
            out.append((pool.name, mount))
    return out