"""Tests for the forgeos-osbackup CLI (DR control)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_osbackup_cli as cli  # noqa: E402


def test_status_runs_with_defaults(capsys):
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "osbackup enabled in config" in out
    assert "rear installed" in out


def test_run_refuses_when_disabled():
    # default config has osbackup.enabled = False -> argparse error (exit 2)
    with pytest.raises(SystemExit) as e:
        cli.main(["run"])
    assert e.value.code == 2


def test_enable_rejects_root_filesystem_path(tmp_path, monkeypatch):
    # enable must refuse a backup path on the root filesystem (ReaR would too)
    import forgeos_config as fc
    cfgfile = tmp_path / "config.json"
    fc.save(fc.ForgeOSConfig(), cfgfile)
    monkeypatch.setattr(fc, "CONFIG_PATH", cfgfile)
    # rear present (so we reach the path check), path on root -> reject
    monkeypatch.setattr(cli, "_require_rear", lambda: None)
    rc = cli.main(["enable", "--backup-path", "/etc/forgeos/osbackup"])
    assert rc == 2   # rejected


def test_reject_root_path_helper():
    assert cli._reject_root_path("") is not None
    assert cli._reject_root_path("/etc/x") is not None   # on root fs


def test_osbackup_modules_importable():
    # regression: forgeos_osbackup + its CLI must be importable (they were
    # missing from py-modules, so installs didn't ship them).
    import importlib
    assert importlib.import_module("forgeos_osbackup")
    assert importlib.import_module("forgeos_osbackup_cli")
