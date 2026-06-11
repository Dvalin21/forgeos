"""Tests for the v2 WireGuard generator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators import GeneratorError  # noqa: E402
import generators.wireguard as wgmod  # noqa: E402
from generators.wireguard import WireGuardGenerator  # noqa: E402


def _enabled_cfg(*peers):
    cfg = fc.ForgeOSConfig()
    cfg.wireguard.enabled = True
    cfg.wireguard.peers = list(peers)
    return cfg


def _gen_with_key(tmp_path, monkeypatch, key="SERVERPRIVKEY="):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(wgmod, "WG_KEY_DIR", str(tmp_path))
    (tmp_path / "server.key").write_text(key + "\n")
    return WireGuardGenerator()


def test_disabled_renders_nothing():
    assert WireGuardGenerator().render(fc.ForgeOSConfig()) == []


def test_interface_block_uses_keystore_key(tmp_path, monkeypatch):
    gen = _gen_with_key(tmp_path, monkeypatch, key="ABC123KEY=")
    c = gen.render(_enabled_cfg())[0].content
    assert "PrivateKey = ABC123KEY=" in c
    assert "ListenPort = 51820" in c
    assert "Address    = 10.10.0.1/24" in c


def test_rendered_file_is_0600(tmp_path, monkeypatch):
    gen = _gen_with_key(tmp_path, monkeypatch)
    rf = gen.render(_enabled_cfg())[0]
    assert rf.mode == 0o600
    assert rf.path == "/etc/wireguard/wg0.conf"


def test_peers_rendered_as_peer_blocks(tmp_path, monkeypatch):
    gen = _gen_with_key(tmp_path, monkeypatch)
    cfg = _enabled_cfg(
        fc.WireGuardPeer(name="laptop", public_key="PUBKEY1=", address="10.10.0.2"),
        fc.WireGuardPeer(name="phone", public_key="PUBKEY2=", address="10.10.0.3/32"),
    )
    c = gen.render(cfg)[0].content
    assert "# peer: laptop" in c
    assert "PublicKey  = PUBKEY1=" in c
    assert "AllowedIPs = 10.10.0.2/32" in c
    assert "# peer: phone" in c
    assert "AllowedIPs = 10.10.0.3/32" in c


def test_no_peers_still_renders_interface(tmp_path, monkeypatch):
    gen = _gen_with_key(tmp_path, monkeypatch)
    c = gen.render(_enabled_cfg())[0].content
    assert "[Interface]" in c
    assert "[Peer]" not in c


def test_private_key_never_in_config_db():
    cfg = fc.WireGuardConfig()
    assert not hasattr(cfg, "private_key")
    peer = fc.WireGuardPeer(name="x", public_key="k=", address="10.10.0.9")
    assert not hasattr(peer, "private_key")


def test_validate_raises_when_server_key_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(wgmod, "WG_KEY_DIR", str(tmp_path))
    gen = WireGuardGenerator()
    files = gen.render(_enabled_cfg())
    with pytest.raises(GeneratorError):
        gen.validate(files)


def test_rejects_duplicate_peers():
    with pytest.raises(ValueError):
        fc.WireGuardConfig(peers=[
            fc.WireGuardPeer(name="a", public_key="k1", address="10.10.0.2"),
            fc.WireGuardPeer(name="A", public_key="k2", address="10.10.0.3"),
        ])


def test_apply_creates_dir_and_writes(tmp_path, monkeypatch):
    gen = _gen_with_key(tmp_path / "keys", monkeypatch)
    out = tmp_path / "etc" / "wireguard" / "wg0.conf"
    orig = gen.render
    def render_tmp(cfg):
        files = orig(cfg)
        return [wgmod.RenderedFile(path=str(out), content=files[0].content, mode=0o600)]
    monkeypatch.setattr(gen, "render", render_tmp)
    written = gen.apply(_enabled_cfg(), do_reload=False)
    assert out.exists()
    assert oct(out.stat().st_mode)[-3:] == "600"
