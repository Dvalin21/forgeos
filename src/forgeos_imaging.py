"""ForgeOS — native UrBackup server lifecycle (imaging).

UrBackup is not in the Debian archives; upstream publishes official .deb
packages per GitHub release. This module installs that deb as a real
systemd service (urbackupsrv) — Keith's call over the Docker app: no
container layer, LAN client-discovery broadcasts work natively.

Deliberate ceilings:
- Version is PINNED below. Upstream debs are not covered by
  unattended-upgrades; upgrading = bump the pin, rerun install.
- Backup storage path is configured in UrBackup's own UI (Settings ->
  Backup storage path). UrBackup owns that database; we don't poke it.
- Root CLI only (forgeos-imaging). Package installs stay out of the API
  sandbox — same boundary as DR timers and app-store orchestration.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import forgeos_config as fc
from generators import registry

URBACKUP_VERSION = "2.5.37"   # verified against uroni/urbackup_backend releases
_DEB_URL = ("https://github.com/uroni/urbackup_backend/releases/download/"
            "{v}/urbackup-server_{v}_{arch}.deb")
SERVICE = "urbackupsrv"
WEB_PORT = 55414
VHOST_NAME = "urbackup"
# Client-facing ports (web UI stays nginx-only): connections + LAN discovery.
_FW_RULES = [
    {"port": "55413:55415", "proto": "tcp", "comment": "UrBackup clients"},
    {"port": "35623", "proto": "udp", "comment": "UrBackup discovery"},
]


class ImagingError(RuntimeError):
    pass


def _default_run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 120)      # nothing in this module may hang forever
    return subprocess.run(cmd, **kw)


def _arch() -> str:
    m = platform.machine()
    return {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf"}.get(m, m)


def deb_url(version: str = URBACKUP_VERSION) -> str:
    return _DEB_URL.format(v=version, arch=_arch())


def status(run=_default_run) -> dict:
    r = run(["dpkg-query", "-W", "-f", "${Version}", "urbackup-server"])
    installed = r.returncode == 0
    version = r.stdout.strip() if installed else ""
    active = False
    if installed:
        a = run(["systemctl", "is-active", SERVICE])
        active = a.stdout.strip() == "active"
    cfg = fc.load()
    return {"installed": installed, "version": version, "running": active,
            "url": f"https://{VHOST_NAME}.{cfg.domain}", "web_port": WEB_PORT}


def install(run=_default_run, version: str = URBACKUP_VERSION) -> dict:
    """Download the pinned upstream deb, apt-install it (resolves deps),
    enable the service, and give it a ForgeOS TLS vhost."""
    deb = f"/tmp/urbackup-server_{version}.deb"
    r = run(["curl", "-fsSL", "-o", deb, deb_url(version)], timeout=300)
    if r.returncode != 0:
        raise ImagingError(f"download failed: {r.stderr.strip()[:200]}")
    if not Path(deb).exists() or Path(deb).stat().st_size < 1_000_000:
        # a real server deb is tens of MB; a tiny file is an error page
        raise ImagingError(f"downloaded deb looks wrong ({deb})")
    # apt runs VISIBLY (no pipe capture) with hard bounds. The first version
    # captured output with no timeout and a wiped env — when apt stalled
    # (lock wait / prompt / postinst), the operator saw nothing, forever.
    r = run(["apt-get", "install", "-y",
             "-o", "DPkg::Lock::Timeout=60",          # bounded lock wait, visible msg
             "-o", "Dpkg::Options::=--force-confdef",
             "-o", "Dpkg::Options::=--force-confold",
             deb],
            capture_output=False, timeout=900,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    if r.returncode != 0:
        raise ImagingError("apt install failed — output above")
    r = run(["systemctl", "enable", "--now", SERVICE], timeout=60)
    if r.returncode != 0:
        raise ImagingError(f"service enable failed: {(r.stderr or '').strip()[:200]}")

    # ForgeOS vhost: urbackup.<domain> -> 127.0.0.1:55414, TLS from the
    # existing nginx generator. Client firewall rules go into the config-DB
    # (from lan_cidr only) — same class as the WireGuard listen-port guard:
    # without them, clients silently can't reach the server under
    # default-deny, and raw `ufw allow` gets wiped by the next converge.
    # Idempotent: each piece skipped if present.
    cfg = fc.load()
    changed = False
    if not any(v.name == VHOST_NAME for v in cfg.nginx.vhosts):
        cfg.nginx.vhosts.append(fc.NginxVhost(
            name=VHOST_NAME, domain=f"{VHOST_NAME}.{cfg.domain}",
            upstream_port=WEB_PORT))
        res = registry.apply_one("nginx", cfg=cfg)
        if not res.ok:
            raise ImagingError(f"nginx vhost apply failed: {res.error}")
        changed = True
    existing = {(r.port, r.proto) for r in cfg.firewall.rules}
    for spec in _FW_RULES:
        if (spec["port"], spec["proto"]) not in existing:
            cfg.firewall.rules.append(fc.FirewallRule(
                port=spec["port"], proto=spec["proto"], action="allow",
                from_ip=cfg.security.lan_cidr, comment=spec["comment"]))
            changed = True
    if changed:
        res = registry.apply_one("ufw", cfg=cfg)
        if not res.ok:
            raise ImagingError(f"ufw apply failed: {res.error}")
        fc.save(cfg)
    return status(run=run)


def uninstall(run=_default_run, purge: bool = False) -> dict:
    run(["systemctl", "disable", "--now", SERVICE], timeout=60)
    r = run(["apt-get", "remove" if not purge else "purge", "-y",
             "-o", "DPkg::Lock::Timeout=60", "urbackup-server"],
            capture_output=False, timeout=600,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    if r.returncode != 0:
        raise ImagingError("apt remove failed — output above")
    cfg = fc.load()
    before_v = len(cfg.nginx.vhosts)
    cfg.nginx.vhosts = [v for v in cfg.nginx.vhosts if v.name != VHOST_NAME]
    ours = {(r["port"], r["proto"]) for r in _FW_RULES}
    before_r = len(cfg.firewall.rules)
    cfg.firewall.rules = [r for r in cfg.firewall.rules
                          if (r.port, r.proto) not in ours]
    if len(cfg.nginx.vhosts) != before_v:
        res = registry.apply_one("nginx", cfg=cfg)
        if not res.ok:
            raise ImagingError(f"nginx apply failed: {res.error}")
    if len(cfg.firewall.rules) != before_r:
        res = registry.apply_one("ufw", cfg=cfg)
        if not res.ok:
            raise ImagingError(f"ufw apply failed: {res.error}")
    if len(cfg.nginx.vhosts) != before_v or len(cfg.firewall.rules) != before_r:
        fc.save(cfg)
    return status(run=run)
