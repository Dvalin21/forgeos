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

# The web UI backend (forgeos-api) listens here on localhost; nginx fronts it.
WEBUI_BACKEND_PORT = 5080
# Where the API code + web assets are deployed on the installed system.
FORGEOS_OPT = "/opt/forgeos"

_API_SERVICE_UNIT = """# ForgeOS Web UI API — GENERATED
[Unit]
Description=ForgeOS Web UI API Backend
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory={opt}
EnvironmentFile={env}
ExecStart=/usr/bin/python3 {opt}/forgeos-api.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=forgeos-api
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/etc/forgeos /var/log/forgeos {opt} /srv /var/lib/forgeos

[Install]
WantedBy=multi-user.target
"""


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
    repo_root: str = ""           # where the cloned repo lives (auto-derived if empty)
    run = None                    # callable(list[str]) -> CompletedProcess
    save_cfg = staticmethod(fc.save)
    generate = None               # callable() -> list (registry.apply_all result)
    apply_toggles = None          # callable(cfg) -> list
    deploy_web = None             # callable(repo_root, opt_dir) -> None
    results: list = field(default_factory=list)

    def __post_init__(self):
        import subprocess
        from pathlib import Path

        if not self.repo_root:
            # this file is at <repo>/install/v2/forgeos_install.py
            self.repo_root = str(Path(__file__).resolve().parent.parent.parent)
        if self.run is None:
            self.run = lambda cmd: subprocess.run(
                cmd, check=False, capture_output=True, text=True
            )
        if self.generate is None:
            self.generate = self._default_generate
        if self.apply_toggles is None:
            self.apply_toggles = self._default_toggles
        if self.deploy_web is None:
            self.deploy_web = self._default_deploy_web

    # ---- phases ----

    def phase_web(self) -> PhaseResult:
        """Deploy the web API + UI, create its service, start it.

        Without this nginx proxies to a dead backend and https://<domain>
        shows nothing. Runs BEFORE generate so the nginx vhost has a live
        :5080 to point at.
        """
        import secrets

        try:
            # 1. deploy code + web assets to /opt/forgeos
            self.deploy_web(self.repo_root, FORGEOS_OPT)

            # 2. JWT secret (persist in the forgeos env file)
            jwt_secret = secrets.token_hex(32)
            env_path = "/etc/forgeos/api.env"
            self._write_file(
                env_path,
                f"FORGEOS_JWT_SECRET={jwt_secret}\n"
                f"FORGEOS_WEB_ROOT={FORGEOS_OPT}/web/desktop\n"
                f"FORGEOS_PORT={WEBUI_BACKEND_PORT}\n",
                0o600,
            )

            # 3. systemd service
            self._write_file(
                "/etc/systemd/system/forgeos-api.service",
                _API_SERVICE_UNIT.format(opt=FORGEOS_OPT, env=env_path),
                0o644,
            )

            # 4. enable + start
            self.run(["systemctl", "daemon-reload"])
            r = self.run(["systemctl", "enable", "--now", "forgeos-api"])
            if getattr(r, "returncode", 1) != 0:
                return PhaseResult("web", False,
                                  getattr(r, "stderr", "").strip() or "service start failed")
            return PhaseResult("web", True)
        except Exception as e:  # noqa: BLE001
            return PhaseResult("web", False, str(e))

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
        # The web UI vhost: nginx fronts the forgeos-api backend on :5080.
        # Without this the nginx generator renders zero vhosts and
        # https://<domain> has nothing to serve.
        cfg.nginx.vhosts.append(
            fc.NginxVhost(
                name="forgeos-ui",
                domain=c.domain,
                upstream_port=WEBUI_BACKEND_PORT,
                websocket=True,   # the dashboard uses websockets for live data
            )
        )
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
            self.phase_web,
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

    @staticmethod
    def _write_file(path, content, mode):
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

    @staticmethod
    def _default_deploy_web(repo_root, opt_dir):
        """Copy the API modules + web assets from the repo to /opt/forgeos."""
        import shutil
        from pathlib import Path

        src = Path(repo_root) / "src"
        opt = Path(opt_dir)
        opt.mkdir(parents=True, exist_ok=True)
        # copy every python module + the generators package
        for item in src.iterdir():
            dest = opt / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        # web assets
        web_src = Path(repo_root) / "web"
        if web_src.exists():
            shutil.copytree(web_src, opt / "web", dirs_exist_ok=True)
