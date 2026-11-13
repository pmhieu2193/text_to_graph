from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.entity_resolution import (
    CanonicalEntity,
    CanonicalEntityMember,
    EntityCandidate,
    EntityResolutionRun,
)
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

    def write_final(
        self, document_id, run_id, candidates, canonical_entities,
        canonical_relations, summary,
    ):
        from app.services.entity_resolution.report_writer import EntityResolutionReportWriter
        writer = EntityResolutionReportWriter(report_dir=self.path.parent)
        return writer.write_final(
            document_id=document_id,
            run_id=run_id,
            candidates=candidates,
            canonical_entities=canonical_entities,
            canonical_relations=canonical_relations,
            summary=summary,
        )


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

        result = service.auto_merge("D1")
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


def test_finalize_defaults_unresolved_review_to_skip_and_exports_workbook(tmp_path):
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
        result = service.finalize("D2")

        persisted_run = db.get(EntityResolutionRun, run_id)
        assert persisted_run.status == "FINALIZED"
        assert persisted_run.report_path == result["report_path"]
        assert result["defaulted_to_skip"] == 1
        candidate = db.scalar(
            select(EntityCandidate).where(EntityCandidate.run_id == run_id)
        )
        assert candidate.decision == "SKIP"
        assert candidate.review_status == "SKIPPED"
        assert result["canonical_entity_count"] == 2
        assert Path(result["report_path"]).exists()
        from openpyxl import load_workbook
        workbook = load_workbook(result["report_path"], read_only=True)
        assert set(workbook.sheetnames) == {
            "Summary", "Candidates", "Canonical_Entities", "Canonical_Relations"
        }
        assert workbook["Summary"].max_row == 2
        workbook.close()
        try:
            service.finalize("D2")
            assert False, "finalize must be idempotency-protected"
        except ValueError:
            pass



def test_finalize_merges_aliases_and_deduplicates_inherited_relations(tmp_path):
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="D3",
            original_filename="aliases.pdf",
            stored_filename="aliases.pdf",
            file_path="storage/aliases.pdf",
            content_type="application/pdf",
            file_size=10,
            sha256="2" * 64,
            status=DocumentStatus.COMPLETED,
        )
        db.add(document)
        db.flush()
        chunks = {}
        for entity_id in ("A", "B", "X"):
            chunk = DocumentChunk(
                document_id="D3", chunk_index=len(chunks) + 1,
                content=entity_id, char_count=1,
            )
            db.add(chunk)
            db.flush()
            chunks[entity_id] = chunk.id

        db.add_all([
            RawEntity(
                id="A", document_id="D3", chunk_id=chunks["A"], local_id="A",
                name="Công viên Đầm Sen", aliases=["Đầm Sen", "CV Đầm Sen"],
                entity_type="LOCATION", evidence=["A evidence"], confidence=0.9,
                provider="test", model_name="fake",
            ),
            RawEntity(
                id="B", document_id="D3", chunk_id=chunks["B"], local_id="B",
                name="Công viên nước Đầm Sen", aliases=["Đầm Sen Water Park"],
                entity_type="LOCATION", evidence=["B evidence"], confidence=0.9,
                provider="test", model_name="fake",
            ),
            RawEntity(
                id="X", document_id="D3", chunk_id=chunks["X"], local_id="X",
                name="Quận 11", aliases=[], entity_type="LOCATION",
                evidence=["X evidence"], confidence=0.9, provider="test",
                model_name="fake",
            ),
        ])
        db.flush()
        db.add_all([
            RawRelation(
                document_id="D3", chunk_id=chunks["A"], local_id="R1",
                subject_entity_id="A", object_entity_id="X",
                relation_type="LOCATED_IN", description="A nằm ở quận 11",
                evidence="A nằm ở quận 11", confidence=0.9,
                provider="test", model_name="fake",
            ),
            RawRelation(
                document_id="D3", chunk_id=chunks["B"], local_id="R2",
                subject_entity_id="B", object_entity_id="X",
                relation_type="located_in", description="B nằm ở quận 11",
                evidence="B nằm ở quận 11", confidence=0.9,
                provider="test", model_name="fake",
            ),
        ])
        db.commit()

        class AliasStringMatcher:
            def generate(self, manager):
                return {
                    ("A", "B"): StringCandidate(
                        "A", "B", 0.99, False,
                        ("Công viên Đầm Sen", "Công viên nước Đầm Sen"),
                    )
                }

        class AliasEmbeddingMatcher:
            def generate(self, manager):
                return {
                    ("A", "B"): EmbeddingCandidate(
                        "A", "B", 0.99,
                        ("Công viên Đầm Sen", "Công viên nước Đầm Sen"),
                    )
                }

        service = EntityResolutionService(
            db,
            embedding_matcher=AliasEmbeddingMatcher(),
            string_matcher=AliasStringMatcher(),
            report_writer=FakeReportWriter(tmp_path / "unused.xlsx"),
        )
        _dataframe, _preview_path, run_id = service.preview("D3")
        result = service.finalize("D3")

        assert result["merged_or_already_same_cluster"] == 1
        assert result["canonical_entity_count"] == 2
        assert result["canonical_relation_count"] == 1
        assert result["deduplicated_relation_count"] == 1
        canonical = next(
            item for item in result["canonical_entities"]
            if len(item["raw_entity_ids"]) == 2
        )
        all_names = {canonical["name"], *canonical["aliases"]}
        assert "Công viên nước Đầm Sen" in all_names
        assert "Công viên Đầm Sen" in all_names
        assert "Đầm Sen" in canonical["aliases"]
        relation = result["canonical_relations"][0]
        assert relation["raw_relation_count"] == 2
        assert len(relation["raw_relation_ids"]) == 2
        assert Path(result["report_path"]).exists()


