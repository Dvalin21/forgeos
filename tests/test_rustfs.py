"""Tests for rustfs_api.py routes (C-004 part 1).

rustfs_api requires boto3 (imported at module level). On systems without
boto3, the main app skips the router entirely. These tests skip
gracefully if boto3 is absent.

We mock get_s3_client() so no live RustFS/S3 server is needed.

Note: ForgeOS enforces auth on all endpoints except /api/auth/login and
/health, so these tests send auth_headers for protected routes and
verify 401/403 without them.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3", reason="rustfs_api requires boto3")


@pytest.fixture
def mock_s3():
    import rustfs_api
    fake = MagicMock()
    with patch.object(rustfs_api, "get_s3_client", return_value=fake):
        yield fake


class TestBucketsAuth:
    def test_list_buckets_requires_auth(self, test_client, mock_s3):
        resp = test_client.get("/api/storage/buckets")
        assert resp.status_code in (401, 403)

    def test_create_bucket_requires_auth(self, test_client, mock_s3):
        resp = test_client.post("/api/storage/buckets/x")
        assert resp.status_code in (401, 403)


class TestBuckets:
    def test_list_buckets_returns_names(self, test_client, auth_headers, mock_s3):
        mock_s3.list_buckets.return_value = {
            "Buckets": [
                {"Name": "photos", "CreationDate": datetime(2026, 1, 1)},
                {"Name": "backups", "CreationDate": datetime(2026, 2, 1)},
            ]
        }
        resp = test_client.get("/api/storage/buckets", headers=auth_headers)
        assert resp.status_code == 200
        names = [b["name"] for b in resp.json()["buckets"]]
        assert names == ["photos", "backups"]

    def test_list_buckets_error_returns_500(self, test_client, auth_headers, mock_s3):
        mock_s3.list_buckets.side_effect = Exception("boom")
        resp = test_client.get("/api/storage/buckets", headers=auth_headers)
        assert resp.status_code == 500

    def test_create_bucket(self, test_client, auth_headers, mock_s3):
        resp = test_client.post("/api/storage/buckets/newbucket", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "bucket": "newbucket"}
        mock_s3.create_bucket.assert_called_once_with(Bucket="newbucket")

    def test_create_bucket_error_returns_500(self, test_client, auth_headers, mock_s3):
        mock_s3.create_bucket.side_effect = Exception("exists")
        resp = test_client.post("/api/storage/buckets/dupe", headers=auth_headers)
        assert resp.status_code == 500

    def test_delete_bucket(self, test_client, auth_headers, mock_s3):
        resp = test_client.delete("/api/storage/buckets/oldbucket", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "bucket": "oldbucket"}
        mock_s3.delete_bucket.assert_called_once_with(Bucket="oldbucket")


class TestObjects:
    def test_list_objects_returns_keys(self, test_client, auth_headers, mock_s3):
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "a.txt", "Size": 100, "LastModified": datetime(2026, 1, 1)},
                {"Key": "b.txt", "Size": 200, "LastModified": datetime(2026, 1, 2)},
            ]
        }
        resp = test_client.get("/api/storage/buckets/mybucket/objects", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "mybucket"
        keys = [o["key"] for o in data["objects"]]
        assert keys == ["a.txt", "b.txt"]

    def test_list_objects_empty_bucket(self, test_client, auth_headers, mock_s3):
        mock_s3.list_objects_v2.return_value = {}
        resp = test_client.get("/api/storage/buckets/empty/objects", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["objects"] == []

    def test_list_objects_error_returns_500(self, test_client, auth_headers, mock_s3):
        mock_s3.list_objects_v2.side_effect = Exception("no such bucket")
        resp = test_client.get("/api/storage/buckets/ghost/objects", headers=auth_headers)
        assert resp.status_code == 500

    def test_delete_object(self, test_client, auth_headers, mock_s3):
        resp = test_client.delete(
            "/api/storage/buckets/b/objects/file.txt", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["key"] == "file.txt"
        mock_s3.delete_object.assert_called_once()
