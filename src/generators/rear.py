"""ReaR (Relax-and-Recover) generator — ForgeOS bare-metal DR.

Renders /etc/rear/local.conf from the config DB. ReaR uses this to build a
bootable rescue image + full system archive so the ForgeOS box can be rebuilt
on the same or new hardware.

Like the other generators: render() is pure (config -> file content), apply()
writes atomically with mkdir -p. There's no live service to reload — ReaR
runs on a timer / on demand — so reload() is a no-op. The systemd timer is
managed by the installer step, not rendered here.
"""

from __future__ import annotations

from generators import GeneratorError, RenderedFile, ServiceGenerator

REAR_CONF = "/etc/rear/local.conf"

# Map our schedule words to systemd OnCalendar (used by the installer's timer,
# exposed here so the value is validated/normalized in one place).
SCHEDULE_ONCALENDAR = {
    "daily": "*-*-* 02:30:00",
    "weekly": "Sun *-*-* 02:30:00",
    "monthly": "*-*-01 02:30:00",
}


class RearGenerator(ServiceGenerator):
    name = "osbackup"

    def render(self, cfg) -> list[RenderedFile]:
        ob = cfg.osbackup
        if not ob.enabled:
            return []

        # ReaR BACKUP_URL for a local mounted filesystem is file://<path>.
        backup_url = f"file://{ob.backup_path}"

        lines = [
            "# ForgeOS bare-metal DR (ReaR) — GENERATED, do not edit by hand.",
            "# Source: /etc/forgeos/config.json  (regenerate: forgeos-generate osbackup)",
            "",
            f"OUTPUT={ob.output}",
            "BACKUP=NETFS",
            f"BACKUP_URL={backup_url}",
            "",
            "# Compress the tar archive with zstd. Set the COMPRESS PROGRAM (not\n"
            "# just options) so ReaR doesn't fall back to gzip and append .gz —\n"
            "# otherwise the file is misnamed backup.tar.zst.gz.",
            'BACKUP_PROG_COMPRESS_PROGRAM="zstd"',
            'BACKUP_PROG_COMPRESS_OPTIONS=( "-3" )',
            'BACKUP_PROG_COMPRESS_SUFFIX=".zst"',
            'BACKUP_PROG_SUFFIX=".tar.zst"',
            "",
            "# Keep the last few recovery points.",
            "NETFS_KEEP_OLD_BACKUP_COPY=yes",
            "",
            "# --- Rescue-image console (CRITICAL for VM recovery) ---",
            "# ReaR auto-detects a serial console on the source box and bakes a",
            "# console=ttyS0 expectation into the rescue image. In a hypervisor",
            "# VM (Proxmox/KVM) whose serial device isn't wired the same way, the",
            "# rescue system then HANGS at 'serial-getty@ttyS0' and never reaches",
            "# the recovery prompt. Force the rescue kernel onto the VGA/noVNC",
            "# console the VM actually presents, and don't depend on serial.",
            "# (ReaR vars: USE_SERIAL_CONSOLE, SERIAL_CONSOLE_DEVICE_SYSLINUX,",
            "#  KERNEL_CMDLINE — verified against ReaR rescue/GNU/Linux console",
            "#  handling.) console=tty0 makes 'printk: console [tty0] enabled'.",
            "USE_SERIAL_CONSOLE=\"n\"",
            'KERNEL_CMDLINE+=" console=tty0"',
            "# Don't let the rescue init block on a serial getty that may never",
            "# get a device in the target VM.",
            'EXCLUDE_SYMLINK+=( "/etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service" )',
            "",
            "# Exclude the data pool + the backup target itself from the OS",
            "# archive (the OS backup protects the OS disk, not the NAS data).",
            'EXCLUDE_BACKUP+=( "/srv/nas/*" )',
            f'EXCLUDE_BACKUP+=( "{ob.backup_path}/*" )',
        ]
        return [RenderedFile(path=REAR_CONF, content="\n".join(lines) + "\n", mode=0o600)]

    def validate(self, files: list[RenderedFile]) -> None:
        # Defensive: never emit a config that backs up onto root.
        for f in files:
            if "BACKUP_URL=file:///\n" in f.content or "BACKUP_URL=file://\n" in f.content:
                raise GeneratorError("ReaR backup target resolves to root fs")

    def reload(self) -> None:
        # No daemon. ReaR runs via timer/on-demand. Nothing to reload.
        return None

    def oncalendar(self, cfg) -> str:
        """Translate the schedule word to a systemd OnCalendar string."""
        sched = cfg.osbackup.schedule
        return SCHEDULE_ONCALENDAR.get(sched, sched)  # allow raw OnCalendar too
