from types import SimpleNamespace

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import entity_resolution as routes
from app.core.database import get_db
from app.models.document import DocumentStatus


class FakeQuery:
    def __init__(self, rows=None):
        self.rows = rows or []

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self):
        self.document = SimpleNamespace(
            status=DocumentStatus.EXTRACTED,
            error_message=None,
        )

    def get(self, _model, _identity):
        return self.document

    def query(self, _model):
        return FakeQuery([])

    def commit(self):
        return None

    def rollback(self):
        return None


def _client(db=None):
    app = FastAPI()
    app.include_router(routes.router)
    database = db or FakeDB()
    app.dependency_overrides[get_db] = lambda: database
    return TestClient(app), database


def _candidate(pair_id, a, b, classification="REVIEW", status="PENDING", decision=None):
    return {
        "pair_id": pair_id,
        "run_id": "RUN-1",
        "entity_a_id": f"RAW-{a}",
        "entity_a": a,
        "evidence_a": [f"Evidence {a}"],
        "entity_b_id": f"RAW-{b}",
        "entity_b": b,
        "evidence_b": [f"Evidence {b}"],
        "fuzzy_score": 0.82,
        "embedding_score": 0.86,
        "final_score": 0.84,
        "match_method": "HYBRID",
        "fuzzy_exact": False,
        "fuzzy_match": [a, b],
        "embedding_match": [a, b],
        "classification": classification,
        "decision": decision,
        "review_status": status,
    }


def test_candidates_are_document_scoped_and_return_pagination_metadata(monkeypatch):
    rows = [
        _candidate("P1", "Alpha", "Alpha variant", "AUTO_MERGE"),
        _candidate("P2", "Beta", "Beta variant", "REVIEW"),
        _candidate("P3", "Gamma", "Gamma variant", "REVIEW", "SKIPPED", "SKIP"),
    ]

    class FakeERService:
        def __init__(self, _db):
            pass

        def get_current_run(self, document_id):
            assert document_id == "DOC-1"
            return SimpleNamespace(id="RUN-1")

        def list_candidates(self, document_id):
            assert document_id == "DOC-1"
            return rows

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    client, _ = _client()

    response = client.get(
        "/documents/DOC-1/entity-resolution/candidates",
        params={"page": 2, "page_size": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == "DOC-1"
    assert body["run_id"] == "RUN-1"
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert [item["pair_id"] for item in body["items"]] == ["P2"]

    filtered = client.get(
        "/documents/DOC-1/entity-resolution/candidates",
        params={"classification": "review", "search": "gamma"},
    )
    assert filtered.status_code == 200
    assert [item["pair_id"] for item in filtered.json()["items"]] == ["P3"]

    assert client.get(
        "/documents/DOC-1/entity-resolution/runs/RUN-1/candidates"
    ).status_code == 404


def test_decision_endpoint_validates_and_returns_typed_response(monkeypatch):
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
    client, db = _client()

    response = client.post(
        "/documents/DOC-1/entity-resolution/candidates/PAIR-1/decision",
        json={"decision": "SKIP"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "SKIPPED"
    assert db.document.status == DocumentStatus.HUMAN_REVIEW

    invalid = client.post(
        "/documents/DOC-1/entity-resolution/candidates/PAIR-1/decision",
        json={"decision": "MAYBE"},
    )
    assert invalid.status_code == 422


def test_preview_creates_run_and_moves_document_to_entity_resolution(monkeypatch):
    class FakeERService:
        def __init__(self, _db):
            pass

        def preview(self, document_id):
            assert document_id == "DOC-1"
            frame = pd.DataFrame([_candidate("P1", "A", "B", "AUTO_MERGE")])
            return frame, "preview.xlsx", "RUN-1"

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    client, db = _client()
    response = client.post("/documents/DOC-1/entity-resolution/preview")

    assert response.status_code == 200
    assert response.json()["run_id"] == "RUN-1"
    assert response.json()["candidate_count"] == 1
    assert db.document.status == DocumentStatus.ENTITY_RESOLUTION


def test_auto_merge_finalize_and_sync_routes(monkeypatch):
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

        def finalize(self, document_id, apply_auto_merge=True):
            assert apply_auto_merge is False
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
                "report_path": None,
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
                "cypher_path": None,
            }

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    monkeypatch.setattr(routes, "Neo4jGraphSyncService", FakeNeo4jSyncService)
    client, db = _client()

    auto = client.post("/documents/DOC-1/entity-resolution/auto-merge")
    assert auto.status_code == 200
    assert auto.json()["merged_or_already_same_cluster"] == 2

    finalized = client.post(
        "/documents/DOC-1/entity-resolution/finalize",
        params={"auto_merge": "false"},
    )
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "FINALIZED"
    assert db.document.status == DocumentStatus.FINALIZED

    synced = client.post("/documents/DOC-1/entity-resolution/sync-neo4j")
    assert synced.status_code == 200
    assert synced.json()["sync_status"] == "SYNCED"
    assert db.document.status == DocumentStatus.NEO4J_SYNCED


def test_reset_er_returns_document_to_extracted_state(monkeypatch):
    class FakeERService:
        def __init__(self, _db):
            pass

        def reset(self, document_id):
            return {
                "document_id": document_id,
                "status": "RESET",
                "deleted_runs": 1,
                "preserved": ["raw_entities", "raw_relations"],
            }

    monkeypatch.setattr(routes, "EntityResolutionService", FakeERService)
    client, db = _client()

    response = client.delete("/documents/DOC-1/entity-resolution/reset")
    assert response.status_code == 200
    assert response.json()["status"] == "RESET"
    assert response.json()["document_status"] == "EXTRACTED"
    assert db.document.status == DocumentStatus.EXTRACTED


def test_candidate_pagination_rejects_invalid_values():
    client, _ = _client()
    response = client.get(
        "/documents/DOC-1/entity-resolution/candidates",
        params={"page": 0, "page_size": 1000},
    )
    assert response.status_code == 422
