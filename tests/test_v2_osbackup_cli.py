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


def test_enable_refuses_when_disabled():
    with pytest.raises(SystemExit) as e:
        cli.main(["enable"])
    assert e.value.code == 2


def test_osbackup_modules_importable():
    # regression: forgeos_osbackup + its CLI must be importable (they were
    # missing from py-modules, so installs didn't ship them).
    import importlib
    assert importlib.import_module("forgeos_osbackup")
    assert importlib.import_module("forgeos_osbackup_cli")
