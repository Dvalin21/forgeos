"""Tests for the v2 NFS generator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.nfs import NfsGenerator  # noqa: E402


def _cfg(*exports, cidr="10.0.0.0/24"):
    cfg = fc.ForgeOSConfig()
    cfg.nfs.enabled = True
    cfg.nfs.lan_cidr = cidr
    cfg.nfs.exports = list(exports)
    return cfg


def test_disabled_renders_nothing():
    assert NfsGenerator().render(fc.ForgeOSConfig()) == []


def test_enabled_emits_v4_root():
    c = NfsGenerator().render(_cfg())[0].content
    assert "/srv/nas 10.0.0.0/24(rw,fsid=0," in c


def test_rw_export_options():
    c = NfsGenerator().render(
        _cfg(fc.NfsExport(path="/srv/nas/data", type="rw"))
    )[0].content
    assert "/srv/nas/data 10.0.0.0/24(rw,no_subtree_check,no_root_squash,async,sec=sys)" in c


def test_ro_export_options():
    c = NfsGenerator().render(
        _cfg(fc.NfsExport(path="/srv/nas/media", type="ro"))
    )[0].content
    assert "/srv/nas/media 10.0.0.0/24(ro,no_subtree_check,root_squash,async,sec=sys)" in c


def test_public_export_all_squash():
    c = NfsGenerator().render(
        _cfg(fc.NfsExport(path="/srv/nas/public", type="public"))
    )[0].content
    assert "all_squash" in c


def test_backup_export_is_sync():
    c = NfsGenerator().render(
        _cfg(fc.NfsExport(path="/srv/nas/backups", type="backup"))
    )[0].content
    assert "/srv/nas/backups" in c
    assert "sync,sec=sys" in c


def test_custom_cidr_used():
    c = NfsGenerator().render(
        _cfg(fc.NfsExport(path="/srv/nas/data"), cidr="192.168.1.0/24")
    )[0].content
    assert "192.168.1.0/24" in c
    assert "10.0.0.0/24" not in c


def test_rejects_relative_export_path():
    with pytest.raises(ValueError):
        fc.NfsExport(path="relative")


def test_rejects_duplicate_export_paths():
    with pytest.raises(ValueError):
        fc.NfsConfig(exports=[
            fc.NfsExport(path="/srv/nas/data"),
            fc.NfsExport(path="/srv/nas/data"),
        ])


def test_renders_to_etc_exports():
    rf = NfsGenerator().render(_cfg())[0]
    assert rf.path == "/etc/exports.d/forgeos.exports"
