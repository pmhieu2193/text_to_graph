from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.routes.dashboard import get_document_workflow
from app.core.database import Base
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.entity_resolution import CanonicalEntity, CanonicalEntityMember, EntityResolutionRun
from app.models.extraction import RawEntity


def test_workflow_reports_alias_inclusive_llm_baseline_against_final_canonical_nodes():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="DOC-METRICS",
            original_filename="metrics.pdf",
            stored_filename="metrics.pdf",
            file_path="data/documents/metrics.pdf",
            content_type="application/pdf",
            file_size=12,
            sha256="a" * 64,
            status=DocumentStatus.FINALIZED,
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
                id="RAW-1", document_id=document.id, chunk_id=chunks[0].id,
                local_id="E1", name="Đại học A", aliases=["ĐH A", "Trường A"],
                entity_type="ORGANIZATION", evidence=["source 1"], confidence=0.9,
                provider="test", model_name="fake",
            ),
            RawEntity(
                id="RAW-2", document_id=document.id, chunk_id=chunks[1].id,
                local_id="E2", name="Đại học A", aliases=["University A"],
                entity_type="ORGANIZATION", evidence=["source 2"], confidence=0.9,
                provider="test", model_name="fake",
            ),
        ])
        canonical = CanonicalEntity(
            id="CAN-1", document_id=document.id,
            entity_type="ORGANIZATION", name="Đại học A",
            aliases=["ĐH A", "Trường A", "University A"],
        )
        db.add(canonical)
        db.flush()
        db.add_all([
            CanonicalEntityMember(
                raw_entity_id="RAW-1", canonical_entity_id="CAN-1",
                document_id=document.id,
            ),
            CanonicalEntityMember(
                raw_entity_id="RAW-2", canonical_entity_id="CAN-1",
                document_id=document.id,
            ),
        ])
        db.add(EntityResolutionRun(
            id="RUN-METRICS", document_id=document.id, status="FINALIZED",
        ))
        db.commit()

        result = get_document_workflow(document.id, db)
        metrics = result["metrics"]

        # 2 extracted records + 3 distinct aliases = 5 LLM-style name entries.
        assert metrics["raw_entity_count"] == 2
        assert metrics["original_entity_name_count"] == 5
        assert metrics["canonical_entity_count"] == 1
        assert metrics["original_to_canonical_reduction_count"] == 4
        assert metrics["original_to_canonical_reduction_percent"] == 80.0

    engine.dispose()
