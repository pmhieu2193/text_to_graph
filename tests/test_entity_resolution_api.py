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

def test_auto_merge_finalize_and_sync_routes_do_not_require_run_id(monkeypatch):
    class FakeERService:
        def __init__(self, _db):
            pass

        def auto_merge(self, document_id):
            return {
                "run_id": "RUN-1",
                "auto_candidates": 2,
                "merged_or_already_same_cluster": 2,
                "blocked_by_keep_separate": 0,
            }

        def finalize(self, document_id):
            return {
                "document_id": document_id,
                "run_id": "RUN-1",
                "status": "FINALIZED",
                "candidate_count": 0,
                "merged_count": 0,
                "kept_separate_count": 0,
                "skipped_count": 0,
                "blocked_conflict_count": 0,
                "canonical_entity_count": 0,
                "canonical_relation_count": 0,
                "deduplicated_relation_count": 0,
                "removed_self_loop_count": 0,
                "auto_candidates": 0,
                "merged_or_already_same_cluster": 0,
                "blocked_by_keep_separate": 0,
                "defaulted_to_skip": 0,
                "report_path": "report.xlsx",
                "canonical_entities": [],
                "canonical_relations": [],
            }

    class FakeNeo4jSyncService:
        def __init__(self, _db):
            pass

        def sync(self, document_id):
            return {
                "document_id": document_id,
                "run_id": "RUN-1",
                "sync_status": "SYNCED",
                "node_count": 1,
                "relation_count": 0,
                "removed_self_loop_count": 0,
                "cypher_path": "neo4j_sync.txt",
            }

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    monkeypatch.setattr(routes, "Neo4jGraphSyncService", FakeNeo4jSyncService)
    client = _client()

    auto_response = client.post("/documents/DOC-1/entity-resolution/auto-merge")
    assert auto_response.status_code == 200
    assert auto_response.json()["run_id"] == "RUN-1"

    finalize_response = client.post("/documents/DOC-1/entity-resolution/finalize")
    assert finalize_response.status_code == 200
    assert finalize_response.json()["status"] == "FINALIZED"

    sync_response = client.post("/documents/DOC-1/entity-resolution/sync-neo4j")
    assert sync_response.status_code == 200
    assert sync_response.json()["sync_status"] == "SYNCED"

    assert client.post(
        "/documents/DOC-1/entity-resolution/runs/RUN-1/auto-merge"
    ).status_code == 404
    assert client.post(
        "/documents/DOC-1/entity-resolution/runs/RUN-1/finalize"
    ).status_code == 404
    assert client.post(
        "/documents/DOC-1/entity-resolution/runs/RUN-1/sync-neo4j"
    ).status_code == 404

