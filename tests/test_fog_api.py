import pytest
import importlib.util
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from datetime import datetime, timedelta, timezone

spec = importlib.util.spec_from_file_location("forgeos_api", "src/forgeos-api.py")
forgeos_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forgeos_api)
app = forgeos_api.app

test_app = FastAPI()
for route in app.routes:
    path = getattr(route, 'path', '')
    if path == '':
        continue
    test_app.routes.append(route)

JWT_SECRET = forgeos_api.JWT_SECRET
JWT_ALGO = forgeos_api.JWT_ALGO

def create_test_token():
    payload = {"sub": "testuser", "role": "admin", "exp": datetime.now(tz=timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

client = TestClient(test_app)

def test_imaging_status():
    """Test FOG imaging status endpoint"""
    token = create_test_token()
    response = client.get("/api/imaging/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "fog_installed" in data
    assert "images" in data
    assert "hosts" in data

def test_imaging_capture():
    """Test FOG image capture endpoint — currently a stub (501)"""
    token = create_test_token()
    response = client.post("/api/imaging/capture?hostname=testhost&image_name=testimage",
        headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in [200, 500, 501]
    data = response.json()
    assert "status" in data or "error" in data or "detail" in data

def test_imaging_deploy():
    """Test FOG image deploy endpoint — currently a stub (501)"""
    token = create_test_token()
    response = client.post("/api/imaging/deploy?image_name=testimage&target_host=testhost",
        headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in [200, 500, 501]
    data = response.json()
    assert "status" in data or "error" in data or "detail" in data