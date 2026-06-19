"""Tests for the v2 ReaR (osbackup) generator + config."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.rear import REAR_CONF, RearGenerator  # noqa: E402


def _cfg(**over):
    cfg = fc.ForgeOSConfig()
    cfg.osbackup.enabled = True
    for k, v in over.items():
        setattr(cfg.osbackup, k, v)
    return cfg


# ---- config validation ----

def test_osbackup_default_disabled():
    assert fc.ForgeOSConfig().osbackup.enabled is False


def test_rejects_root_backup_path():
    for bad in ("/", "/etc", "/var", "/home", "/boot"):
        with pytest.raises(ValueError):
            fc.OsBackupConfig(backup_path=bad)


def test_rejects_relative_backup_path():
    with pytest.raises(ValueError):
        fc.OsBackupConfig(backup_path="relative/path")


def test_accepts_dedicated_disk_path():
    c = fc.OsBackupConfig(backup_path="/mnt/backup/osbackup")
    assert c.backup_path == "/mnt/backup/osbackup"


def test_output_must_be_iso_or_usb():
    with pytest.raises(ValueError):
        fc.OsBackupConfig(output="floppy")


# ---- generator render ----

def test_disabled_renders_nothing():
    assert RearGenerator().render(fc.ForgeOSConfig()) == []


def test_renders_local_conf():
    files = RearGenerator().render(_cfg())
    assert len(files) == 1
    assert files[0].path == REAR_CONF
    assert files[0].mode == 0o600


def test_backup_url_is_file_scheme():
    c = _cfg(backup_path="/mnt/backup/osbackup")
    out = RearGenerator().render(c)[0].content
    assert "BACKUP_URL=file:///mnt/backup/osbackup" in out
    assert "BACKUP=NETFS" in out


def test_output_iso_vs_usb():
    iso = RearGenerator().render(_cfg(output="ISO"))[0].content
    usb = RearGenerator().render(_cfg(output="USB"))[0].content
    assert "OUTPUT=ISO" in iso
    assert "OUTPUT=USB" in usb


def test_excludes_data_pool_and_backup_target():
    c = _cfg(backup_path="/mnt/backup/osbackup")
    out = RearGenerator().render(c)[0].content
    assert '/srv/nas/*' in out
    assert '/mnt/backup/osbackup/*' in out


def test_oncalendar_mapping():
    g = RearGenerator()
    assert g.oncalendar(_cfg(schedule="weekly")).startswith("Sun")
    assert g.oncalendar(_cfg(schedule="daily")) == "*-*-* 02:30:00"
    # raw OnCalendar passes through
    assert g.oncalendar(_cfg(schedule="*-*-15 03:00:00")) == "*-*-15 03:00:00"


def test_apply_writes_0600(tmp_path, monkeypatch):
    import generators.rear as rr
    target = tmp_path / "etc" / "rear" / "local.conf"
    monkeypatch.setattr(rr, "REAR_CONF", str(target))
    written = rr.RearGenerator().apply(_cfg(), do_reload=False)
    assert target.exists()
    assert oct(target.stat().st_mode)[-3:] == "600"
    assert str(target) in written


def test_registered_in_registry():
    from generators import registry
    assert "osbackup" in registry.names()


def test_rear_config_uses_zstd_program_not_gz_suffix():
    # regression: bare BACKUP_PROG_COMPRESS_OPTIONS=( --zstd ) made ReaR append
    # .gz, producing backup.tar.zst.gz. The fix sets COMPRESS_PROGRAM=zstd.
    import sys
    sys.path.insert(0, "src")
    import forgeos_config as fc
    from generators.rear import RearGenerator
    cfg = fc.ForgeOSConfig()
    cfg.osbackup.enabled = True
    cfg.osbackup.backup_path = "/mnt/backup/osbackup"
    blob = " ".join(f.content for f in RearGenerator().render(cfg))
    assert 'BACKUP_PROG_COMPRESS_PROGRAM="zstd"' in blob
    assert "( --zstd )" not in blob          # the buggy form is gone
    assert 'BACKUP_PROG_SUFFIX=".tar.zst"' in blob
