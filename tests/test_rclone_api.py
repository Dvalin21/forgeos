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

def test_rclone_status():
    token = create_test_token()
    response = client.get("/api/backup/rclone/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "installed" in data

def test_rclone_configs():
    token = create_test_token()
    response = client.get("/api/backup/rclone/configs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "remotes" in data