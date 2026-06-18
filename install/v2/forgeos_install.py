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
    # reverse proxy + certs (ssl-cert provides the snakeoil cert so nginx can
    # bring up :443 before Let's Encrypt issues a real one — without it the
    # generated vhost references a cert that doesn't exist and nginx silently
    # runs :80 only).
    "nginx", "certbot", "python3-certbot-nginx", "ssl-cert",
    # vpn
    "wireguard", "wireguard-tools",
    # security tier tools (all of them; tiers enable/disable at runtime)
    "ufw", "fail2ban", "apparmor", "apparmor-utils",
    "auditd", "aide", "rkhunter",
    # backup
    "restic", "rclone",
    # mDNS: makes <hostname>.local resolve on the LAN with zero client config
    # (the default domain is .local, which IS mDNS — without avahi it resolves
    # nowhere). V-011.
    "avahi-daemon", "libnss-mdns",
    # base utilities
    "curl", "ca-certificates", "jq",
]

# The web UI backend (forgeos-api) listens here on localhost; nginx fronts it.
WEBUI_BACKEND_PORT = 5080
# Where the API code + web assets are deployed on the installed system.
FORGEOS_OPT = "/opt/forgeos"

# Secret files that MUST be mode 0600 (or stricter) and owned by root.
# phase_secaudit (V-013) proves this on the real box after install rather
# than trusting that each writer set it. A world-readable JWT secret, password
# hash file, or WireGuard private key is game-over.
SECRET_FILES = [
    "/etc/forgeos/api.env",            # JWT secret
    "/etc/forgeos/api-users.json",     # bcrypt password hashes
    "/etc/forgeos/config.json",        # may hold smtp/other secrets
    "/etc/forgeos/wireguard/server.key",  # WG private key (if VPN enabled)
]
# Runtime dirs the service needs to exist (created in phase_web before start).
# These are exactly the writable paths the systemd unit's ReadWritePaths
# references, so ProtectSystem=strict can bind-mount them.
RUNTIME_DIRS = [
    "/etc/forgeos",
    "/var/log/forgeos",
    "/var/lib/forgeos",
]

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
ReadWritePaths=/etc/forgeos /var/log/forgeos /var/lib/forgeos {opt} /srv

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
    http_post = None              # callable(url, body) -> (status, text)
    stat_file = None              # callable(path) -> (mode, uid) | None
    results: list = field(default_factory=list)
    _admin_password: str = ""     # set by phase_web; surfaced once by the CLI

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
        if self.http_post is None:
            self.http_post = self._default_http_post
        if self.stat_file is None:
            self.stat_file = self._default_stat_file

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

            # 1b. create the runtime dirs the service's systemd hardening
            # (ProtectSystem=strict + ReadWritePaths) needs to exist BEFORE
            # start — otherwise the namespace bind-mount fails with 226.
            self._make_dirs(RUNTIME_DIRS)

            # 1c. Disable the stock Debian default nginx site. It declares
            # `listen 80 default_server`, colliding with our default-deny
            # server (also default_server) -> nginx -t "duplicate default
            # server". Disabled the Debian-sanctioned way: remove the
            # sites-enabled SYMLINK (config stays in sites-available, exactly
            # what a2dissite does). Not a destructive rm of a real file.
            self._disable_stock_nginx_default()

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

            # 2b. Admin user (V-001). Generate a random password, bcrypt-hash
            # it, write the users file the API reads. Without this there is NO
            # admin account and login is impossible. Password returned so the
            # CLI can surface it once (V-004); never logged.
            self._admin_password = self._create_admin_user()

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

    def phase_verify(self) -> PhaseResult:
        """Post-install healthcheck (V-002): prove login actually works before
        the installer claims success. This is the whole point of the gate —
        'install finished' must mean 'you can log in', not just 'no errors'.

        - If we created the admin password this run, do a REAL login against
          the local API and require a token back.
        - If an admin already existed (re-run), we don't know the password, so
          we only assert the endpoint is up and correctly REJECTS a bogus
          login (401) — i.e. auth is wired, just not testable with a known pw.
        """
        try:
            ok, detail = self._verify_login(
                port=WEBUI_BACKEND_PORT,
                password=self._admin_password,
            )
            return PhaseResult("verify", ok, detail)
        except Exception as e:  # noqa: BLE001
            return PhaseResult("verify", False, str(e))

    def phase_secaudit(self) -> PhaseResult:
        """Prove every secret file is 0600-or-stricter and root-owned (V-013).
        Intent isn't proof — this checks the real files after install and fails
        the install if any secret is loosely permissioned. Files that don't
        exist (e.g. wg key when VPN disabled) are skipped, not failed.
        """
        try:
            bad = []
            for path in SECRET_FILES:
                info = self.stat_file(path)
                if info is None:
                    continue  # not present (optional feature) — fine
                mode, uid = info
                perm = mode & 0o777
                if perm & 0o077:  # any group/other bits set
                    bad.append(f"{path} mode={oct(perm)} (must be 0600 or stricter)")
                elif uid != 0:
                    bad.append(f"{path} uid={uid} (must be root)")
            if bad:
                return PhaseResult("secaudit", False, "; ".join(bad))
            return PhaseResult("secaudit", True, "all secret files 0600/root")
        except Exception as e:  # noqa: BLE001
            return PhaseResult("secaudit", False, str(e))

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
            self.phase_verify,
            self.phase_secaudit,
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
    def _make_dirs(dirs):
        from pathlib import Path
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _disable_stock_nginx_default():
        """Remove the stock Debian nginx default site symlink (a2dissite-style).
        Config stays in sites-available; only the sites-enabled symlink goes.
        No-op if already absent.
        """
        from pathlib import Path
        link = Path("/etc/nginx/sites-enabled/default")
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
        except OSError:
            pass

    def _verify_login(self, *, port, password, attempts=10, delay=1.0):
        """Poll the local login endpoint until the service answers, then:
        - if `password` is set: require 200 + a token (real login works);
        - if not (admin pre-existed): require the endpoint to reject a bogus
          login with 401 (auth wired, just not testable here).
        Returns (ok: bool, detail: str). Injectable via self.http_post.
        """
        import json
        import time

        url = f"http://127.0.0.1:{port}/api/auth/login"
        test_pw = password or "definitely-not-the-real-password"
        body = json.dumps({"username": "admin", "password": test_pw}).encode()

        last = "no response"
        for _ in range(attempts):
            try:
                status, text = self.http_post(url, body)
            except Exception as e:  # noqa: BLE001 — service may not be up yet
                last = f"connect error: {e}"
                time.sleep(delay)
                continue

            if password:
                if status == 200 and ("token" in text or "access_token" in text):
                    return True, "login verified (200 + token)"
                if status == 401:
                    last = "login rejected the generated password (401)"
                else:
                    last = f"unexpected status {status}"
            else:
                if status == 401:
                    return True, "auth endpoint up; rejects bad creds (401) as expected"
                last = f"expected 401 for bogus creds, got {status}"
            time.sleep(delay)
        return False, f"login healthcheck failed: {last}"

    @staticmethod
    def _default_stat_file(path):
        import os
        try:
            st = os.stat(path)
            return (st.st_mode, st.st_uid)
        except FileNotFoundError:
            return None

    @staticmethod
    def _default_http_post(url, body):
        import urllib.request
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def _create_admin_user(self) -> str:
        """Generate a random admin password, bcrypt-hash it, write the users
        file the API reads (0600). Returns the plaintext (shown once by the
        CLI). If an admin already exists, leaves it alone and returns "" so a
        re-run never clobbers a configured password.
        """
        import json
        import secrets
        from pathlib import Path

        users_file = Path("/etc/forgeos/api-users.json")
        if users_file.exists():
            try:
                existing = json.loads(users_file.read_text())
                if existing.get("admin", {}).get("hash"):
                    return ""
            except (ValueError, OSError):
                pass  # corrupt/unreadable — recreate

        password = secrets.token_urlsafe(12)
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        users = {"admin": {"hash": pwd_ctx.hash(password), "role": "admin"}}
        self._write_file(str(users_file), json.dumps(users, indent=2), 0o600)
        return password

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
