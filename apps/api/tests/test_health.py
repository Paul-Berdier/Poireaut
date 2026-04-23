"""Test the /health endpoint."""
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "poireaut-api"


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "poireaut-api"
