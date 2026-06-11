"""Tests for app-store install/uninstall orchestration — pure parts."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
import forgeos_appstore as fa  # noqa: E402
import forgeos_appinstall as ai  # noqa: E402


def _manifest(app_id="grafana", main="grafana", image="grafana/grafana:11.4.0",
              port_map="3000"):
    text = textwrap.dedent(f"""
        name: {app_id}
        services:
          {main}:
            image: {image}
            ports:
              - target: 3000
                published: ${{WEBUI_PORT:-3000}}
            volumes:
              - type: bind
                source: /srv/forgeos/apps/${{APP_ID}}/data
                target: /var/lib/grafana
        x-forgeos:
          title: Grafana
          main: {main}
          port_map: "{port_map}"
    """).strip()
    return fa.parse_manifest(text)


def _fixed_alloc(port):
    return lambda used, preferred=None: port


def test_plan_install_basic():
    cfg = fc.ForgeOSConfig(domain="nas.local")
    plan = ai.plan_install(_manifest(), cfg, allocate=_fixed_alloc(20000))
    assert plan.app_id == "grafana"
    assert plan.webui_port == 20000
    assert plan.version == "11.4.0"
    assert plan.vhost_domain == "grafana.nas.local"
    assert plan.data_dir == "/srv/forgeos/apps/grafana"
    assert plan.env["WEBUI_PORT"] == "20000"
    assert plan.env["APP_ID"] == "grafana"


def test_plan_install_rejects_duplicate():
    cfg = fc.ForgeOSConfig()
    cfg.apps.append(fc.InstalledApp(id="grafana", webui_port=20000))
    with pytest.raises(ai.InstallError, match="already installed"):
        ai.plan_install(_manifest(), cfg, allocate=_fixed_alloc(20001))


def test_plan_install_avoids_used_ports():
    cfg = fc.ForgeOSConfig()
    cfg.apps.append(fc.InstalledApp(id="other", webui_port=20000))
    captured = {}

    def alloc(used, preferred=None):
        captured["used"] = used
        return 20001

    ai.plan_install(_manifest(), cfg, allocate=alloc)
    assert 20000 in captured["used"]


def test_apply_install_records_app_and_vhost():
    cfg = fc.ForgeOSConfig(domain="nas.local")
    plan = ai.plan_install(_manifest(), cfg, allocate=_fixed_alloc(20000))
    cfg2 = ai.apply_install_to_config(plan, cfg)
    assert any(a.id == "grafana" and a.webui_port == 20000 for a in cfg2.apps)
    vh = [v for v in cfg2.nginx.vhosts if v.name == "grafana"]
    assert len(vh) == 1
    assert vh[0].domain == "grafana.nas.local"
    assert vh[0].upstream_port == 20000


def test_apply_uninstall_removes_app_and_vhost():
    cfg = fc.ForgeOSConfig(domain="nas.local")
    plan = ai.plan_install(_manifest(), cfg, allocate=_fixed_alloc(20000))
    cfg = ai.apply_install_to_config(plan, cfg)
    cfg = ai.apply_uninstall_to_config("grafana", cfg)
    assert not any(a.id == "grafana" for a in cfg.apps)
    assert not any(v.name == "grafana" for v in cfg.nginx.vhosts)


def test_uninstall_unknown_raises():
    with pytest.raises(ai.InstallError, match="not installed"):
        ai.apply_uninstall_to_config("ghost", fc.ForgeOSConfig())


def test_render_compose_substitutes_vars():
    cfg = fc.ForgeOSConfig()
    m = _manifest()
    plan = ai.plan_install(m, cfg, allocate=_fixed_alloc(20000))
    out = ai.render_compose(m, plan)
    # WEBUI_PORT and APP_ID substituted; no raw ${...} left for them
    assert "20000" in out
    assert "${WEBUI_PORT" not in out
    assert "${APP_ID}" not in out
    assert "/srv/forgeos/apps/grafana/data" in out


def test_version_extracted_with_registry_port():
    m = _manifest(image="registry.example.com:5000/foo/bar:2.1", main="grafana")
    cfg = fc.ForgeOSConfig()
    plan = ai.plan_install(m, cfg, allocate=_fixed_alloc(20000))
    assert plan.version == "2.1"


def test_config_rejects_duplicate_apps():
    with pytest.raises(ValueError):
        fc.ForgeOSConfig(apps=[
            fc.InstalledApp(id="a", webui_port=20000),
            fc.InstalledApp(id="a", webui_port=20001),
        ])


def test_full_roundtrip_two_apps():
    cfg = fc.ForgeOSConfig(domain="nas.local")
    p1 = ai.plan_install(_manifest("grafana", "grafana"), cfg, allocate=_fixed_alloc(20000))
    cfg = ai.apply_install_to_config(p1, cfg)
    p2 = ai.plan_install(_manifest("prometheus", "prometheus",
                                   image="prom/prometheus:v2.54.1"),
                         cfg, allocate=_fixed_alloc(20001))
    cfg = ai.apply_install_to_config(p2, cfg)
    assert len(cfg.apps) == 2
    assert len(cfg.nginx.vhosts) == 2
    # uninstall one leaves the other intact
    cfg = ai.apply_uninstall_to_config("grafana", cfg)
    assert [a.id for a in cfg.apps] == ["prometheus"]
    assert [v.name for v in cfg.nginx.vhosts] == ["prometheus"]
