"""ForgeOS LHSR — SMART snapshot scheduler.

Creates a systemd timer unit that periodically records SMART snapshots
for all monitored disks. Also provides CLI and API for manual snapshot
triggering and schedule configuration.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("forgeos-lhsr-scheduler")

# systemd timer unit for periodic SMART snapshots
SNAPSHOT_SERVICE_UNIT = """# ForgeOS LHSR — SMART snapshot recorder
[Unit]
Description=ForgeOS LHSR SMART snapshot recorder
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {opt}/lhsr_snapshot.py
User=root
StandardOutput=journal
StandardError=journal
"""

SNAPSHOT_TIMER_UNIT = """# ForgeOS LHSR — SMART snapshot timer
[Unit]
Description=ForgeOS LHSR periodic SMART snapshots

[Timer]
OnCalendar={calendar}
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
"""

SNAPSHOT_SCRIPT = """#!/usr/bin/env python3
\"\"\"ForgeOS LHSR SMART snapshot recorder.

Reads SMART data from all monitored disks and records snapshots
to the trend database.
\"\"\"
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/forgeos")

from forgeos_lhsr_trend import TrendDB
from forgeos_lhsr_health import DiskHealth, compute_health_score


def get_monitored_disks():
    \"\"\"Get list of disks to monitor from config + lsblk.\"\"\"
    disks = []
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINT"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return disks
        data = json.loads(r.stdout)
        for dev in data.get("blockdevices", []):
            if dev.get("type") != "disk":
                continue
            # Skip loop devices and RAM disks
            name = dev.get("name", "")
            if name.startswith("loop") or name.startswith("ram"):
                continue
            disks.append(f"/dev/{name}")
    except Exception as e:
        print(f"Error getting disk list: {{e}}", file=sys.stderr)
    return disks


def read_smart(disk_path: str) -> dict:
    \"\"\"Read SMART attributes from a disk.\"\"\"
    result = {
        "reallocated": 0,
        "pending": 0,
        "uncorrectable": 0,
        "temperature": 0,
        "power_on_hours": 0,
        "wear_level": 0,
    }
    try:
        r = subprocess.run(
            ["smartctl", "-A", "-j", disk_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return result
        data = json.loads(r.stdout)
        attrs = data.get("ata_smart_attributes", {}).get("table", [])
        for attr in attrs:
            aid = attr.get("id", 0)
            val = attr.get("raw", {}).get("value", 0)
            if aid == 5:
                result["reallocated"] = val
            elif aid == 197:
                result["pending"] = val
            elif aid == 198:
                result["uncorrectable"] = val
            elif aid in (194, 190):
                result["temperature"] = val
            elif aid == 9:
                result["power_on_hours"] = val
            elif aid == 177:
                result["wear_level"] = val
    except Exception as e:
        print(f"Error reading SMART from {{disk_path}}: {{e}}", file=sys.stderr)
    return result


def main():
    \"\"\"Record SMART snapshots for all monitored disks.\"\"\"
    db = TrendDB("/var/lib/forgeos/lhsr_trends.db")
    db.open()

    disks = get_monitored_disks()
    for disk_path in disks:
        smart = read_smart(disk_path)
        dh = DiskHealth(
            disk_path=disk_path,
            smart_reallocated=smart["reallocated"],
            smart_pending=smart["pending"],
            smart_uncorrectable=smart["uncorrectable"],
            temperature=smart["temperature"],
            power_on_hours=smart["power_on_hours"],
            wear_level=smart["wear_level"],
        )
        score = compute_health_score(dh)
        db.record_snapshot(
            disk_path=disk_path,
            reallocated=smart["reallocated"],
            pending=smart["pending"],
            uncorrectable=smart["uncorrectable"],
            temperature=smart["temperature"],
            power_on_hours=smart["power_on_hours"],
            wear_level=smart["wear_level"],
            health_score=score,
        )

    db.close()


if __name__ == "__main__":
    main()
"""


def install_scheduler(
    calendar: str = "daily",
    opt_dir: str = "/opt/forgeos",
) -> None:
    """Install the SMART snapshot timer.

    Args:
        calendar: systemd calendar expression (daily, hourly, weekly, etc.)
        opt_dir: where ForgeOS is installed.
    """
    # Write the snapshot script
    script_path = Path(opt_dir) / "lhsr_snapshot.py"
    script_path.write_text(SNAPSHOT_SCRIPT.format(opt=opt_dir))
    script_path.chmod(0o755)

    # Write the service unit
    service_path = Path("/etc/systemd/system/forgeos-lhsr-snapshot.service")
    service_path.write_text(SNAPSHOT_SERVICE_UNIT.format(opt=opt_dir))

    # Write the timer unit
    timer_path = Path("/etc/systemd/system/forgeos-lhsr-snapshot.timer")
    timer_path.write_text(SNAPSHOT_TIMER_UNIT.format(calendar=calendar))

    # Enable and start
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True, text=True, timeout=10)
    subprocess.run(["systemctl", "enable", "--now", "forgeos-lhsr-snapshot.timer"], check=True, capture_output=True, text=True, timeout=10)

    logger.info(f"LHSR SMART snapshot scheduler installed (calendar: {calendar})")


def remove_scheduler() -> None:
    """Remove the SMART snapshot timer."""
    subprocess.run(["systemctl", "disable", "--now", "forgeos-lhsr-snapshot.timer"], capture_output=True, text=True, timeout=10)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True, text=True, timeout=10)

    for path in [
        "/etc/systemd/system/forgeos-lhsr-snapshot.service",
        "/etc/systemd/system/forgeos-lhsr-snapshot.timer",
    ]:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    logger.info("LHSR SMART snapshot scheduler removed")


def get_status() -> dict:
    """Get scheduler status."""
    r = subprocess.run(
        ["systemctl", "is-active", "forgeos-lhsr-snapshot.timer"],
        capture_output=True, text=True, timeout=5,
    )
    active = r.stdout.strip() == "active"

    # Get timer info
    info = {}
    r = subprocess.run(
        ["systemctl", "show", "forgeos-lhsr-snapshot.timer", "--property=NextElapseUSecMonotonic,LastTriggerUSec,TimersCalendar"],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v

    return {
        "active": active,
        "info": info,
    }
