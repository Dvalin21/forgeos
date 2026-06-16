"""Guard against packaging regressions that only show in an INSTALLED package.

The in-tree suite passes because templates sit on disk next to the code. A
real `pip install` is different — these tests assert the things that broke a
real install: templates present, CLI modules importable with main().
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_generator_templates_exist():
    # all four templates the generators load must exist on disk
    tdir = Path(__file__).resolve().parent.parent / "src" / "generators" / "templates"
    for name in ("smb_global.conf.j2", "smb_shares.conf.j2",
                 "nginx_vhost.conf.j2", "wireguard.conf.j2"):
        assert (tdir / name).exists(), f"missing template {name}"


def test_cli_modules_importable_with_main():
    # the console_scripts entry points target these modules' main()
    for mod_name in ("forgeos_generate_cli", "forgeos_app_cli"):
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "main"), f"{mod_name} has no main()"


def test_generate_cli_list(capsys):
    import forgeos_generate_cli as cli
    rc = cli.main(["--list"])
    assert rc == 0
    out = capsys.readouterr().out
    for svc in ("security", "samba", "nginx", "wireguard", "nfs"):
        assert svc in out
