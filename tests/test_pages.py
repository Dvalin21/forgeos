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


class TestChmodScoped:
    """chmod with independent dir/file recursion (tree Permissions editor).

    The correct Unix pattern is dirs 755 / files 644 in ONE operation; the
    two scopes must be independently targetable and must not bleed into each
    other.
    """
    import stat as _stat

    def _tree(self, root):
        # root/sub/ , root/f1 , root/sub/f2  — start everything at 700/600
        import os
        sub = root / "sub"
        sub.mkdir()
        (root / "f1").write_text("a")
        (sub / "f2").write_text("b")
        os.chmod(root, 0o700); os.chmod(sub, 0o700)
        os.chmod(root / "f1", 0o600); os.chmod(sub / "f2", 0o600)
        return sub

    def _mode(self, p):
        import os
        return os.stat(p).st_mode & 0o777

    def test_requires_admin(self, test_client, user_headers, file_root):
        r = test_client.post("/api/files/chmod",
                             json={"path": str(file_root), "mode": "755"},
                             headers=user_headers)
        assert r.status_code == 403

    def test_apply_dirs_only_leaves_files(self, test_client, auth_headers, file_root):
        sub = self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "755",
                                   "apply_dirs": True, "apply_files": False})
        assert r.status_code == 200
        assert self._mode(file_root) == 0o755      # folder itself
        assert self._mode(sub) == 0o755            # subdir changed
        assert self._mode(file_root / "f1") == 0o600   # files UNTOUCHED
        assert self._mode(sub / "f2") == 0o600

    def test_apply_files_only_leaves_dirs(self, test_client, auth_headers, file_root):
        sub = self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "644",
                                   "apply_dirs": False, "apply_files": True})
        assert r.status_code == 200
        assert self._mode(sub) == 0o700            # subdir UNTOUCHED
        assert self._mode(file_root / "f1") == 0o644   # files changed
        assert self._mode(sub / "f2") == 0o644

    def test_separate_file_mode(self, test_client, auth_headers, file_root):
        # dirs 755, files 644 in one call — the canonical pattern
        sub = self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "755",
                                   "file_mode": "644",
                                   "apply_dirs": True, "apply_files": True})
        assert r.status_code == 200
        assert self._mode(sub) == 0o755
        assert self._mode(file_root / "f1") == 0o644
        assert self._mode(sub / "f2") == 0o644

    def test_recursive_alias_still_works(self, test_client, auth_headers, file_root):
        # the file-list editor sends recursive:true with a single mode
        sub = self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "755",
                                   "recursive": True})
        assert r.status_code == 200
        assert self._mode(sub) == 0o755
        assert self._mode(file_root / "f1") == 0o755   # both, single mode

    def test_non_recursive_single_target(self, test_client, auth_headers, file_root):
        sub = self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "750"})
        assert r.status_code == 200
        assert self._mode(file_root) == 0o750
        assert self._mode(sub) == 0o700            # nothing recursed

    def test_bad_file_mode_400(self, test_client, auth_headers, file_root):
        self._tree(file_root)
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": str(file_root), "mode": "755",
                                   "file_mode": "xyz", "apply_files": True})
        assert r.status_code == 400

    def test_traversal_rejected(self, test_client, auth_headers, file_root):
        r = test_client.post("/api/files/chmod", headers=auth_headers,
                             json={"path": "/etc", "mode": "777", "recursive": True})
        assert r.status_code == 403


class TestChownScoped:
    """chown independent dir/file recursion. Uses the invoking user's own
    name so the operation is permitted without root in the test env."""

    def _tree(self, root):
        sub = root / "sub"; sub.mkdir()
        (root / "f1").write_text("a"); (sub / "f2").write_text("b")
        return sub

    def test_requires_admin(self, test_client, user_headers, file_root):
        r = test_client.post("/api/files/chown",
                             json={"path": str(file_root), "owner": "root"},
                             headers=user_headers)
        assert r.status_code == 403

    def test_unknown_owner_400(self, test_client, auth_headers, file_root):
        self._tree(file_root)
        r = test_client.post("/api/files/chown", headers=auth_headers,
                             json={"path": str(file_root),
                                   "owner": "nosuchuser_zzz9"})
        assert r.status_code == 400

    def test_no_owner_or_group_400(self, test_client, auth_headers, file_root):
        r = test_client.post("/api/files/chown", headers=auth_headers,
                             json={"path": str(file_root), "owner": "", "group": ""})
        assert r.status_code == 400

    def test_same_owner_noop_succeeds_scoped(self, test_client, auth_headers, file_root):
        # chown to the current owner is a no-op that must still succeed and
        # exercise the scoped walk without needing root privileges.
        import getpass
        sub = self._tree(file_root)
        me = getpass.getuser()
        r = test_client.post("/api/files/chown", headers=auth_headers,
                             json={"path": str(file_root), "owner": me,
                                   "apply_dirs": True, "apply_files": True})
        assert r.status_code == 200

    def test_traversal_rejected(self, test_client, auth_headers, file_root):
        r = test_client.post("/api/files/chown", headers=auth_headers,
                             json={"path": "/etc", "owner": "root", "recursive": True})
        assert r.status_code == 403
