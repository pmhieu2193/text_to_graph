from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.entity_resolution import CanonicalEntityMember, EntityCandidate
from app.models.extraction import RawEntity, RawRelation
from app.services.entity_resolution.embedding_matcher import EmbeddingCandidate
from app.services.entity_resolution.service import EntityResolutionService
from app.services.entity_resolution.string_matcher import StringCandidate


class FakeStringMatcher:
    def generate(self, manager):
        return {
            ("A", "B"): StringCandidate("A", "B", 0.99, False, ("Alpha", "Alpha variant")),
            ("B", "C"): StringCandidate("B", "C", 0.98, False, ("Alpha variant", "Alpha")),
        }


class FakeEmbeddingMatcher:
    def generate(self, manager):
        return {
            ("A", "B"): EmbeddingCandidate("A", "B", 0.99, ("Alpha", "Alpha variant")),
            ("B", "C"): EmbeddingCandidate("B", "C", 0.98, ("Alpha variant", "Alpha")),
        }


class FakeReportWriter:
    def __init__(self, path: Path):
        self.path = path

    def write(self, document_id, dataframe):
        return self.path


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_auto_merge_handles_transitive_a_b_c_and_preserves_raw_relations(tmp_path):
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="D1",
            original_filename="sample.pdf",
            stored_filename="sample.pdf",
            file_path="storage/sample.pdf",
            content_type="application/pdf",
            file_size=10,
            sha256="0" * 64,
            status=DocumentStatus.COMPLETED,
        )
        db.add(document)
        db.flush()

        chunks = {}
        for index, entity_id in enumerate(("A", "B", "C", "X"), start=1):
            chunk = DocumentChunk(
                document_id="D1",
                chunk_index=index,
                content=f"chunk {index}",
                char_count=8,
            )
            db.add(chunk)
            db.flush()
            chunks[entity_id] = chunk.id

        for entity_id, name in (
            ("A", "Alpha"),
            ("B", "Alpha variant"),
            ("C", "Alpha"),
            ("X", "External node"),
        ):
            db.add(RawEntity(
                id=entity_id,
                document_id="D1",
                chunk_id=chunks[entity_id],
                local_id=entity_id,
                name=name,
                aliases=[],
                entity_type="ORGANIZATION",
                evidence=[f"Evidence for {entity_id}"],
                confidence=0.9,
                provider="test",
                model_name="fake",
            ))

        # One edge leaves A; another edge enters C. Both must still resolve
        # after A, B and C are merged into the same canonical cluster.
        db.add_all([
            RawRelation(
                document_id="D1",
                chunk_id=chunks["A"],
                local_id="R1",
                subject_entity_id="A",
                object_entity_id="X",
                relation_type="RELATED_TO",
                evidence="A liên quan X",
                confidence=0.9,
                provider="test",
                model_name="fake",
            ),
            RawRelation(
                document_id="D1",
                chunk_id=chunks["C"],
                local_id="R2",
                subject_entity_id="X",
                object_entity_id="C",
                relation_type="RELATED_TO",
                evidence="X liên quan C",
                confidence=0.9,
                provider="test",
                model_name="fake",
            ),
        ])
        db.commit()

        service = EntityResolutionService(
            db,
            embedding_matcher=FakeEmbeddingMatcher(),
            string_matcher=FakeStringMatcher(),
            report_writer=FakeReportWriter(tmp_path / "report.xlsx"),
        )
        dataframe, _report_path, run_id = service.preview("D1")

        assert {"pair_id", "evidence_a", "evidence_b"} <= set(dataframe.columns)
        assert len(dataframe) == 2
        assert dataframe["classification"].tolist() == ["AUTO_MERGE", "AUTO_MERGE"]

        result = service.auto_merge("D1", run_id)
        assert result["merged_or_already_same_cluster"] == 2

        members = {
            raw_id: canonical_id
            for raw_id, canonical_id in db.execute(
                select(
                    CanonicalEntityMember.raw_entity_id,
                    CanonicalEntityMember.canonical_entity_id,
                )
            ).all()
        }
        assert members["A"] == members["B"] == members["C"]
        assert members["X"] != members["A"]

        canonical_relations = service.canonical_relations("D1")
        assert len(canonical_relations) == 2
        outgoing = next(row for row in canonical_relations if row["raw_subject_entity_id"] == "A")
        incoming = next(row for row in canonical_relations if row["raw_object_entity_id"] == "C")
        assert outgoing["canonical_subject_id"] == members["A"]
        assert incoming["canonical_object_id"] == members["C"]

        candidates = db.scalars(
            select(EntityCandidate).where(EntityCandidate.run_id == run_id)
        ).all()
        assert all(candidate.review_status == "MERGED" for candidate in candidates)


def test_auto_process_defaults_unresolved_review_to_keep_separate(tmp_path):
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="D2",
            original_filename="review.pdf",
            stored_filename="review.pdf",
            file_path="storage/review.pdf",
            content_type="application/pdf",
            file_size=10,
            sha256="1" * 64,
            status=DocumentStatus.COMPLETED,
        )
        db.add(document)
        db.flush()
        chunk_a = DocumentChunk(document_id="D2", chunk_index=1, content="A", char_count=1)
        chunk_b = DocumentChunk(document_id="D2", chunk_index=2, content="B", char_count=1)
        db.add_all([chunk_a, chunk_b])
        db.flush()
        db.add_all([
            RawEntity(
                id="RA", document_id="D2", chunk_id=chunk_a.id, local_id="RA",
                name="Quận 11", aliases=[], entity_type="LOCATION",
                evidence=["Quận 11"], confidence=0.9, provider="test", model_name="fake",
            ),
            RawEntity(
                id="RB", document_id="D2", chunk_id=chunk_b.id, local_id="RB",
                name="Quận Long Biên", aliases=[], entity_type="LOCATION",
                evidence=["Quận Long Biên"], confidence=0.9, provider="test", model_name="fake",
            ),
        ])
        db.commit()

        class ReviewStringMatcher:
            def generate(self, manager):
                return {
                    ("RA", "RB"): StringCandidate(
                        "RA", "RB", 0.85, False, ("Quận 11", "Quận Long Biên")
                    )
                }

        class NoEmbeddingMatcher:
            def generate(self, manager):
                return {}

        service = EntityResolutionService(
            db,
            embedding_matcher=NoEmbeddingMatcher(),
            string_matcher=ReviewStringMatcher(),
            report_writer=FakeReportWriter(tmp_path / "review.xlsx"),
        )
        _dataframe, _path, run_id = service.preview("D2")
        result = service.auto_process("D2", run_id)

        assert result["defaulted_to_keep_separate"] == 1
        candidate = db.scalar(
            select(EntityCandidate).where(EntityCandidate.run_id == run_id)
        )
        assert candidate.decision == "KEEP_SEPARATE"
        assert candidate.review_status == "KEPT_SEPARATE"
