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
    """Just the per-site vhost files (exclude conf.d include + default-deny)."""
    return [f for f in files
            if f.path.startswith(VHOST_DIR) and not f.path.endswith("00-default-deny.conf")]


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
    assert "server_name nas.local" in c   # may also carry _ when default
    assert "proxy_pass http://forgeos_ui;" in c


def test_single_vhost_is_default_server():
    # A lone vhost must be default_server so the box answers on its IP and
    # localhost, not only its domain (the bug that 444'd real access).
    cfg = _cfg(fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080))
    c = _first_vhost(cfg)
    assert "default_server" in c
    assert "server_name nas.local _;" in c


def test_forgeos_ui_is_default_not_app_vhosts():
    # forgeos-ui owns the catch-all; app vhosts match only their server_name.
    cfg = _cfg(
        fc.NginxVhost(name="grafana", domain="grafana.nas.local", upstream_port=3000),
        fc.NginxVhost(name="forgeos-ui", domain="nas.local", upstream_port=5080),
    )
    files = {f.path.split("/")[-1]: f.content for f in NginxGenerator().render(cfg)}
    assert "default_server" in files["forgeos-ui.conf"]
    assert "default_server" not in files["grafana.conf"]


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
    # include + one vhost (no separate default-deny anymore — the UI vhost is
    # itself the default_server)
    assert len(written) == 2


def test_apply_removes_stale_vhosts(tmp_path, monkeypatch):
    # Regression: a stale 00-default-deny.conf (return 444, default_server)
    # left on disk after we stopped generating it kept dropping ALL traffic
    # (ERR_EMPTY_RESPONSE). apply() must reconcile forgeos.d/ — remove any
    # ForgeOS .conf it no longer produces.
    import sys
    sys.path.insert(0, "src")
    import generators.nginx as ng
    import forgeos_config as fc

    monkeypatch.setattr(ng, "VHOST_DIR", str(tmp_path))
    monkeypatch.setattr(ng, "CONFD_DIR", str(tmp_path))
    (tmp_path / "00-default-deny.conf").write_text("server { return 444; }")
    (tmp_path / "old-app.conf").write_text("server {}")

    cfg = fc.ForgeOSConfig()
    cfg.nginx.vhosts.append(
        fc.NginxVhost(name="forgeos-ui", domain="nas.local",
                      upstream_port=5080, websocket=True))
    gen = ng.NginxGenerator()
    gen.reload = lambda: None
    gen.apply(cfg, do_reload=False)

    names = {p.name for p in tmp_path.glob("*.conf")}
    assert "00-default-deny.conf" not in names   # stale dropper removed
    assert "old-app.conf" not in names           # stale app vhost removed
    assert "forgeos-ui.conf" in names            # current vhost kept
