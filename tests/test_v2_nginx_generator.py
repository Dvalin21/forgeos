"""Tests for the v2 nginx generator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.nginx import CONFD_DIR, VHOST_DIR, NginxGenerator  # noqa: E402


def _cfg(*vhosts):
    cfg = fc.ForgeOSConfig()
    cfg.nginx.vhosts = list(vhosts)
    return cfg


def _vhost_files(files):
    """Just the per-site vhost files (exclude the conf.d include)."""
    return [f for f in files if f.path.startswith(VHOST_DIR)]


def _first_vhost(cfg):
    return _vhost_files(NginxGenerator().render(cfg))[0].content


def test_disabled_renders_nothing():
    cfg = fc.ForgeOSConfig()
    cfg.nginx.enabled = False
    cfg.nginx.vhosts = [fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080)]
    assert NginxGenerator().render(cfg) == []


def test_no_vhosts_renders_nothing():
    assert NginxGenerator().render(fc.ForgeOSConfig()) == []


def test_emits_confd_include():
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    files = NginxGenerator().render(cfg)
    inc = [f for f in files if f.path == f"{CONFD_DIR}/forgeos.conf"]
    assert len(inc) == 1
    # the include must pull in our vhost dir (stock nginx ignores forgeos.d)
    assert f"include {VHOST_DIR}/*.conf;" in inc[0].content


def test_one_file_per_vhost():
    cfg = _cfg(
        fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080),
        fc.NginxVhost(name="grafana", domain="grafana.nas.local", upstream_port=3000),
    )
    paths = {f.path for f in _vhost_files(NginxGenerator().render(cfg))}
    assert paths == {f"{VHOST_DIR}/ui.conf", f"{VHOST_DIR}/grafana.conf"}


def test_vhost_has_upstream_and_servername():
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "server 127.0.0.1:5080;" in c
    assert "server_name nas.local;" in c
    assert "proxy_pass http://forgeos_ui;" in c


def test_websocket_emits_upgrade_headers():
    cfg = _cfg(fc.NginxVhost(name="ws", domain="ws.nas.local", upstream_port=8070, websocket=True))
    c = _first_vhost(cfg)
    assert "proxy_set_header Upgrade $http_upgrade;" in c
    assert 'proxy_set_header Connection "upgrade";' in c


def test_non_websocket_omits_upgrade_headers():
    cfg = _cfg(fc.NginxVhost(name="plain", domain="p.nas.local", upstream_port=8085))
    c = _first_vhost(cfg)
    assert "Upgrade $http_upgrade" not in c


def test_cert_falls_back_to_snakeoil_when_no_le(monkeypatch):
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "ssl-cert-snakeoil.pem" in c


def test_rejects_bad_port():
    with pytest.raises(ValueError):
        fc.NginxVhost(name="x", domain="d", upstream_port=99999)


def test_rejects_duplicate_vhosts():
    with pytest.raises(ValueError):
        fc.NginxConfig(vhosts=[
            fc.NginxVhost(name="ui", domain="a", upstream_port=80),
            fc.NginxVhost(name="UI", domain="b", upstream_port=81),
        ])


def test_apply_creates_vhost_dir(tmp_path, monkeypatch):
    import generators.nginx as ng
    monkeypatch.setattr(ng, "VHOST_DIR", str(tmp_path / "etc" / "nginx" / "forgeos.d"))
    monkeypatch.setattr(ng, "CONFD_DIR", str(tmp_path / "etc" / "nginx" / "conf.d"))
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    written = ng.NginxGenerator().apply(cfg, do_reload=False)
    assert (tmp_path / "etc" / "nginx" / "forgeos.d" / "ui.conf").exists()
    assert (tmp_path / "etc" / "nginx" / "conf.d" / "forgeos.conf").exists()
    # include file + one vhost
    assert len(written) == 2
