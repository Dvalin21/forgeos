"""ufw generator (v2).

Converges the live firewall to the config-DB FirewallConfig. Unlike the file
generators this renders nothing — ufw owns /etc/ufw persistence — so render()
is empty and apply() drives the ufw CLI (arg-lists, no shell).

Lockout safety, in order:
  1. `ufw --force reset` disables the firewall first — the transient state is
     fail-OPEN, never fail-closed.
  2. When enabling with a non-allow incoming policy, management guard rules
     (SSH rate-limited, HTTP/S) from security.lan_cidr are inserted BEFORE any
     user rule.
  3. `ufw --force enable` runs LAST, after policies + guards + rules exist.

ponytail: full reset+rebuild instead of diffing live rules — O(rules) CLI calls,
idempotent, and immune to drift; switch to incremental converge only if rule
counts ever make reset visibly slow.
"""
from __future__ import annotations

from generators import GeneratorError, RenderedFile, ServiceGenerator


class UfwGenerator(ServiceGenerator):
    name = "ufw"

    def render(self, cfg) -> list[RenderedFile]:
        return []                      # CLI-driven; nothing to write

    def reload(self) -> None:
        return                         # enable/disable happens inside apply()

    # ── rule → argv ──────────────────────────────────────────────
    @staticmethod
    def _rule_args(r) -> list[str]:
        port = r.port if r.proto == "any" else f"{r.port}/{r.proto}"
        if r.from_ip == "any":
            if r.family == "ipv4":
                args = [r.action, "from", "0.0.0.0/0", "to", "any", "port", r.port]
            elif r.family == "ipv6":
                args = [r.action, "from", "::/0", "to", "any", "port", r.port]
            else:
                args = [r.action, port]
                if r.comment:
                    args += ["comment", r.comment]
                return args
        else:
            args = [r.action, "from", r.from_ip, "to", "any", "port", r.port]
        if r.proto != "any":
            args += ["proto", r.proto]
        if r.comment:
            args += ["comment", r.comment]
        return args

    def _guard_rules(self, cfg) -> list[list[str]]:
        """Management access that must exist before enable — the firewall
        equivalent of the undeletable forgeos-ui vhost."""
        lan = getattr(cfg.security, "lan_cidr", "") or "any"
        src = ["from", lan] if lan != "any" else []
        g = []
        g.append(["limit"] + src + ["to", "any", "port", "22", "proto", "tcp",
                                    "comment", "ForgeOS management SSH"])
        for p in ("80", "443"):
            g.append(["allow"] + src + ["to", "any", "port", p, "proto", "tcp",
                                        "comment", "ForgeOS management UI"])
        # WireGuard must be reachable from the WAN, not just lan_cidr —
        # without this guard the default-deny policy silently eats the
        # handshake and the VPN "runs" but no client can ever connect.
        wg = getattr(cfg, "wireguard", None)
        if wg is not None and wg.enabled:
            g.append(["allow", f"{wg.listen_port}/udp",
                      "comment", "ForgeOS WireGuard VPN"])
        return g

    def _data_connect_rules(self, cfg) -> list[list[str]]:
        """LAN-scoped allows for tracked server-DB ports (Data Connect).
        Derived from config like the WireGuard guard — no mirrored rule
        entries the user could delete out from under a tracked database."""
        dc = getattr(cfg, "data_connect", None)
        if dc is None or not dc.enabled:
            return []
        lan = getattr(cfg.security, "lan_cidr", "") or "any"
        src = ["from", lan] if lan != "any" else []
        g = []
        for d in dc.databases:
            if d.kind in ("postgres", "mysql") and d.port:
                g.append(["allow"] + src + ["to", "any", "port", str(d.port),
                          "proto", "tcp",
                          "comment", f"ForgeOS Data Connect {d.name}"])
        return g

    # ── converge ─────────────────────────────────────────────────
    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        fw = cfg.firewall
        cmds: list[list[str]] = [["ufw", "--force", "reset"]]
        cmds.append(["ufw", "default", fw.default_incoming, "incoming"])
        cmds.append(["ufw", "default", fw.default_outgoing, "outgoing"])
        cmds.append(["ufw", "logging", fw.logging])
        if fw.enabled and fw.default_incoming != "allow":
            cmds += [["ufw"] + g for g in self._guard_rules(cfg)]
        if fw.enabled and fw.default_incoming != "allow":
            cmds += [["ufw"] + g for g in self._data_connect_rules(cfg)]
        cmds += [["ufw"] + self._rule_args(r) for r in fw.rules]
        cmds.append(["ufw", "--force", "enable" if fw.enabled else "disable"])

        for cmd in cmds:
            res = self._run(cmd, check=False)
            if res.returncode != 0:
                raise GeneratorError(
                    f"{' '.join(cmd)} failed: {(res.stderr or res.stdout or '').strip()}"
                )
        return []
