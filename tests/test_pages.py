"""Tests for forgeos_pages_api.py file-station routes (C-004 part 2).

Targets the /api/files/* route group — the most-used and most dangerous
routes in pages_api (they touch the filesystem). Scope per the registry
is regression-prevention, not exhaustive coverage of all 42 routes.

Covered:
  GET  /api/files/roots     (auth)
  GET  /api/files/list      (auth)
  POST /api/files/mkdir     (admin)
  POST /api/files/rename    (admin)
  POST /api/files/delete    (admin)

Security focus: _safe() path sanitization must reject traversal outside
ALLOWED_ROOTS, and mutations must require admin.
"""
from __future__ import annotations

import pytest


class TestFileRoots:
    def test_requires_auth(self, test_client):
        resp = test_client.get("/api/files/roots")
        assert resp.status_code in (401, 403)

    def test_returns_roots(self, test_client, auth_headers, file_root):
        resp = test_client.get("/api/files/roots", headers=auth_headers)
        assert resp.status_code == 200
        roots = resp.json()["roots"]
        assert str(file_root) in roots


class TestFileList:
    def test_requires_auth(self, test_client):
        resp = test_client.get("/api/files/list")
        assert resp.status_code in (401, 403)

    def test_lists_directory_contents(self, test_client, auth_headers, file_root):
        (file_root / "alpha.txt").write_text("hi")
        (file_root / "subdir").mkdir()
        resp = test_client.get(
            "/api/files/list", params={"path": str(file_root)}, headers=auth_headers
        )
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()["entries"]]
        assert "alpha.txt" in names
        assert "subdir" in names

    def test_dirs_sorted_before_files(self, test_client, auth_headers, file_root):
        (file_root / "zzz.txt").write_text("x")
        (file_root / "aaa_dir").mkdir()
        resp = test_client.get(
            "/api/files/list", params={"path": str(file_root)}, headers=auth_headers
        )
        types = [e["type"] for e in resp.json()["entries"]]
        # First entry should be the directory
        assert types[0] == "dir"

    def test_missing_path_404(self, test_client, auth_headers, file_root):
        resp = test_client.get(
            "/api/files/list",
            params={"path": str(file_root / "does-not-exist")},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_traversal_outside_root_rejected(self, test_client, auth_headers, file_root):
        # Attempt to escape the root with ../../etc
        resp = test_client.get(
            "/api/files/list", params={"path": "/etc"}, headers=auth_headers
        )
        assert resp.status_code == 403

    def test_returns_breadcrumbs(self, test_client, auth_headers, file_root):
        (file_root / "deep").mkdir()
        resp = test_client.get(
            "/api/files/list", params={"path": str(file_root / "deep")},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "crumbs" in resp.json()
        assert len(resp.json()["crumbs"]) >= 1


class TestFileMkdir:
    def test_requires_auth(self, test_client):
        resp = test_client.post("/api/files/mkdir", json={"path": "/", "name": "x"})
        assert resp.status_code in (401, 403)

    def test_requires_admin(self, test_client, user_headers, file_root):
        resp = test_client.post(
            "/api/files/mkdir",
            json={"path": str(file_root), "name": "newdir"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_creates_directory(self, test_client, auth_headers, file_root):
        resp = test_client.post(
            "/api/files/mkdir",
            json={"path": str(file_root), "name": "created"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert (file_root / "created").is_dir()

    def test_empty_name_rejected(self, test_client, auth_headers, file_root):
        resp = test_client.post(
            "/api/files/mkdir",
            json={"path": str(file_root), "name": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_name_sanitized(self, test_client, auth_headers, file_root):
        # Dangerous chars replaced with _
        resp = test_client.post(
            "/api/files/mkdir",
            json={"path": str(file_root), "name": "bad/../name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # The slash and dots get sanitized to underscores; no traversal
        created = list(file_root.iterdir())
        assert len(created) == 1
        assert "/" not in created[0].name


class TestFileRename:
    def test_requires_admin(self, test_client, user_headers, file_root):
        (file_root / "orig.txt").write_text("x")
        resp = test_client.post(
            "/api/files/rename",
            json={"src": str(file_root / "orig.txt"), "name": "renamed.txt"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_renames_file(self, test_client, auth_headers, file_root):
        (file_root / "before.txt").write_text("data")
        resp = test_client.post(
            "/api/files/rename",
            json={"src": str(file_root / "before.txt"), "name": "after.txt"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert not (file_root / "before.txt").exists()
        assert (file_root / "after.txt").exists()

    def test_empty_new_name_rejected(self, test_client, auth_headers, file_root):
        (file_root / "x.txt").write_text("d")
        resp = test_client.post(
            "/api/files/rename",
            json={"src": str(file_root / "x.txt"), "name": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestFileDelete:
    def test_requires_admin(self, test_client, user_headers, file_root):
        (file_root / "victim.txt").write_text("x")
        resp = test_client.post(
            "/api/files/delete",
            json={"path": str(file_root / "victim.txt")},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_deletes_file(self, test_client, auth_headers, file_root):
        (file_root / "trash.txt").write_text("x")
        resp = test_client.post(
            "/api/files/delete",
            json={"path": str(file_root / "trash.txt")},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert not (file_root / "trash.txt").exists()

    def test_refuses_to_delete_root(self, test_client, auth_headers, file_root):
        resp = test_client.post(
            "/api/files/delete",
            json={"path": str(file_root)},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_deletes_directory_recursively(self, test_client, auth_headers, file_root):
        d = file_root / "fulldir"
        d.mkdir()
        (d / "inner.txt").write_text("x")
        resp = test_client.post(
            "/api/files/delete",
            json={"path": str(d)},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert not d.exists()
