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
        """Run rear mkbackup, then VERIFY the artifacts exist and are
        substantial before reporting success — a 0 exit code alone is not proof
        a usable backup landed. Returns True only if both the rescue ISO and
        the system archive are present and non-trivial."""
        r = self.run(["rear", "-v", "mkbackup"])
        ok = getattr(r, "returncode", 1) == 0
        if not ok:
            self.notify("critical", "OS backup FAILED",
                        f"rear mkbackup failed: {getattr(r,'stderr','').strip()[:500]}")
            return False

        problem = self._verify_artifacts(backup_path)
        if problem:
            self.notify("critical", "OS backup INCOMPLETE",
                        f"rear exited 0 but {problem}")
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

    def _verify_artifacts(self, backup_path) -> str:
        """'' if a valid ISO + archive exist under backup_path, else a
        description of what's missing/too-small. Injectable via find_artifacts."""
        if not backup_path:
            return ""  # nothing to verify against
        finder = self.find_artifacts or self._default_find_artifacts
        iso_bytes, archive_bytes = finder(backup_path)
        MIN_ISO = 20 * 1024 * 1024
        MIN_ARCHIVE = 50 * 1024 * 1024
        if iso_bytes < MIN_ISO:
            return f"no rescue ISO found (largest .iso = {iso_bytes} bytes)"
        if archive_bytes < MIN_ARCHIVE:
            return f"no system archive found (largest archive = {archive_bytes} bytes)"
        return ""

    @staticmethod
    def _default_find_artifacts(backup_path):
        """(largest_iso_bytes, largest_archive_bytes) under backup_path,
        recursive, skipping the .old rotation so we check the CURRENT backup."""
        import os
        biggest_iso = 0
        biggest_archive = 0
        for root, _dirs, files in os.walk(backup_path):
            if root.endswith(".old") or ".old/" in (root + "/"):
                continue
            for f in files:
                try:
                    sz = os.path.getsize(os.path.join(root, f))
                except OSError:
                    continue
                if f.endswith(".iso"):
                    biggest_iso = max(biggest_iso, sz)
                elif ".tar" in f and any(x in f for x in ("zst", "gz", "bz2")):
                    biggest_archive = max(biggest_archive, sz)
        return biggest_iso, biggest_archive

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