def test_reset_er_preserves_raw_data_and_allows_a_fresh_run(tmp_path):
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="D4",
            original_filename="reset.pdf",
            stored_filename="reset.pdf",
            file_path="storage/reset.pdf",
            content_type="application/pdf",
            file_size=10,
            sha256="4" * 64,
            status=DocumentStatus.COMPLETED,
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id="D4", chunk_index=1, content="raw entity", char_count=10
        )
        db.add(chunk)
        db.flush()
        raw = RawEntity(
            id="RAW-D4", document_id="D4", chunk_id=chunk.id, local_id="E1",
            name="Entity One", aliases=[], entity_type="ORGANIZATION",
            evidence=["source"], confidence=0.9, provider="test", model_name="fake",
        )
        db.add(raw)
        db.commit()

        class NoCandidates:
            def generate(self, manager):
                return {}

        service = EntityResolutionService(
            db,
            embedding_matcher=NoCandidates(),
            string_matcher=NoCandidates(),
            report_writer=FakeReportWriter(tmp_path / "reset.xlsx"),
        )
        _frame, _report, first_run_id = service.preview("D4")
        assert db.get(CanonicalEntityMember, "RAW-D4") is not None

        try:
            service.preview("D4")
            assert False, "A second run must require reset first"
        except ValueError:
            pass

        reset_result = service.reset("D4")
        assert reset_result["status"] == "RESET"
        assert db.get(RawEntity, "RAW-D4") is not None
        assert db.get(CanonicalEntityMember, "RAW-D4") is None
        assert db.scalar(
            select(EntityResolutionRun).where(EntityResolutionRun.id == first_run_id)
        ) is None
        assert db.scalars(
            select(CanonicalEntity).where(CanonicalEntity.document_id == "D4")
        ).all() == []

        _frame, _report, second_run_id = service.preview("D4")
        assert second_run_id != first_run_id
        assert db.get(RawEntity, "RAW-D4") is not None

