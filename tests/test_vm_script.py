"""scripts/vm.sh — the single entry point for talking to the test VM.

The install layout used to live only in the operator's head. That produced a
real failure: a deploy copied to dist-packages/forgeos-api.py while the
service actually runs /opt/forgeos/forgeos-api.py, and reported success.

These tests keep the script honest without needing the VM: valid syntax, a
manifest of real files, and - the important one - no password in the repo.
The VM-side behaviour (check / deploy / facts) is exercised by running it.
"""
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "vm.sh"


def test_vm_script_exists_and_parses():
    assert _SCRIPT.exists(), "scripts/vm.sh is missing"
    r = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, f"vm.sh has a syntax error:\n{r.stderr}"


def test_vm_script_manifest_points_at_real_files():
    """Every repo-relative path the manifest generates must exist. A typo or a
    deleted file would otherwise only surface as a failed deploy on the box."""
    text = _SCRIPT.read_text()
    assert "manifest()" in text, "manifest() disappeared from vm.sh"

    # the two explicitly listed entries, and the globbed asset dirs
    listed = re.findall(r"^(\S+)\t\$APP/", text, re.M)
    for rel in listed:
        assert (_ROOT / rel).exists(), f"manifest lists a missing file: {rel}"

    for pat in ("web/desktop/*.html", "web/desktop/js/*.js", "web/desktop/css/*.css"):
        assert list((_ROOT / pat).parent.glob(Path(pat).name)), \
            f"manifest globs {pat} but nothing matches"


def test_vm_password_never_appears_in_the_repo():
    """The real sudo password lives in ~/.config/forgeos/vm_sudo. Assert its
    exact content appears nowhere in the tree - checking the live value is
    the only version of this test that cannot be satisfied by a lookalike."""
    import os

    pw_file = Path(os.environ.get("FORGEOS_VM_PWFILE",
                                 Path.home() / ".config/forgeos/vm_sudo"))
    if not pw_file.exists():
        pytest.skip(f"no password file at {pw_file}")
    secret = pw_file.read_text().strip()
    if len(secret) < 6:
        pytest.skip("password file looks empty")

    offenders = []
    for f in _ROOT.rglob("*"):
        if not f.is_file() or ".git" in f.parts or ".venv" in f.parts:
            continue
        try:
            if secret in f.read_text(errors="ignore"):
                offenders.append(str(f.relative_to(_ROOT)))
        except OSError:
            continue
    assert offenders == [], f"the VM sudo password is committed in: {offenders}"


def test_vm_script_verifies_before_reporting_success():
    """deploy must verify (cmd_check) AND restart the API before reporting
    success. Both orderings are the whole point: a failed copy cannot print
    success, and a copy without a restart silently changes nothing (the
    header documents deploy as copy + restart + verify — it used to only
    copy, which read as success while the box ran old code)."""
    text = _SCRIPT.read_text()
    start = text.index("cmd_deploy() {")
    nxt = text.index("\ncmd_", start + 1) if "\ncmd_" in text[start + 1:] else start
    dep = text[start:start + (nxt - start if nxt != start else len(text))]
    i_check = dep.index("cmd_check")
    i_restart = dep.index("systemctl restart forgeos-api")
    i_success = dep.index('echo "API restarted and healthy"')
    assert i_check < i_restart < i_success, \
        "cmd_deploy must verify, then restart, and only then report success"
    assert "set -euo pipefail" in text, "vm.sh must run under set -euo pipefail"