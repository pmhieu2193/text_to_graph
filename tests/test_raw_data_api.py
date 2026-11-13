from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.routes.raw_data import router
from app.core.database import Base, get_db
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.extraction import RawEntity, RawRelation


def _client_with_seeded_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        document = Document(
            id="DOC-RAW",
            original_filename="raw.pdf",
            stored_filename="raw.pdf",
            file_path="data/documents/raw.pdf",
            content_type="application/pdf",
            file_size=10,
            sha256="b" * 64,
            status=DocumentStatus.EXTRACTED,
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

        db.add_all([
            RawEntity(
                id="RAW-A", document_id=document.id, chunk_id=chunks[0].id,
                local_id="A", name="Đại học A", aliases=["ĐH A"],
                entity_type="ORGANIZATION", evidence=["Evidence A"], confidence=0.9,
                provider="test", model_name="fake",
            ),
            RawEntity(
                id="RAW-B", document_id=document.id, chunk_id=chunks[1].id,
                local_id="B", name="Thành phố B", aliases=[],
                entity_type="LOCATION", evidence=["Evidence B"], confidence=0.8,
                provider="test", model_name="fake",
            ),
        ])
        db.flush()
        db.add(RawRelation(
            document_id=document.id,
            chunk_id=chunks[0].id,
            local_id="REL-1",
            subject_entity_id="RAW-A",
            object_entity_id="RAW-B",
            relation_type="LOCATED_IN",
            description="Đại học A nằm tại thành phố B",
            evidence="Đại học A nằm tại thành phố B",
            confidence=0.95,
            provider="test",
            model_name="fake",
        ))
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), engine


def test_raw_entity_pagination_search_and_not_found():
    client, engine = _client_with_seeded_database()
    try:
        first = client.get(
            "/documents/DOC-RAW/raw-entities",
            params={"page": 1, "page_size": 1},
        )
        assert first.status_code == 200
        assert first.json()["total"] == 2
        assert first.json()["page"] == 1
        assert len(first.json()["items"]) == 1

        second = client.get(
            "/documents/DOC-RAW/raw-entities",
            params={"page": 1, "page_size": 1, "entity_type": "LOCATION"},
        )
        assert second.status_code == 200
        assert second.json()["total"] == 1
        assert second.json()["items"][0]["name"] == "Thành phố B"

        missing = client.get("/documents/MISSING/raw-entities")
        assert missing.status_code == 404
    finally:
        engine.dispose()


def test_raw_relation_search_and_pagination():
    client, engine = _client_with_seeded_database()
    try:
        response = client.get(
            "/documents/DOC-RAW/raw-relations",
            params={"page": 1, "page_size": 10, "search": "Đại học A"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["subject"] == "Đại học A"
        assert body["items"][0]["object"] == "Thành phố B"

        empty = client.get(
            "/documents/DOC-RAW/raw-relations",
            params={"page": 2, "page_size": 10},
        )
        assert empty.status_code == 200
        assert empty.json()["items"] == []
    finally:
        engine.dispose()
