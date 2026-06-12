"""ForgeOS v2 installer core.

Thin, phased installer that bootstraps the minimal base, then hands all
config work to the generators (no heredocs, no per-service config writing in
the installer itself). This is the opposite of the v1 19-module monolith.

Phases:
  1. base packages   — one apt transaction for the always-installed base
  2. seed config DB  — write initial /etc/forgeos/config.json from choices
  3. keystores       — wireguard server key, smtp password placeholder
  4. generate        — forgeos-generate all (renders configs, starts services)
  5. toggles         — ForgeFileDB/Coral/GPU per config (hardware-gated)

Each phase is a method with its side effects injected (run-command, config
save, generator apply), so the orchestration is unit-testable without root,
apt, or systemd. The bash bootstrap (install/v2/bootstrap.sh) only installs
Python + this package, then calls run().
"""

from __future__ import annotations

from dataclasses import dataclass, field

import forgeos_config as fc

# The always-installed base. Grounded in the base services:
# samba, nginx, wireguard, nfs, security tools, docker, incus, restic, rustfs.
BASE_PACKAGES: list[str] = [
    # file sharing
    "samba", "samba-common-bin", "nfs-kernel-server", "nfs-common",
    # reverse proxy + certs
    "nginx", "certbot", "python3-certbot-nginx",
    # vpn
    "wireguard", "wireguard-tools",
    # security tier tools (all of them; tiers enable/disable at runtime)
    "ufw", "fail2ban", "apparmor", "apparmor-utils",
    "auditd", "aide", "rkhunter",
    # backup
    "restic", "rclone",
    # base utilities
    "curl", "ca-certificates", "jq",
]


@dataclass
class InstallChoices:
    """What the operator selected at install time."""

    domain: str = "nas.local"
    lan_cidr: str = "10.0.0.0/24"
    security_profile: str = "medium"
    enable_wireguard: bool = False
    enable_nfs: bool = False
    # base toggles
    enable_forgefiledb: bool = False
    enable_coral: bool = False
    enable_gpu: bool = False


@dataclass
class PhaseResult:
    phase: str
    ok: bool
    detail: str = ""


@dataclass
class Installer:
    choices: InstallChoices
    run = None                    # callable(list[str]) -> CompletedProcess
    save_cfg = staticmethod(fc.save)
    generate = None               # callable() -> list (registry.apply_all result)
    apply_toggles = None          # callable(cfg) -> list
    results: list = field(default_factory=list)

    def __post_init__(self):
        import subprocess

        if self.run is None:
            self.run = lambda cmd: subprocess.run(
                cmd, check=False, capture_output=True, text=True
            )
        if self.generate is None:
            self.generate = self._default_generate
        if self.apply_toggles is None:
            self.apply_toggles = self._default_toggles

    # ---- phases ----

    def phase_base_packages(self) -> PhaseResult:
        r = self.run(["apt-get", "install", "-y", *BASE_PACKAGES])
        ok = getattr(r, "returncode", 1) == 0
        return PhaseResult("base_packages", ok,
                          "" if ok else getattr(r, "stderr", "").strip())

    def build_config(self) -> fc.ForgeOSConfig:
        """Pure: turn install choices into the initial config DB."""
        c = self.choices
        cfg = fc.ForgeOSConfig(domain=c.domain)
        cfg.security.profile = c.security_profile
        cfg.security.lan_cidr = c.lan_cidr
        cfg.samba.enabled = True
        cfg.nginx.enabled = True
        cfg.wireguard.enabled = c.enable_wireguard
        cfg.nfs.enabled = c.enable_nfs
        cfg.nfs.lan_cidr = c.lan_cidr
        cfg.toggles.forgefiledb = c.enable_forgefiledb
        cfg.toggles.coral = c.enable_coral
        cfg.toggles.gpu = c.enable_gpu
        return cfg

    def phase_seed_config(self) -> PhaseResult:
        cfg = self.build_config()
        try:
            self.save_cfg(cfg)
            return PhaseResult("seed_config", True)
        except Exception as e:  # noqa: BLE001
            return PhaseResult("seed_config", False, str(e))

    def phase_keystores(self) -> PhaseResult:
        """Generate the wireguard server key if VPN is enabled."""
        if not self.choices.enable_wireguard:
            return PhaseResult("keystores", True, "wireguard disabled — skipped")
        # wg genkey -> /etc/forgeos/wireguard/server.key (0600)
        r = self.run(["bash", "-c",
                      "umask 077; mkdir -p /etc/forgeos/wireguard && "
                      "wg genkey > /etc/forgeos/wireguard/server.key"])
        ok = getattr(r, "returncode", 1) == 0
        return PhaseResult("keystores", ok,
                          "" if ok else getattr(r, "stderr", "").strip())

    def phase_generate(self) -> PhaseResult:
        try:
            results = self.generate()
            failed = [r for r in results if not getattr(r, "ok", True)]
            if failed:
                names = ", ".join(getattr(r, "service", "?") for r in failed)
                return PhaseResult("generate", False, f"failed: {names}")
            return PhaseResult("generate", True)
        except Exception as e:  # noqa: BLE001
            return PhaseResult("generate", False, str(e))

    def phase_toggles(self) -> PhaseResult:
        try:
            cfg = fc.load()
            self.apply_toggles(cfg)
            return PhaseResult("toggles", True)
        except Exception as e:  # noqa: BLE001
            return PhaseResult("toggles", False, str(e))

    # ---- orchestration ----

    def run_all(self, *, stop_on_fail=True) -> list[PhaseResult]:
        phases = [
            self.phase_base_packages,
            self.phase_seed_config,
            self.phase_keystores,
            self.phase_generate,
            self.phase_toggles,
        ]
        self.results = []
        for ph in phases:
            res = ph()
            self.results.append(res)
            if not res.ok and stop_on_fail:
                break
        return self.results

    # ---- defaults ----

    @staticmethod
    def _default_generate():
        from generators import registry
        return registry.apply_all()

    @staticmethod
    def _default_toggles(cfg):
        from forgeos_toggles import ToggleManager
        return ToggleManager().plan(cfg)
