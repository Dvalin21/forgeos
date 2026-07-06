"""Security generator (v2).

Owns fail2ban (jails + the forgeos-api filter) and ensures AppArmor stays
enforced. That is the whole list — deliberately.

Deleted from scope (small-business NAS threat model, per owner decision):
auditd, AIDE, rkhunter, crowdsec — high operational burden / false-positive
fatigue for a shop with no analyst; near-zero marginal detection on a patched,
auto-updating appliance. ufw moved to its own generator (single owner:
config.firewall). Patching lives in the updates generator.
"""

from __future__ import annotations

from pathlib import Path

from generators import RenderedFile, ServiceGenerator


def _have(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


class SecurityGenerator(ServiceGenerator):
    name = "security"

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
        # repeat offenders across ALL jails: week-long ban after 3 bans in a day
        jail("recidive", f2b.jail_recidive,
             ["logpath = /var/log/fail2ban.log",
              "bantime = 1w", "findtime = 1d", "maxretry = 3"])

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
        # fail2ban validates logpaths at load and drops jails whose file is
        # missing; both our sources are created lazily. Touch them.
        for lp in ("/var/log/forgeos/auth.log", "/var/log/fail2ban.log"):
            try:
                f = Path(lp)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.touch(exist_ok=True)
            except OSError:
                pass
        if _have("systemctl"):
            if cfg.security.fail2ban.enabled:
                self._run(["systemctl", "enable", "--now", "fail2ban"], check=False)
            else:
                self._run(["systemctl", "disable", "--now", "fail2ban"], check=False)
            # AppArmor: stock Debian profiles confine nginx/samba for free.
            # Always on; no config surface.
            self._run(["systemctl", "enable", "--now", "apparmor"], check=False)
            if do_reload and cfg.security.fail2ban.enabled:
                self._run(["systemctl", "reload", "fail2ban"], check=False)
        return written
