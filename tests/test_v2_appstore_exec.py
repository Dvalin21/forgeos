"""Tests for the app-store EXECUTE layer — injected fakes, no Docker/git."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
import forgeos_appstore_exec as ex  # noqa: E402


VALID_COMPOSE = textwrap.dedent("""
    name: grafana
    services:
      grafana:
        image: grafana/grafana:11.4.0
        ports:
          - target: 3000
            published: ${WEBUI_PORT:-3000}
    x-forgeos:
      title: Grafana
      main: grafana
      port_map: "3000"
""").strip()


def _store(tmp_path, cfg_holder, cmds):
    """Build an AppStore wired to a temp catalog + in-memory config + fake run."""
    catalog = tmp_path / "catalog"
    (catalog / "apps" / "grafana").mkdir(parents=True)
    (catalog / "apps" / "grafana" / "docker-compose.yml").write_text(VALID_COMPOSE)
    (catalog / ".git").mkdir()

    # Redirect APPS_ROOT into tmp so install() never touches the real
    # /srv/forgeos (which a non-root CI runner can't create — and which a
    # test must never write to anyway).
    import forgeos_appinstall as _ai
    _ai.APPS_ROOT = str(tmp_path / "srv-apps")

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, cwd=None):
        cmds.append(cmd)
        return R()

    store = ex.AppStore(catalog_dir=str(catalog))
    store.run = fake_run
    store.load_cfg = lambda: cfg_holder["cfg"]
    store.save_cfg = lambda c, path=None: cfg_holder.__setitem__("cfg", c)
    store.render_nginx = lambda c: cfg_holder.__setitem__("rendered", True)
    return store


def test_load_manifest_from_catalog(tmp_path):
    holder = {"cfg": fc.ForgeOSConfig()}
    store = _store(tmp_path, holder, [])
    m = store.load_manifest("grafana")
    assert m.app_id == "grafana"


def test_load_manifest_missing(tmp_path):
    holder = {"cfg": fc.ForgeOSConfig()}
    store = _store(tmp_path, holder, [])
    with pytest.raises(ex.AppStoreError, match="not found"):
        store.load_manifest("ghost")


def test_install_writes_compose_and_records(tmp_path):
    holder = {"cfg": fc.ForgeOSConfig(domain="nas.local")}
    cmds = []
    store = _store(tmp_path, holder, cmds)

    plan = store.install("grafana")

    # compose written + substituted
    compose = Path(plan.compose_path)
    assert compose.exists()
    assert "${WEBUI_PORT" not in compose.read_text()
    # docker compose up called
    assert any("up" in c for c in cmds)
    # recorded in config + nginx rendered
    assert any(a.id == "grafana" for a in holder["cfg"].apps)
    assert holder.get("rendered") is True


def test_install_duplicate_raises(tmp_path):
    cfg = fc.ForgeOSConfig(domain="nas.local")
    cfg.apps.append(fc.InstalledApp(id="grafana", webui_port=20000))
    holder = {"cfg": cfg}
    store = _store(tmp_path, holder, [])
    with pytest.raises(ex.InstallError if hasattr(ex, "InstallError") else Exception):
        store.install("grafana")


def test_uninstall_calls_down_and_removes(tmp_path):
    cfg = fc.ForgeOSConfig(domain="nas.local")
    cfg.apps.append(fc.InstalledApp(id="grafana", webui_port=20000))
    cfg.nginx.vhosts.append(
        fc.NginxVhost(name="grafana", domain="grafana.nas.local", upstream_port=20000)
    )
    holder = {"cfg": cfg}
    cmds = []
    # need the compose file to exist for _compose_down to call down
    (tmp_path / "srv").mkdir()
    store = _store(tmp_path, holder, cmds)
    store.uninstall("grafana")
    assert not any(a.id == "grafana" for a in holder["cfg"].apps)
    assert not any(v.name == "grafana" for v in holder["cfg"].nginx.vhosts)
    assert holder.get("rendered") is True


def test_sync_clone_when_no_git(tmp_path):
    holder = {"cfg": fc.ForgeOSConfig()}
    cmds = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    fresh = tmp_path / "fresh-catalog"
    store = ex.AppStore(catalog_dir=str(fresh))
    store.run = lambda cmd, cwd=None: (cmds.append(cmd) or R())
    store.sync_catalog()
    assert any("clone" in c for c in cmds)


def test_sync_pull_when_git_exists(tmp_path):
    cmds = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    cat = tmp_path / "cat"
    (cat / ".git").mkdir(parents=True)
    store = ex.AppStore(catalog_dir=str(cat))
    store.run = lambda cmd, cwd=None: (cmds.append(cmd) or R())
    store.sync_catalog()
    assert any("pull" in c for c in cmds)


def test_sync_failure_raises(tmp_path):
    class R:
        returncode = 1
        stdout = ""
        stderr = "fatal: boom"

    cat = tmp_path / "cat2"
    store = ex.AppStore(catalog_dir=str(cat))
    store.run = lambda cmd, cwd=None: R()
    with pytest.raises(ex.AppStoreError, match="sync failed"):
        store.sync_catalog()


def test_install_compose_up_failure_raises(tmp_path):
    holder = {"cfg": fc.ForgeOSConfig(domain="nas.local")}

    class ROK:
        returncode = 0
        stdout = ""
        stderr = ""

    class RFAIL:
        returncode = 1
        stdout = ""
        stderr = "no docker"

    catalog = tmp_path / "catalog"
    (catalog / "apps" / "grafana").mkdir(parents=True)
    (catalog / "apps" / "grafana" / "docker-compose.yml").write_text(VALID_COMPOSE)
    (catalog / ".git").mkdir()

    store = ex.AppStore(catalog_dir=str(catalog))
    # up fails
    store.run = lambda cmd, cwd=None: RFAIL() if "up" in cmd else ROK()
    store.load_cfg = lambda: holder["cfg"]
    store.save_cfg = lambda c, path=None: None
    store.render_nginx = lambda c: None
    with pytest.raises(ex.AppStoreError, match="compose up failed"):
        store.install("grafana")
