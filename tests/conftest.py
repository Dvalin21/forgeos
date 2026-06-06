"""
ForgeOS API test configuration.
Fixtures for all API test modules.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# Make src/ importable for all tests
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# Ensure filedb_api loads in mock mode — must be set before any module import
os.environ.setdefault("MOCK_FILEDB", "true")

# Provide a JWT secret BEFORE forgeos_auth is imported anywhere.
# forgeos_auth loads its secret at import time (module-level
# JWT_SECRET = _load_jwt_secret()), and refuses to import without a
# valid secret (C-001 hardening). Tests must supply one here, at
# conftest import — which runs before any test module imports the app.
# This is test-only; real deployments get their secret from the
# installer (99-finalize.sh) per C-001.
os.environ.setdefault("FORGEOS_JWT_SECRET", "test-secret-not-for-production")

# forgeos_pages_api resolves ALLOWED_ROOTS from FORGEOS_FILE_ROOTS at
# import time (default /srv/nas, which doesn't exist in CI). Point it at
# a session temp dir so file-station tests have a real, writable root.
_FILE_ROOT = tempfile.mkdtemp(prefix="forgeos-test-root-")
os.environ.setdefault("FORGEOS_FILE_ROOTS", _FILE_ROOT)

# Prevent tests from touching /etc/forgeos — use temp dirs instead
@pytest.fixture(autouse=True)
def _isolate_forgeos_config(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Replace /etc/forgeos paths with temp dirs so tests don't touch the system."""
    # Import after sys.path is set up
    import forgeos_auth

    with tempfile.TemporaryDirectory() as tmpdir:
        etc = Path(tmpdir) / "etc" / "forgeos"
        etc.mkdir(parents=True, exist_ok=True)

        # Create minimal forgeos.conf
        (etc / "forgeos.conf").write_text(
            'WEBUI_JWT_SECRET="test-secret-not-for-production"\n'
        )

        # Create empty api-users.json
        (etc / "api-users.json").write_text("{}")

        # Create filedb subdirectory
        (etc / "filedb").mkdir(parents=True, exist_ok=True)
        (etc / "filedb" / "filedb.conf").write_text(
            'SNAPSHOT_DEBOUNCE="30"\nMAX_SNAPSHOTS="48"\nWRITE_THRESHOLD="100"\n'
            'WATCH_ROOT="/tmp/test-srv-nas"\nAPI_PORT="12010"\n'
        )

        # Replace the module-level Path constants directly
        monkeypatch.setattr(forgeos_auth, "CONFIG_FILE", etc / "forgeos.conf")
        monkeypatch.setattr(forgeos_auth, "USERS_FILE", etc / "api-users.json")

        yield


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Return valid JWT auth headers (admin role)."""
    from forgeos_auth import create_token

    token = create_token("testadmin", "admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers() -> dict[str, str]:
    """Return valid JWT auth headers for a NON-admin user."""
    from forgeos_auth import create_token

    token = create_token("testuser", "user")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def file_root():
    """The session file-station root (from FORGEOS_FILE_ROOTS), cleaned per test."""
    root = Path(os.environ["FORGEOS_FILE_ROOTS"])
    root.mkdir(parents=True, exist_ok=True)
    # Clean contents before each test for isolation
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            import shutil as _sh
            _sh.rmtree(child)
        else:
            child.unlink()
    yield root


@pytest.fixture
def test_client() -> TestClient:
    """Test client against the full forgeos-api app.

    Note: the source file is forgeos-api.py (with a hyphen), so we
    must use importlib to load it — Python's import statement doesn't
    accept hyphens in module names.
    """
    import importlib.util as importlib_util

    api_path = str(Path(__file__).resolve().parent.parent / "src" / "forgeos-api.py")
    spec = importlib_util.spec_from_file_location("forgeos_api_module", api_path)
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return TestClient(mod.app)
