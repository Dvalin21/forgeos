"""Bridge: run the jsdom frontend smoke test from pytest.

network.js is browser code — the Python suite never executes it, so a handler
that's wired but undefined (a ReferenceError in init) sails through every
Python test and only surfaces as a frozen page in the browser. This runs the
jsdom harness that actually executes init().

Skips cleanly when node or jsdom isn't available so a fresh gate clone (which
installs Python deps only) stays green; it runs wherever the JS tooling is
present (dev, CI with `npm ci`).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HARNESS = _ROOT / "tests" / "frontend" / "network_init.test.js"


def _node_with_jsdom() -> bool:
    if shutil.which("node") is None or not _HARNESS.exists():
        return False
    try:
        r = subprocess.run(["node", "-e", "require('jsdom')"],
                           cwd=str(_ROOT), capture_output=True, timeout=20)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.mark.skipif(not _node_with_jsdom(),
                    reason="node or jsdom unavailable (frontend tooling not installed)")
def test_network_js_init_runs_without_reference_error():
    r = subprocess.run(["node", str(_HARNESS)], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"network.js init() failed:\n{r.stderr}\n{r.stdout}"
