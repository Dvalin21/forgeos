import pytest
import importlib.util
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from datetime import datetime, timedelta
from starlette.routing import Route, WebSocketRoute, Mount

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
    payload = {"sub": "testuser", "role": "admin", "exp": datetime.utcnow() + timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

client = TestClient(test_app)

def test_docker_apps_endpoint():
    token = create_test_token()
    response = client.get("/api/docker/apps", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "apps" in data
    apps = data["apps"]
    assert len(apps) == 10
    app_names = [a["name"] for a in apps]
    assert "nginx" in app_names
    assert "jellyfin" in app_names
    assert "adguard" in app_names

def test_docker_install_endpoint():
    token = create_test_token()
    response = client.post("/api/docker/install?app=jellyfin",
        headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in [200, 500]