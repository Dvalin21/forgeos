"""Tests for the config-DB schema migration runner (V-012)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402


def test_migrate_v1_populates_naming_from_domain():
    v1 = {"version": 1, "domain": "nas.local"}
    out = fc.migrate(v1)
    assert out["version"] == 3
    assert out["naming"]["lan_name"] == "nas.local"
    assert out["naming"]["system_hostname"] == "nas"   # label before first dot
    assert out["naming"]["public_fqdn"] == ""


def test_migrate_no_version_treated_as_v1():
    # the very first schema shipped without an explicit version int
    out = fc.migrate({"domain": "home.local"})
    assert out["version"] == 3
    assert out["naming"]["lan_name"] == "home.local"


def test_migrate_is_idempotent_on_current_version():
    v3 = {"version": 3, "domain": "x.local",
          "naming": {"system_hostname": "x", "lan_name": "x.local", "public_fqdn": ""},
          "auth": {"require_totp_new_users": False}}
    out = fc.migrate(dict(v3))
    assert out == v3


def test_migrate_preserves_existing_naming_fields():
    # if a partial naming block already exists, don't clobber set fields
    v1 = {"version": 1, "domain": "nas.local",
          "naming": {"public_fqdn": "mail.example.com"}}
    out = fc.migrate(v1)
    assert out["naming"]["public_fqdn"] == "mail.example.com"   # kept
    assert out["naming"]["lan_name"] == "nas.local"             # filled


def test_migrate_unknown_version_raises():
    with pytest.raises(ValueError):
        fc.migrate({"version": 99})


def test_load_migrates_v1_file_in_memory(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"version": 1, "domain": "old.local"}))
    cfg = fc.load(p)
    assert cfg.version == 3
    assert cfg.naming.lan_name == "old.local"
    # load() does NOT rewrite the file
    assert json.loads(p.read_text())["version"] == 1


def test_load_and_upgrade_persists_migration(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"version": 1, "domain": "old.local"}))
    cfg = fc.load_and_upgrade(p)
    assert cfg.version == 3
    # the on-disk file is now upgraded
    on_disk = json.loads(p.read_text())
    assert on_disk["version"] == 3
    assert on_disk["naming"]["lan_name"] == "old.local"


def test_load_and_upgrade_writes_0600(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"version": 1, "domain": "old.local"}))
    fc.load_and_upgrade(p)
    assert (p.stat().st_mode & 0o777) == 0o600


def test_load_and_upgrade_noop_when_current(tmp_path):
    p = tmp_path / "config.json"
    cfg = fc.ForgeOSConfig(domain="cur.local")
    fc.save(cfg, p)
    before = p.stat().st_mtime_ns
    fc.load_and_upgrade(p)   # already v2 — must not rewrite
    assert p.stat().st_mtime_ns == before


def test_load_and_upgrade_missing_file_returns_defaults(tmp_path):
    p = tmp_path / "nope.json"
    cfg = fc.load_and_upgrade(p)
    assert cfg.version == fc.SCHEMA_VERSION
    assert not p.exists()   # wrote nothing


def test_storage_field_backward_compatible_no_bump():
    # adding storage must NOT break existing configs that lack the key — it
    # defaults to empty. (Such a config still migrates up to the current schema
    # like any old config; the storage field itself needed no migrator.)
    old = {"version": 2, "domain": "nas.local",
           "naming": {"system_hostname": "nas", "lan_name": "nas.local", "public_fqdn": ""}}
    cfg = fc.ForgeOSConfig.model_validate(fc.migrate(dict(old)))
    assert cfg.storage.pools == []
    assert cfg.version == 3


def test_storage_pool_validation_and_mountpoint():
    p = fc.StoragePool(name="tank", raid_level="raid1",
                       devices=["/dev/disk/by-id/a", "/dev/disk/by-id/b"])
    assert p.resolved_mountpoint() == "/srv/nas/tank"
    import pytest
    with pytest.raises(Exception):
        fc.StoragePool(name="x")  # too short
    with pytest.raises(Exception):
        fc.StorageConfig(pools=[p, p])  # duplicate names


def test_migrate_v2_to_v3_adds_auth_policy_default_off():
    v2 = {"version": 2, "domain": "x.local",
          "naming": {"system_hostname": "x", "lan_name": "x.local", "public_fqdn": ""}}
    out = fc.migrate(v2)
    assert out["version"] == 3
    cfg = fc.ForgeOSConfig.model_validate(out)
    assert cfg.auth.require_totp_new_users is False   # safe default


def test_migrate_v2_to_v3_preserves_existing_sections():
    v2 = {"version": 2, "domain": "x.local",
          "naming": {"system_hostname": "x", "lan_name": "x.local", "public_fqdn": ""},
          "samba": {"workgroup": "TESTWG"}}
    out = fc.migrate(v2)
    assert out["samba"]["workgroup"] == "TESTWG"   # untouched


def test_migrate_v2_to_v3_keeps_preset_auth_block():
    v2 = {"version": 2, "domain": "x.local",
          "naming": {"system_hostname": "x", "lan_name": "x.local", "public_fqdn": ""},
          "auth": {"require_totp_new_users": True}}
    out = fc.migrate(v2)
    assert out["auth"]["require_totp_new_users"] is True   # not clobbered


def test_default_config_is_current_schema_with_auth():
    cfg = fc.ForgeOSConfig()
    assert cfg.version == fc.SCHEMA_VERSION == 3
    assert cfg.auth.require_totp_new_users is False
