"""Unattended-upgrades generator (v2).

Debian's unattended-upgrades already targets the security origin by default;
this renders only the periodic switches + reboot policy. No reload — apt
reads config per run.
"""
from __future__ import annotations

from generators import RenderedFile, ServiceGenerator


class UpdatesGenerator(ServiceGenerator):
    name = "updates"

    def render(self, cfg) -> list[RenderedFile]:
        u = cfg.updates
        lines = [
            "// ForgeOS unattended updates — GENERATED. Do not edit.",
            "// Source: /etc/forgeos/config.json  (regenerate: forgeos-generate updates)",
            f'APT::Periodic::Update-Package-Lists "{1 if u.enabled else 0}";',
            f'APT::Periodic::Unattended-Upgrade "{1 if u.enabled else 0}";',
            'APT::Periodic::AutocleanInterval "7";',
            f'Unattended-Upgrade::Automatic-Reboot "{"true" if u.auto_reboot else "false"}";',
        ]
        if u.auto_reboot:
            lines.append(f'Unattended-Upgrade::Automatic-Reboot-Time "{u.reboot_time}";')
        return [RenderedFile(path="/etc/apt/apt.conf.d/52forgeos-updates.conf",
                             content="\n".join(lines) + "\n", mode=0o644)]

    def reload(self) -> None:
        return
