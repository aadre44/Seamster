from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    # Reports the active LLM provider/model so config is verifiable without a frontend.
    assert data["llm_provider"] in {"anthropic", "ollama"}
    assert "llm_model" in data


def test_skirt_types():
    response = client.get("/api/skirt-types")
    assert response.status_code == 200
    data = response.json()
    assert "straight" in data["silhouettes"]
    assert len(data["silhouettes"]) == 7
