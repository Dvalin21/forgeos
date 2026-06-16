"""ForgeOS OS-backup (ReaR) runtime: timer units + backup run + notify.

The RearGenerator (generators/rear.py) renders /etc/rear/local.conf. This
module manages the *operational* side:
  - render the systemd service + timer units (pure -> testable)
  - install/enable or disable the timer based on config
  - run a backup (rear mkbackup) and report success/failure into the
    notification path
  - optional cloud sync of the produced archive via Rclone

Side effects (systemctl, rear, rclone) are injected so the unit rendering +
notify logic are unit-testable without root.
"""

from __future__ import annotations

from dataclasses import dataclass

TIMER_UNIT = "/etc/systemd/system/forgeos-osbackup.timer"
SERVICE_UNIT = "/etc/systemd/system/forgeos-osbackup.service"


def render_service_unit() -> str:
    return (
        "# ForgeOS OS-backup (ReaR) — GENERATED\n"
        "[Unit]\n"
        "Description=ForgeOS bare-metal backup (ReaR)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/sbin/rear -v mkbackup\n"
        # success/failure is reported by the wrapper that calls this, but a
        # systemd OnFailure hook can also notify:
        "OnFailure=forgeos-osbackup-failed.service\n"
    )


def render_timer_unit(oncalendar: str) -> str:
    return (
        "# ForgeOS OS-backup (ReaR) — GENERATED\n"
        "[Unit]\n"
        "Description=ForgeOS bare-metal backup schedule\n\n"
        "[Timer]\n"
        f"OnCalendar={oncalendar}\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


@dataclass
class OsBackupRunner:
    run = None            # callable(list[str]) -> CompletedProcess
    notify = None         # callable(level, title, message) -> None

    def __post_init__(self):
        import subprocess
        if self.run is None:
            self.run = lambda cmd: subprocess.run(
                cmd, check=False, capture_output=True, text=True
            )
        if self.notify is None:
            self.notify = self._default_notify

    # ---- timer management ----

    def setup_timer(self, oncalendar: str, *, write=None, reload_daemon=True) -> None:
        """Write + enable the timer. `write` injectable for tests."""
        writer = write or _atomic_write
        writer(SERVICE_UNIT, render_service_unit(), 0o644)
        writer(TIMER_UNIT, render_timer_unit(oncalendar), 0o644)
        if reload_daemon:
            self.run(["systemctl", "daemon-reload"])
            self.run(["systemctl", "enable", "--now", "forgeos-osbackup.timer"])

    def disable_timer(self) -> None:
        self.run(["systemctl", "disable", "--now", "forgeos-osbackup.timer"])

    # ---- backup run ----

    def run_backup(self, *, cloud_sync=False, cloud_remote="", backup_path="") -> bool:
        """Run rear mkbackup; notify on result. Returns True on success."""
        r = self.run(["rear", "-v", "mkbackup"])
        ok = getattr(r, "returncode", 1) == 0
        if not ok:
            self.notify("critical", "OS backup FAILED",
                        f"rear mkbackup failed: {getattr(r,'stderr','').strip()[:500]}")
            return False

        if cloud_sync and cloud_remote and backup_path:
            rc = self.run(["rclone", "sync", backup_path, f"{cloud_remote}:osbackup"])
            if getattr(rc, "returncode", 1) != 0:
                self.notify("warning", "OS backup cloud sync failed",
                            f"local backup OK but rclone sync failed: "
                            f"{getattr(rc,'stderr','').strip()[:300]}")
                return True  # local backup still succeeded

        self.notify("info", "OS backup complete",
                    "ForgeOS bare-metal backup finished successfully.")
        return True

    @staticmethod
    def _default_notify(level, title, message):
        # route through the existing notification fan-out if available
        try:
            import subprocess
            subprocess.run(["forgeos-notify", level, title, message],
                           check=False, capture_output=True)
        except Exception:
            pass


def _atomic_write(path: str, content: str, mode: int) -> None:
    import os
    import tempfile
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".forgeos-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
