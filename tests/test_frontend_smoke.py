"""Bridge: run the jsdom frontend smoke test from pytest.

network.js is browser code — the Python suite never executes it, so a handler
that's wired but undefined (a ReferenceError in init) sails through every
Python test and only surfaces as a frozen page in the browser. This runs the
jsdom harness that actually executes init().

Skips cleanly when node or jsdom isn't available so a fresh gate clone (which
installs Python deps only) stays green; it runs wherever the JS tooling is
present (dev, CI with `npm ci`).
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HARNESS = _ROOT / "tests" / "frontend" / "network_init.test.js"
_NAV_HARNESS = _ROOT / "tests" / "frontend" / "nav_scroll.test.js"
_HEALTH_HARNESS = _ROOT / "tests" / "frontend" / "health_truth.test.js"


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


@pytest.mark.skipif(not _node_with_jsdom(),
                    reason="node or jsdom unavailable (frontend tooling not installed)")
def test_nav_scroll_position_logic():
    r = subprocess.run(["node", str(_NAV_HARNESS)], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"nav.js scroll test failed:\n{r.stderr}\n{r.stdout}"


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="node unavailable")
def test_storage_health_is_one_shared_verdict():
    """js/health.js is the single storage-health verdict. Sidebar, dashboard
    and Storage chip all read it; if they ever disagree again the green chip
    lies about the box, so the rules are pinned here."""
    r = subprocess.run(["node", str(_HEALTH_HARNESS)], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"health.js verdict test failed:\n{r.stderr}\n{r.stdout}"


def test_health_js_loaded_on_every_page():
    """ForgeHealth must exist before any page calls it. A page missing the
    script tag throws ReferenceError at runtime — invisible to every Python
    test, fatal in the browser."""
    pages = sorted((_ROOT / "web" / "desktop").glob("*.html"))
    assert pages, "no desktop pages found"
    missing = [p.name for p in pages if "js/health.js" not in p.read_text()]
    assert missing == [], f"pages not loading health.js: {missing}"


def test_shares_nfs_panel_wired_end_to_end():
    """The NFS panel is markup + handlers + API. Any one of the three missing
    renders a dead button that looks alive. Pin all three at once."""
    html = (_ROOT / "web" / "desktop" / "shares.html").read_text()
    js = (_ROOT / "web" / "desktop" / "js" / "shares.js").read_text()

    # 1. every id shares.js reaches for must exist in the markup
    ids = set(re.findall(r"\$\('#([a-z0-9-]+)'\)", js))
    absent = sorted(i for i in ids if f'id="{i}"' not in html)
    assert absent == [], f"shares.js queries ids not present in shares.html: {absent}"

    # 2. the panel is wired and called on load
    assert "loadNfs()" in js, "NFS never loads on page open"
    for hook in ("nfs-enable", "nfs-off-btn", "nfs-add", "nfs-save"):
        assert f"$('#{hook}')" in js, f"{hook} has no handler"

    # 3. it talks to the endpoints that actually exist
    assert "'/api/nfs'" in js and "'/api/nfs/toggle'" in js
