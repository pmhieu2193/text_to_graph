import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.entity_resolution import (
    CanonicalEntity,
    CanonicalEntityMember,
    EntityResolutionRun,
)
from app.models.extraction import RawEntity, RawRelation
from app.services.entity_resolution.neo4j_sync import Neo4jGraphSyncService


class FakeResult:
    def consume(self):
        return None

    def single(self):
        return {"deleted": 0}


class FakeTransaction:
    def __init__(self, calls):
        self.calls = calls

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult()


class FakeSession:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult()

    def execute_write(self, callback):
        return callback(FakeTransaction(self.calls))


class FakeDriver:
    def __init__(self, calls):
        self.calls = calls

    def verify_connectivity(self):
        return None

    def session(self, database=None):
        return FakeSession(self.calls)

    def close(self):
        return None


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed_finalized_document(db):
    document = Document(
        id="DOC-NEO4J",
        original_filename="graph.pdf",
        stored_filename="graph.pdf",
        file_path="storage/graph.pdf",
        content_type="application/pdf",
        file_size=10,
        sha256="a" * 64,
        status=DocumentStatus.COMPLETED,
    )
    db.add(document)
    db.flush()

    chunks = []
    for index in (1, 2):
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=index,
            content=f"chunk {index}",
            char_count=8,
        )
        db.add(chunk)
        db.flush()
        chunks.append(chunk)

    raw_a = RawEntity(
        id="RAW-A", document_id=document.id, chunk_id=chunks[0].id,
        local_id="A", name="Alpha", aliases=["A"], entity_type="ORGANIZATION",
        evidence=["Alpha source"], confidence=0.9, provider="test", model_name="fake",
    )
    raw_b = RawEntity(
        id="RAW-B", document_id=document.id, chunk_id=chunks[1].id,
        local_id="B", name="Beta", aliases=[], entity_type="LOCATION",
        evidence=["Beta source"], confidence=0.9, provider="test", model_name="fake",
    )
    db.add_all([raw_a, raw_b])
    db.flush()

    canonical_a = CanonicalEntity(
        id="CAN-A", document_id=document.id, entity_type="ORGANIZATION",
        name="Alpha", aliases=["A"],
    )
    canonical_b = CanonicalEntity(
        id="CAN-B", document_id=document.id, entity_type="LOCATION",
        name="Beta", aliases=[],
    )
    db.add_all([canonical_a, canonical_b])
    db.flush()
    db.add_all([
        CanonicalEntityMember(
            raw_entity_id="RAW-A", canonical_entity_id="CAN-A", document_id=document.id,
        ),
        CanonicalEntityMember(
            raw_entity_id="RAW-B", canonical_entity_id="CAN-B", document_id=document.id,
        ),
    ])
    db.add_all([
        RawRelation(
            document_id=document.id, chunk_id=chunks[0].id, local_id="REL-1",
            subject_entity_id="RAW-A", object_entity_id="RAW-B",
            relation_type="LOCATED_IN", description="Alpha nằm tại Beta",
            evidence="Alpha nằm tại Beta", confidence=0.9, provider="test", model_name="fake",
        ),
        RawRelation(
            document_id=document.id, chunk_id=chunks[1].id, local_id="REL-2",
            subject_entity_id="RAW-A", object_entity_id="RAW-B",
            relation_type="HAS_PART", description="Alpha có thành phần Beta",
            evidence="Alpha có thành phần Beta", confidence=0.9, provider="test", model_name="fake",
        ),
    ])
    db.add(EntityResolutionRun(
        id="RUN-NEO4J", document_id=document.id, status="FINALIZED",
    ))
    db.commit()
    return document.id


def test_sync_uses_domain_relationship_types_and_exports_cypher(tmp_path, monkeypatch):
    engine = _database()
    calls = []
    fake_graph_database = SimpleNamespace(
        driver=lambda *_args, **_kwargs: FakeDriver(calls)
    )
    monkeypatch.setitem(
        sys.modules, "neo4j", SimpleNamespace(GraphDatabase=fake_graph_database)
    )
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://localhost:7687")
    monkeypatch.setattr(settings, "neo4j_username", "neo4j")
    monkeypatch.setattr(settings, "neo4j_password", "test")
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    monkeypatch.setattr(settings, "er_report_dir", tmp_path)

    with Session(engine, expire_on_commit=False) as db:
        document_id = _seed_finalized_document(db)
        result = Neo4jGraphSyncService(db).sync(document_id)

        assert result["sync_status"] == "SYNCED"
        assert result["node_count"] == 2
        assert result["relation_count"] == 2
        assert Path(result["cypher_path"]).is_file()

        cypher = Path(result["cypher_path"]).read_text(encoding="utf-8")
        assert "CREATE (s)-[r:`LOCATED_IN`" in cypher
        assert "CREATE (s)-[r:`HAS_PART`" in cypher
        assert "RELATION {" not in cypher

        relationship_queries = [
            query for query, _params in calls
            if "CREATE (s)-[r:" in query
        ]
        assert len(relationship_queries) == 2
        assert any("`LOCATED_IN`" in query for query in relationship_queries)
        assert any("`HAS_PART`" in query for query in relationship_queries)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("located in", "LOCATED_IN"),
        ("HAS-PART", "HAS_PART"),
        ("  related_to  ", "RELATED_TO"),
    ],
)
def test_relationship_type_is_normalized(value, expected):
    assert Neo4jGraphSyncService._relationship_type(value) == expected


@pytest.mark.parametrize("value", ["", "  ", "BAD`TYPE", "TYPE; MATCH (n) DELETE n"])
def test_relationship_type_rejects_invalid_identifiers(value):
    with pytest.raises(ValueError):
        Neo4jGraphSyncService._relationship_type(value)

def test_sync_failure_marks_run_failed_and_does_not_publish_export(tmp_path, monkeypatch):
    engine = _database()

    class UnavailableDriver(FakeDriver):
        def verify_connectivity(self):
            raise RuntimeError("Neo4j unavailable")

    monkeypatch.setitem(
        sys.modules,
        "neo4j",
        SimpleNamespace(GraphDatabase=SimpleNamespace(
            driver=lambda *_args, **_kwargs: UnavailableDriver([])
        )),
    )
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://localhost:7687")
    monkeypatch.setattr(settings, "neo4j_username", "neo4j")
    monkeypatch.setattr(settings, "neo4j_password", "test")
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    monkeypatch.setattr(settings, "er_report_dir", tmp_path)

    with Session(engine, expire_on_commit=False) as db:
        document_id = _seed_finalized_document(db)
        with pytest.raises(RuntimeError, match="Neo4j sync thất bại"):
            Neo4jGraphSyncService(db).sync(document_id)

        run = db.get(__import__(
            "app.models.entity_resolution", fromlist=["EntityResolutionRun"]
        ).EntityResolutionRun, "RUN-NEO4J")
        assert run.sync_status == "SYNC_FAILED"
        assert run.sync_error is not None
        assert not (tmp_path / f"neo4j_sync_{document_id}.cypher.txt").exists()
        assert not (tmp_path / f"neo4j_sync_{document_id}.cypher.txt.tmp").exists()