def test_keep_separate_blocks_a_later_transitive_cluster_merge():
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        document = Document(
            id="D5", original_filename="separation.pdf",
            stored_filename="separation.pdf", file_path="storage/separation.pdf",
            content_type="application/pdf", file_size=10, sha256="5" * 64,
            status=DocumentStatus.COMPLETED,
        )
        db.add(document)
        db.flush()
        chunks = {}
        for raw_id in ("A", "B", "C"):
            chunk = DocumentChunk(
                document_id="D5", chunk_index=len(chunks) + 1,
                content=raw_id, char_count=1,
            )
            db.add(chunk)
            db.flush()
            chunks[raw_id] = chunk.id
            db.add(RawEntity(
                id=raw_id, document_id="D5", chunk_id=chunk.id, local_id=raw_id,
                name=raw_id, aliases=[], entity_type="ORGANIZATION",
                evidence=[raw_id], confidence=0.9, provider="test", model_name="fake",
            ))
        db.flush()
        canonicals = {
            raw_id: CanonicalEntity(
                id=f"CAN-{raw_id}", document_id="D5",
                entity_type="ORGANIZATION", name=raw_id, aliases=[],
            )
            for raw_id in ("A", "B", "C")
        }
        db.add_all(canonicals.values())
        db.flush()
        db.add_all([
            CanonicalEntityMember(
                raw_entity_id=raw_id, canonical_entity_id=f"CAN-{raw_id}",
                document_id="D5",
            )
            for raw_id in ("A", "B", "C")
        ])
        run = EntityResolutionRun(id="RUN-D5", document_id="D5", status="COMPLETED")
        db.add(run)
        db.flush()
        db.add_all([
            EntityCandidate(
                id="PAIR-AB", run_id=run.id, document_id="D5",
                entity_a_id="A", entity_b_id="B", classification="AUTO_MERGE",
                final_score=0.97, match_method="HYBRID",
                evidence_a=["A"], evidence_b=["B"], review_status="PENDING",
            ),
            EntityCandidate(
                id="PAIR-BC", run_id=run.id, document_id="D5",
                entity_a_id="B", entity_b_id="C", classification="AUTO_MERGE",
                final_score=0.99, match_method="HYBRID",
                evidence_a=["B"], evidence_b=["C"], review_status="PENDING",
            ),
            EntityCandidate(
                id="PAIR-AC", run_id=run.id, document_id="D5",
                entity_a_id="A", entity_b_id="C", classification="AUTO_MERGE",
                final_score=0.98, match_method="HYBRID",
                evidence_a=["A"], evidence_b=["C"], review_status="PENDING",
            ),
        ])
        db.commit()

        service = EntityResolutionService(
            db,
            embedding_matcher=object(),
            string_matcher=object(),
            report_writer=FakeReportWriter(Path("unused.xlsx")),
        )
        decision = service.decide("D5", "PAIR-AB", "KEEP_SEPARATE")
        assert decision["review_status"] == "KEPT_SEPARATE"

        result = service.auto_merge("D5")
        assert result["merged_or_already_same_cluster"] == 1
        assert result["blocked_by_keep_separate"] == 1
        members = {
            raw_id: canonical_id
            for raw_id, canonical_id in db.query(
                CanonicalEntityMember.raw_entity_id,
                CanonicalEntityMember.canonical_entity_id,
            ).all()
        }
        assert members["B"] == members["C"]
        assert members["A"] != members["B"]


def test_current_run_rejects_ambiguous_multiple_runs():
    engine = _build_db()
    with Session(engine, expire_on_commit=False) as db:
        db.add(Document(
            id="D6", original_filename="multiple.pdf",
            stored_filename="multiple.pdf", file_path="storage/multiple.pdf",
            content_type="application/pdf", file_size=10, sha256="6" * 64,
            status=DocumentStatus.COMPLETED,
        ))
        db.flush()
        db.add_all([
            EntityResolutionRun(id="RUN-1", document_id="D6", status="COMPLETED"),
            EntityResolutionRun(id="RUN-2", document_id="D6", status="COMPLETED"),
        ])
        db.commit()

        service = EntityResolutionService(
            db,
            embedding_matcher=object(),
            string_matcher=object(),
            report_writer=FakeReportWriter(Path("unused.xlsx")),
        )
        try:
            service.get_current_run("D6")
            assert False, "Multiple runs must not be silently selected"
        except ValueError as exc:
            assert "nhiều ER run" in str(exc)

