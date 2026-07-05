"""Security profile generator (v2).

Manages WHICH security tools are active for the selected profile
(low/medium/high). Tier definitions live in a declarative matrix below — so
"what does High add over Medium" is answerable by reading data, not tracing
logic.

Decisions (agreed with Keith):
  - Default profile: medium.
  - Lowering the tier DISABLES/stops the now-unneeded tools but keeps them
    INSTALLED, so switching back up is fast (no reinstall).
  - Re-applicable any time from the web UI: write profile to the config DB,
    call this generator's apply().

Tools managed: ufw, fail2ban, apparmor, auditd, aide, rkhunter, crowdsec.
All already present in legacy 07-security.sh — this organizes them into
tiers, it does NOT add new security software.
"""

from __future__ import annotations

from dataclasses import dataclass

from generators import RenderedFile, ServiceGenerator

TIER_TOOLS: dict[str, set[str]] = {
    "low": {"ufw", "fail2ban"},
    "medium": {"ufw", "fail2ban", "apparmor", "crowdsec"},
    "high": {"ufw", "fail2ban", "apparmor", "crowdsec", "auditd", "aide", "rkhunter"},
}

ALL_TOOLS = TIER_TOOLS["high"]

TOOL_UNIT: dict[str, str] = {
    "ufw": "ufw",
    "fail2ban": "fail2ban",
    "apparmor": "apparmor",
    "crowdsec": "crowdsec",
    "auditd": "auditd",
}


@dataclass(frozen=True)
class ToolPlan:
    tool: str
    active: bool


class SecurityGenerator(ServiceGenerator):
    name = "security"

    def plan(self, cfg) -> list[ToolPlan]:
        """Pure: profile -> per-tool active/inactive plan. Unit-testable."""
        active = TIER_TOOLS[cfg.security.profile]
        return [ToolPlan(tool=t, active=(t in active)) for t in sorted(ALL_TOOLS)]

    def render(self, cfg) -> list[RenderedFile]:
        f2b = cfg.security.fail2ban
        lines = [
            "# ForgeOS fail2ban jails — GENERATED. Do not edit.",
            "# Source: /etc/forgeos/config.json  (regenerate: forgeos-generate security)",
            "[DEFAULT]",
            f"bantime = {f2b.bantime}",
            f"findtime = {f2b.findtime}",
            f"maxretry = {f2b.maxretry}",
            "",
        ]

        def jail(name: str, on: bool, extra: list[str]) -> None:
            lines.append(f"[{name}]")
            lines.append("enabled = " + ("true" if (f2b.enabled and on) else "false"))
            lines.extend(extra)
            lines.append("")

        # trixie logs sshd to the journal, not /var/log/auth.log
        jail("sshd", f2b.jail_sshd, ["backend = systemd"])
        jail("nginx-http-auth", f2b.jail_nginx,
             ["port = http,https", "logpath = /var/log/nginx/error.log"])
        jail("forgeos-api", f2b.jail_forgeos,
             ["port = http,https",
              "filter = forgeos-api",
              "logpath = /var/log/forgeos/auth.log"])

        # the filter the forgeos-api jail references — grammar matches
        # forgeos_auth.log_auth_failure exactly
        filt = "\n".join([
            "# ForgeOS API auth-failure filter — GENERATED. Do not edit.",
            "[Definition]",
            r"failregex = ^.*forgeos-auth FAILED \S+ user=\S+ ip=<HOST>\s*$",
            "ignoreregex =",
        ]) + "\n"

        return [
            RenderedFile(path="/etc/fail2ban/jail.d/forgeos.conf",
                         content="\n".join(lines) + "\n", mode=0o644),
            RenderedFile(path="/etc/fail2ban/filter.d/forgeos-api.conf",
                         content=filt, mode=0o644),
        ]

    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        written = super().apply(cfg, do_reload=False)
        for p in self.plan(cfg):
            if p.active:
                self._enable_tool(p.tool)
            else:
                self._disable_tool(p.tool)
        if do_reload and _have("systemctl"):
            self._run(["systemctl", "reload", "fail2ban"], check=False)
        return written

    def _enable_tool(self, tool: str) -> None:
        if not _have("systemctl"):
            return
        if tool in ("aide", "rkhunter"):
            self._run(["systemctl", "enable", "--now", f"{tool}.timer"], check=False)
            return
        unit = TOOL_UNIT.get(tool)
        if unit:
            self._run(["systemctl", "enable", "--now", unit], check=False)

    def _disable_tool(self, tool: str) -> None:
        if not _have("systemctl"):
            return
        if tool in ("aide", "rkhunter"):
            self._run(["systemctl", "disable", "--now", f"{tool}.timer"], check=False)
            return
        unit = TOOL_UNIT.get(tool)
        if unit:
            self._run(["systemctl", "disable", "--now", unit], check=False)


def _have(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None
