"""Integration tests: config DB -> registry -> apply all generators."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators import registry  # noqa: E402


def test_registry_lists_all_three():
    assert set(registry.names()) == {"security", "samba", "nginx", "wireguard", "nfs", "osbackup", "ufw", "updates"}


def test_get_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        registry.get("nope")


def test_apply_one_isolates_failure(monkeypatch):
    def boom(self, cfg, **kw):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(registry.SambaGenerator, "apply", boom, raising=False)
    r = registry.apply_one("samba", cfg=fc.ForgeOSConfig(), do_reload=False)
    assert r.ok is False
    assert "kaboom" in r.error


def test_apply_all_runs_every_service(tmp_path, monkeypatch):
    import generators.samba as sg
    import generators.nginx as ng
    import generators.security as secg

    monkeypatch.setattr(sg, "SMB_CONF", str(tmp_path / "samba" / "smb.conf"))
    monkeypatch.setattr(sg, "SHARES_FILE", str(tmp_path / "samba" / "shares.conf"))
    monkeypatch.setattr(ng, "VHOST_DIR", str(tmp_path / "nginx"))
    monkeypatch.setattr(ng, "CONFD_DIR", str(tmp_path / "confd"))
    monkeypatch.setattr(secg, "_have", lambda c: False)

    cfg = fc.ForgeOSConfig()
    cfg.samba.shares = [fc.SambaShare(name="data", path="/srv/nas/data")]
    cfg.nginx.vhosts = [fc.NginxVhost(name="ui", domain="nas.local", upstream_port=5080)]
    cfg.security.profile = "medium"

    orig_render = secg.SecurityGenerator.render
    def render_to_tmp(self, c):
        files = orig_render(self, c)
        return [secg.RenderedFile(path=str(tmp_path / "f2b.conf"),
                                  content=files[0].content, mode=files[0].mode)]
    monkeypatch.setattr(secg.SecurityGenerator, "render", render_to_tmp)

    results = registry.apply_all(cfg=cfg, do_reload=False)
    by = {r.service: r for r in results}
    assert by["samba"].ok and by["nginx"].ok and by["security"].ok
    assert (tmp_path / "samba" / "smb.conf").exists()
    assert (tmp_path / "nginx" / "ui.conf").exists()
    assert (tmp_path / "f2b.conf").exists()


def test_apply_all_continues_past_one_failure(monkeypatch):
    def boom(self, cfg, **kw):
        raise RuntimeError("x")
    monkeypatch.setattr(registry.NginxGenerator, "apply", boom, raising=False)
    monkeypatch.setattr(registry.SambaGenerator, "apply",
                        lambda self, cfg, **kw: [], raising=False)
    monkeypatch.setattr(registry.SecurityGenerator, "apply",
                        lambda self, cfg, **kw: [], raising=False)
    results = registry.apply_all(cfg=fc.ForgeOSConfig(), do_reload=False)
    by = {r.service: r.ok for r in results}
    assert by["nginx"] is False
    assert by["samba"] is True
    assert by["security"] is True
