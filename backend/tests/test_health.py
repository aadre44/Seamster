from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_skirt_types():
    response = client.get("/api/skirt-types")
    assert response.status_code == 200
    data = response.json()
    assert "straight" in data["silhouettes"]
    assert len(data["silhouettes"]) == 7
