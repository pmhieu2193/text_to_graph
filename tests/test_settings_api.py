from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import settings as settings_routes


def _client():
    app = FastAPI()
    app.include_router(settings_routes.router)
    return TestClient(app)


def test_settings_endpoint_masks_all_secret_values(monkeypatch):
    monkeypatch.setattr(settings_routes.settings, "llm_api_key", "gemini-secret")
    monkeypatch.setattr(settings_routes.settings, "llm_fallback_api_key", "backup-secret")
    monkeypatch.setattr(settings_routes.settings, "neo4j_password", "neo4j-secret")

    response = _client().get("/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_api_key"] == {"configured": True, "masked": "••••••••"}
    assert body["llm_fallback_api_key"] == {"configured": True, "masked": "••••••••"}
    assert body["neo4j_password"] == {"configured": True, "masked": "••••••••"}
    assert "gemini-secret" not in response.text
    assert "backup-secret" not in response.text
    assert "neo4j-secret" not in response.text


def test_blank_secret_fields_do_not_overwrite_existing_values(monkeypatch):
    captured = {}

    def fake_persist(values):
        captured.update(values)

    monkeypatch.setattr(settings_routes, "persist_runtime_settings", fake_persist)
    response = _client().put(
        "/settings",
        json={
            "llm_provider": "gemini",
            "llm_model": "gemini-2.5-flash",
            "llm_api_key": "",
            "llm_fallback_api_key": "",
            "neo4j_password": "",
            "neo4j_database": "neo4j",
        },
    )
    assert response.status_code == 200
    assert "llm_api_key" not in captured
    assert "llm_fallback_api_key" not in captured
    assert "neo4j_password" not in captured
    assert captured["llm_provider"] == "gemini"
    assert captured["llm_model"] == "gemini-2.5-flash"
