"""ForgeOS app-store EXECUTE layer.

The side-effecting orchestrator that wraps the pure planning logic in
forgeos_appinstall. Responsibilities:
  - sync the catalog (git clone/pull)
  - read an app manifest from the synced catalog
  - install: write resolved compose -> docker compose up -> record in config
    DB -> render the app's nginx vhost (via the existing generator)
  - uninstall: docker compose down -> drop from config DB -> re-render nginx

Each side-effecting dependency (run-command, config load/save, nginx apply)
is injectable so the orchestration is unit-testable without Docker, git, or
root. The pure decisions live in forgeos_appinstall and are already tested.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import forgeos_appinstall as ai
import forgeos_config as fc
from forgeos_appstore import parse_manifest_file

CATALOG_DIR = "/var/lib/forgeos/appstore"
CATALOG_REPO = "https://github.com/Dvalin21/forgeos-appstore.git"


class AppStoreError(RuntimeError):
    pass


def _run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


@dataclass
class AppStore:
    """Orchestrates catalog + install/uninstall. Injectable deps for tests."""

    catalog_dir: str = CATALOG_DIR
    catalog_repo: str = CATALOG_REPO
    run = staticmethod(_run)            # command runner (injectable)
    load_cfg = staticmethod(fc.load)    # config loader (injectable)
    save_cfg = staticmethod(fc.save)    # config saver (injectable)
    render_nginx = None                 # callable(cfg) -> None; default set in __post_init__

    def __post_init__(self):
        if self.render_nginx is None:
            self.render_nginx = self._default_render_nginx

    # ---- catalog ----

    def sync_catalog(self) -> None:
        """git clone or pull the catalog. Works offline once synced."""
        d = Path(self.catalog_dir)
        if (d / ".git").exists():
            r = self.run(["git", "-C", str(d), "pull", "--ff-only"])
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            r = self.run(["git", "clone", "--depth", "1", self.catalog_repo, str(d)])
        if r.returncode != 0:
            raise AppStoreError(f"catalog sync failed: {r.stderr.strip()}")

    def manifest_path(self, app_id: str) -> Path:
        return Path(self.catalog_dir) / "apps" / app_id / "docker-compose.yml"

    def load_manifest(self, app_id: str):
        p = self.manifest_path(app_id)
        if not p.exists():
            raise AppStoreError(f"app {app_id!r} not found in catalog ({p})")
        return parse_manifest_file(p)

    # ---- install ----

    def install(self, app_id: str, *, write_files=True) -> ai.InstallPlan:
        manifest = self.load_manifest(app_id)
        cfg = self.load_cfg()
        plan = ai.plan_install(manifest, cfg)        # pure, raises if dup

        if write_files:
            compose_text = ai.render_compose(manifest, plan)
            self._write_compose(plan.compose_path, compose_text)
            self._compose_up(plan)

        # record in config DB + add nginx vhost (pure), persist, render nginx
        cfg = ai.apply_install_to_config(plan, cfg)
        self.save_cfg(cfg)
        self.render_nginx(cfg)
        return plan

    def uninstall(self, app_id: str, *, remove_data=False, write_files=True) -> None:
        cfg = self.load_cfg()
        ai.plan_uninstall(app_id, cfg)               # pure, raises if absent

        if write_files:
            compose_path = f"{ai.APPS_ROOT}/{app_id}/docker-compose.yml"
            self._compose_down(compose_path)
            if remove_data:
                self._remove_data_dir(f"{ai.APPS_ROOT}/{app_id}")

        cfg = ai.apply_uninstall_to_config(app_id, cfg)
        self.save_cfg(cfg)
        self.render_nginx(cfg)

    # ---- side effects (each guarded/injectable) ----

    def _write_compose(self, path: str, text: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _compose_up(self, plan: ai.InstallPlan) -> None:
        r = self.run(["docker", "compose", "-f", plan.compose_path, "up", "-d"])
        if r.returncode != 0:
            raise AppStoreError(f"docker compose up failed: {r.stderr.strip()}")

    def _compose_down(self, compose_path: str) -> None:
        if Path(compose_path).exists():
            self.run(["docker", "compose", "-f", compose_path, "down"])

    def _remove_data_dir(self, data_dir: str) -> None:
        import shutil

        if Path(data_dir).exists():
            shutil.rmtree(data_dir, ignore_errors=True)

    @staticmethod
    def _default_render_nginx(cfg) -> None:
        # Render the nginx vhosts via the existing generator registry.
        from generators import registry

        registry.apply_one("nginx", cfg=cfg)
