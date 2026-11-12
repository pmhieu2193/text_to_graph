from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import entity_resolution as routes
from app.core.database import get_db


def _client():
    app = FastAPI()
    app.include_router(routes.router)

    def fake_db():
        return object()

    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_candidates_endpoint_is_document_scoped_without_run_id(monkeypatch):
    class FakeERService:
        def __init__(self, _db):
            pass

        def get_current_run(self, document_id):
            assert document_id == "DOC-1"
            return SimpleNamespace(id="RUN-1")

        def list_candidates(self, document_id):
            assert document_id == "DOC-1"
            return []

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    client = _client()

    response = client.get("/documents/DOC-1/entity-resolution/candidates")
    assert response.status_code == 200
    assert response.json() == {
        "document_id": "DOC-1",
        "run_id": "RUN-1",
        "items": [],
    }

    legacy_response = client.get(
        "/documents/DOC-1/entity-resolution/runs/RUN-1/candidates"
    )
    assert legacy_response.status_code == 404


def test_decision_endpoint_has_typed_response_model(monkeypatch):
    class FakeERService:
        def __init__(self, _db):
            pass

        def decide(self, document_id, pair_id, decision):
            assert (document_id, pair_id, decision) == ("DOC-1", "PAIR-1", "SKIP")
            return {
                "pair_id": pair_id,
                "decision": decision,
                "review_status": "SKIPPED",
                "canonical_entity_id": None,
            }

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    response = _client().post(
        "/documents/DOC-1/entity-resolution/candidates/PAIR-1/decision",
        json={"decision": "SKIP"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "SKIPPED"
