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


def _any_running(ps_stdout: str):
    """Parse `docker compose ps --format json` -> is any service running?

    Returns True/False, or None when the output is non-empty but unparseable
    (caller must treat None as "state unknown" and NOT guess). Empty output is
    a real answer: nothing is up. Handles both NDJSON (one object per line) and
    a JSON array — compose versions differ on which they emit.
    """
    import json

    text = ps_stdout.strip()
    if not text:
        return False
    if text[0] == "[":
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            return None
    else:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "running" in str(row.get("State", "")).lower():
            return True
        if str(row.get("Status", "")).lower().startswith("up"):
            return True
    return False


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

    # ---- converge (reconcile actual Docker -> config DB) ----

    def converge(self, cfg=None, *, apps_root: str | None = None) -> ai.ConvergeResult:
        """Reconcile actual Docker state to the config DB's app list.

        For each app in cfg.apps:
          enabled  -> its compose project must be UP
          disabled -> its compose project must be STOPPED (kept, not removed)

        Idempotent: probes actual state and issues `up`/`stop` ONLY on a delta,
        so boot, post-restore, and a second back-to-back run all heal rather
        than double-act (`compose up -d` / `stop` are themselves no-ops when
        already in the target state, and we don't even call them unless the
        state differs).

        Scoped by construction to app-store projects: every command is
        `docker compose -p <id> -f <apps_root>/<id>/docker-compose.yml ...`.
        converge NEVER issues a bare `docker rm/stop`, so a container started
        via /api/docker/run (the advanced path, not recorded in cfg.apps) is
        untouchable here. It also never saves config or renders nginx — it only
        moves Docker run-state.

        ponytail: forward-only — does NOT sweep ORPHANS (a compose project that
        is up but absent from cfg.apps). Safe orphan removal needs global
        project enumeration gated on a forgeos-managed label; deferred to the
        boot/restore wiring commit. Normal uninstall already downs its project,
        so orphans don't accumulate through the supported path.
        """
        if cfg is None:
            cfg = self.load_cfg()
        root = apps_root if apps_root is not None else ai.APPS_ROOT

        result = ai.ConvergeResult()
        for app in cfg.apps:
            st = self._converge_one(app, root)
            result.states.append(st)
            if st.action == "error":
                result.errors.append(app.id)
            elif st.action in ("up", "stop"):
                result.changed.append(app.id)
        return result

    def _converge_one(self, app, root: str) -> ai.AppState:
        desired = "up" if app.enabled else "stopped"
        compose_path = f"{root}/{app.id}/docker-compose.yml"

        if not Path(compose_path).exists():
            action = ai.decide_app_action(
                enabled=app.enabled, running=False, compose_exists=False
            )
            detail = "" if action == "noop" else f"no compose file at {compose_path}"
            return ai.AppState(app.id, desired, "absent", action, detail)

        running = self._probe_running(app.id, compose_path)
        if running is None:
            return ai.AppState(
                app.id, desired, "unknown", "error",
                f"could not determine state of {app.id!r} (docker unreachable "
                f"or unparseable compose ps output)",
            )

        actual = "up" if running else "stopped"
        action = ai.decide_app_action(
            enabled=app.enabled, running=running, compose_exists=True
        )
        if action in ("up", "stop"):
            err = self._compose_action(action, app.id, compose_path)
            if err:
                return ai.AppState(app.id, desired, actual, "error", err)
        return ai.AppState(app.id, desired, actual, action)

    def _probe_running(self, app_id: str, compose_path: str):
        """Actual run-state of one app's project. Returns True/False, or None
        when state could not be determined (caller must not guess)."""
        r = self.run(
            ["docker", "compose", "-p", app_id, "-f", compose_path,
             "ps", "--format", "json"]
        )
        if r.returncode != 0:
            return None
        return _any_running(r.stdout)

    def _compose_action(self, action: str, app_id: str, compose_path: str) -> str:
        """Apply `up -d` or `stop` to one app's project. '' on success, else
        the error text (fail loud — never swallow a compose failure)."""
        tail = ["up", "-d"] if action == "up" else ["stop"]
        r = self.run(
            ["docker", "compose", "-p", app_id, "-f", compose_path] + tail
        )
        if r.returncode != 0:
            return f"compose {action} failed: {r.stderr.strip()[:200]}"
        return ""

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
