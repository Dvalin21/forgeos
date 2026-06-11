"""ForgeOS app-store install / uninstall orchestration.

Ties together: manifest parsing (forgeos_appstore), port allocation
(forgeos_ports), the config DB (forgeos_config), and the nginx generator
(generators.nginx) — so installing an app also gets it a reverse-proxy vhost
+ TLS for free.

The PLAN step is pure and testable (what files/records/ports would result).
The EXECUTE step performs the side effects (write compose, docker compose
up, save config DB, render nginx). Execution shells out to docker, so it's
injected/guarded to keep the planning fully unit-testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import forgeos_config as fc
import forgeos_ports as fp
from forgeos_appstore import AppManifest

APPS_ROOT = "/srv/forgeos/apps"


class InstallError(RuntimeError):
    pass


@dataclass
class InstallPlan:
    """What an install WOULD do — pure, inspectable, testable."""

    app_id: str
    version: str
    webui_port: int
    container_port: str
    data_dir: str
    compose_path: str
    vhost_name: str
    vhost_domain: str
    # the variable substitutions that will be applied to the compose
    env: dict = field(default_factory=dict)


def plan_install(
    manifest: AppManifest,
    cfg: fc.ForgeOSConfig,
    *,
    allocate=fp.allocate_port,
    apps_root: str = APPS_ROOT,
) -> InstallPlan:
    """Pure-ish: decide port, paths, vhost for installing `manifest`.

    `allocate` is injectable so tests don't probe real sockets. Does NOT
    write anything.
    """
    app_id = manifest.app_id
    if any(a.id == app_id for a in cfg.apps):
        raise InstallError(f"app {app_id!r} is already installed")

    used_ports = {a.webui_port for a in cfg.apps}
    container_port = manifest.meta.port_map or "80"
    preferred = int(container_port) if container_port.isdigit() else None
    webui_port = allocate(used_ports, preferred=preferred)

    data_dir = f"{apps_root}/{app_id}"
    return InstallPlan(
        app_id=app_id,
        version=_image_version(manifest),
        webui_port=webui_port,
        container_port=container_port,
        data_dir=data_dir,
        compose_path=f"{data_dir}/docker-compose.yml",
        vhost_name=app_id,
        vhost_domain=f"{app_id}.{cfg.domain}",
        env={
            "WEBUI_PORT": str(webui_port),
            "APP_ID": app_id,
            "TZ": os.environ.get("TZ", "UTC"),
            "PUID": "1000",
            "PGID": "1000",
        },
    )


def apply_install_to_config(
    plan: InstallPlan, cfg: fc.ForgeOSConfig, *, websocket: bool = False
) -> fc.ForgeOSConfig:
    """Pure: return a NEW config with the app + its nginx vhost recorded.

    Auto-creates the app.<domain> vhost (Keith's decision: on by default).
    """
    cfg.apps.append(
        fc.InstalledApp(
            id=plan.app_id, version=plan.version,
            webui_port=plan.webui_port, enabled=True,
        )
    )
    cfg.nginx.vhosts.append(
        fc.NginxVhost(
            name=plan.vhost_name, domain=plan.vhost_domain,
            upstream_port=plan.webui_port, websocket=websocket,
        )
    )
    # re-validate
    return fc.ForgeOSConfig.model_validate(cfg.model_dump())


def plan_uninstall(app_id: str, cfg: fc.ForgeOSConfig) -> None:
    if not any(a.id == app_id for a in cfg.apps):
        raise InstallError(f"app {app_id!r} is not installed")


def apply_uninstall_to_config(
    app_id: str, cfg: fc.ForgeOSConfig
) -> fc.ForgeOSConfig:
    """Pure: return a NEW config with the app + its vhost removed."""
    plan_uninstall(app_id, cfg)
    cfg.apps = [a for a in cfg.apps if a.id != app_id]
    cfg.nginx.vhosts = [v for v in cfg.nginx.vhosts if v.name != app_id]
    return fc.ForgeOSConfig.model_validate(cfg.model_dump())


def render_compose(manifest: AppManifest, plan: InstallPlan) -> str:
    """Substitute platform variables into the compose text. Pure."""
    import yaml

    text = yaml.safe_dump(manifest.compose, default_flow_style=False, sort_keys=False)
    for key, val in plan.env.items():
        # support ${KEY} and ${KEY:-default}
        text = _subst(text, key, val)
    return text


def _subst(text: str, key: str, val: str) -> str:
    import re

    # ${KEY:-default} -> val ; ${KEY} -> val
    text = re.sub(r"\$\{" + re.escape(key) + r"(:-[^}]*)?\}", val, text)
    return text


def _image_version(manifest: AppManifest) -> str:
    """Pull the main service's image tag as the recorded version."""
    main = manifest.meta.main
    svc = manifest.compose.get("services", {}).get(main, {})
    img = svc.get("image", "")
    # tag is after the last ':' that isn't part of a registry:port
    last = img.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else ""
