"""Tests for the forgeos-storage CLI (guarded pool ops)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_storage_cli as cli  # noqa: E402
import forgeos_diskprep as dp      # noqa: E402

_FAKE = {"blockdevices": [
    {"name": "sda", "type": "disk", "size": 34359738368},
    {"name": "sdb", "type": "disk", "size": 34359738368,
     "children": [{"name": "sdb1", "fstype": "ext4", "mountpoint": "/"}]},
    {"name": "sdc", "type": "disk", "size": 34359738368},
]}


@pytest.fixture
def fake_disks(monkeypatch):
    monkeypatch.setattr(dp, "_run", lambda cmd: json.dumps(_FAKE))


def test_disks_lists_system_and_blank(fake_disks, capsys):
    assert cli.main(["disks"]) == 0
    out = capsys.readouterr().out
    assert "sdb" in out and "SYSTEM" in out
    assert "sda" in out and "BLANK" in out


def test_plan_blank_disks_ok(fake_disks, capsys):
    assert cli.main(["plan", "tank", "raid1", "sda", "sdc"]) == 0
    out = capsys.readouterr().out
    assert "mkfs.btrfs" in out and "raid1" in out
    assert "no changes made" in out


def test_plan_refuses_system_disk(fake_disks):
    assert cli.main(["plan", "tank", "raid1", "sda", "sdb"]) == 2


def test_plan_refuses_too_few_disks(fake_disks):
    assert cli.main(["plan", "tank", "raid10", "sda", "sdc"]) == 2  # raid10 needs 4
