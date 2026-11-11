from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.models.document import Document
from app.models.entity_resolution import (
    CanonicalEntity,
    CanonicalEntityMember,
    EntityCandidate,
    EntityResolutionRun,
)
from app.models.extraction import RawEntity, RawRelation
from app.services.entity_resolution.embedding_matcher import EmbeddingMatcher
from app.services.entity_resolution.manage_raw_entity import ManageRawEntity
from app.services.entity_resolution.report_writer import EntityResolutionReportWriter
from app.services.entity_resolution.string_matcher import StringMatcher


class EntityResolutionService:
    """Persisted, document-scoped ER candidates and human review workflow."""

    def __init__(
        self,
        db: Session,
        embedding_matcher: EmbeddingMatcher | None = None,
        string_matcher: StringMatcher | None = None,
        report_writer: EntityResolutionReportWriter | None = None,
    ) -> None:
        self.db = db
        self.embedding_matcher = embedding_matcher or EmbeddingMatcher()
        self.string_matcher = string_matcher or StringMatcher(
            top_k=settings.er_string_top_k
        )
        self.report_writer = report_writer or EntityResolutionReportWriter()

    def _ensure_canonical_members(self, document_id: str) -> None:
        entities = list(self.db.scalars(
            select(RawEntity).where(RawEntity.document_id == document_id)
        ).all())
        for entity in entities:
            member = self.db.get(CanonicalEntityMember, entity.id)
            if member is not None:
                continue
            canonical = CanonicalEntity(
                document_id=document_id,
                entity_type=entity.entity_type,
                name=entity.name,
            )
            self.db.add(canonical)
            self.db.flush()
            self.db.add(CanonicalEntityMember(
                raw_entity_id=entity.id,
                canonical_entity_id=canonical.id,
                document_id=document_id,
            ))
        self.db.flush()

    def preview(self, document_id: str) -> tuple[pd.DataFrame, str, str]:
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")

        rows = list(self.db.scalars(
            select(RawEntity)
            .where(RawEntity.document_id == document_id)
            .order_by(RawEntity.chunk_id, RawEntity.id)
        ).all())
        manager = ManageRawEntity()
        manager.load_from_db(rows)
        manager.clean_entities()

        fuzzy = self.string_matcher.generate(manager)
        semantic = self.embedding_matcher.generate(manager)
        entity_map = {entity.id: entity for entity in manager.get_entities()}

        run = EntityResolutionRun(document_id=document_id, status="GENERATING")
        self.db.add(run)
        self.db.flush()

        records = []
        for entity_a_id, entity_b_id in sorted(set(fuzzy) | set(semantic)):
            string_candidate = fuzzy.get((entity_a_id, entity_b_id))
            embedding_candidate = semantic.get((entity_a_id, entity_b_id))
            fuzzy_score = string_candidate.fuzzy_score if string_candidate else None
            embedding_score = (
                embedding_candidate.embedding_score if embedding_candidate else None
            )
            if fuzzy_score is not None and embedding_score is not None:
                final_score = 0.45 * fuzzy_score + 0.55 * embedding_score
                match_method = "HYBRID"
            elif fuzzy_score is not None:
                final_score = None
                match_method = "FUZZY_ONLY"
            else:
                final_score = None
                match_method = "EMBEDDING_ONLY"

            classification = self._classify(
                string_candidate, fuzzy_score, embedding_score
            )
            entity_a = entity_map[entity_a_id]
            entity_b = entity_map[entity_b_id]
            candidate = EntityCandidate(
                run_id=run.id,
                document_id=document_id,
                entity_a_id=entity_a_id,
                entity_b_id=entity_b_id,
                fuzzy_score=fuzzy_score,
                embedding_score=embedding_score,
                final_score=final_score,
                match_method=match_method,
                fuzzy_exact=bool(string_candidate and string_candidate.is_exact),
                fuzzy_match=(
                    list(string_candidate.matched_variants) if string_candidate else None
                ),
                embedding_match=(
                    list(embedding_candidate.matched_variants)
                    if embedding_candidate else None
                ),
                evidence_a=list(entity_a.evidence or []),
                evidence_b=list(entity_b.evidence or []),
                classification=classification,
                review_status="PENDING",
            )
            self.db.add(candidate)
            self.db.flush()
            records.append(self._candidate_record(candidate, entity_a, entity_b))

        columns = [
            "pair_id", "entity_a_id", "entity_a", "evidence_a",
            "entity_b_id", "entity_b", "evidence_b",
            "fuzzy_score", "embedding_score", "final_score", "match_method",
            "fuzzy_exact", "fuzzy_match", "embedding_match",
            "classification", "decision", "review_status",
        ]
        dataframe = pd.DataFrame.from_records(records, columns=columns)
        report_path = self.report_writer.write(document_id, dataframe)
        run.report_path = str(report_path)
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        self._ensure_canonical_members(document_id)
        self.db.commit()
        return dataframe, str(report_path), run.id

    @staticmethod
    def _candidate_record(candidate, entity_a=None, entity_b=None) -> dict:
        return {
            "pair_id": candidate.id,
            "entity_a_id": candidate.entity_a_id,
            "entity_a": entity_a.name if entity_a else None,
            "evidence_a": candidate.evidence_a,
            "entity_b_id": candidate.entity_b_id,
            "entity_b": entity_b.name if entity_b else None,
            "evidence_b": candidate.evidence_b,
            "fuzzy_score": candidate.fuzzy_score,
            "embedding_score": candidate.embedding_score,
            "final_score": candidate.final_score,
            "match_method": candidate.match_method,
            "fuzzy_exact": candidate.fuzzy_exact,
            "fuzzy_match": candidate.fuzzy_match,
            "embedding_match": candidate.embedding_match,
            "classification": candidate.classification,
            "decision": candidate.decision,
            "review_status": candidate.review_status,
        }

    @staticmethod
    def _classify(string_candidate, fuzzy_score, embedding_score) -> str:
        if (
            string_candidate is not None
            and string_candidate.is_exact
            and settings.er_auto_merge_exact
        ):
            return "AUTO_MERGE"
        if (
            fuzzy_score is not None
            and embedding_score is not None
            and fuzzy_score >= settings.er_fuzzy_auto_threshold
            and embedding_score >= settings.er_embedding_auto_threshold
        ):
            return "AUTO_MERGE"
        fuzzy_review = (
            fuzzy_score is not None
            and fuzzy_score >= settings.er_fuzzy_review_threshold
        )
        embedding_review = (
            embedding_score is not None
            and embedding_score >= settings.er_embedding_review_threshold
        )
        return "REVIEW" if fuzzy_review or embedding_review else "REJECT"

    def list_candidates(self, document_id: str, run_id: str) -> list[dict]:
        run = self.db.get(EntityResolutionRun, run_id)
        if run is None or run.document_id != document_id:
            raise LookupError("Không tìm thấy lần chạy ER thuộc tài liệu này.")
        entities = aliased(RawEntity)
        rows = self.db.execute(
            select(EntityCandidate, RawEntity, entities)
            .join(RawEntity, RawEntity.id == EntityCandidate.entity_a_id)
            .join(entities, entities.id == EntityCandidate.entity_b_id)
            .where(
                EntityCandidate.document_id == document_id,
                EntityCandidate.run_id == run_id,
            )
            .order_by(EntityCandidate.final_score.desc().nullslast(), EntityCandidate.id)
        ).all()
        return [
            self._candidate_record(candidate, entity_a, entity_b)
            for candidate, entity_a, entity_b in rows
        ]

    def _canonical_for_raw(self, raw_entity_id: str) -> CanonicalEntity:
        member = self.db.get(CanonicalEntityMember, raw_entity_id)
        if member is None:
            raise ValueError(f"Raw entity {raw_entity_id} chưa có canonical mapping.")
        canonical = self.db.get(CanonicalEntity, member.canonical_entity_id)
        if canonical is None:
            raise ValueError("Canonical entity mapping không hợp lệ.")
        while canonical.merged_into_id:
            canonical = self.db.get(CanonicalEntity, canonical.merged_into_id)
            if canonical is None:
                raise ValueError("Canonical merge chain không hợp lệ.")
        return canonical

    def _has_separation_conflict(
        self, document_id: str, raw_ids_a: set[str], raw_ids_b: set[str]
    ) -> bool:
        if not raw_ids_a or not raw_ids_b:
            return False
        pairs = self.db.scalars(
            select(EntityCandidate).where(
                EntityCandidate.document_id == document_id,
                EntityCandidate.decision == "KEEP_SEPARATE",
            )
        ).all()
        for pair in pairs:
            if (
                pair.entity_a_id in raw_ids_a and pair.entity_b_id in raw_ids_b
            ) or (
                pair.entity_b_id in raw_ids_a and pair.entity_a_id in raw_ids_b
            ):
                return True
        return False

    def _merge_candidate(self, candidate: EntityCandidate) -> str | None:
        canonical_a = self._canonical_for_raw(candidate.entity_a_id)
        canonical_b = self._canonical_for_raw(candidate.entity_b_id)
        if canonical_a.id == canonical_b.id:
            candidate.decision = "MERGE"
            candidate.review_status = "MERGED"
            candidate.reviewed_at = datetime.now(timezone.utc)
            return canonical_a.id

        members_a = set(self.db.scalars(
            select(CanonicalEntityMember.raw_entity_id).where(
                CanonicalEntityMember.canonical_entity_id == canonical_a.id
            )
        ).all())
        members_b = set(self.db.scalars(
            select(CanonicalEntityMember.raw_entity_id).where(
                CanonicalEntityMember.canonical_entity_id == canonical_b.id
            )
        ).all())
        if self._has_separation_conflict(
            candidate.document_id, members_a, members_b
        ):
            candidate.review_status = "BLOCKED_CONFLICT"
            candidate.error_message = (
                "Không thể gộp: hai cluster có quyết định KEEP_SEPARATE trước đó."
            )
            return None

        # Stable survivor: canonical created first; ID breaks timestamp ties.
        survivor, loser = sorted(
            (canonical_a, canonical_b),
            key=lambda item: ((item.created_at.isoformat() if item.created_at else ""), item.id),
        )
        self.db.execute(
            update(CanonicalEntityMember)
            .where(CanonicalEntityMember.canonical_entity_id == loser.id)
            .values(canonical_entity_id=survivor.id)
        )
        loser.merged_into_id = survivor.id
        candidate.decision = "MERGE"
        candidate.review_status = "MERGED"
        candidate.error_message = None
        candidate.reviewed_at = datetime.now(timezone.utc)
        self.db.flush()
        return survivor.id

    def decide(self, document_id: str, pair_id: str, decision: str) -> dict:
        candidate = self.db.get(EntityCandidate, pair_id)
        if candidate is None or candidate.document_id != document_id:
            raise LookupError("Không tìm thấy cặp candidate thuộc tài liệu này.")
        if candidate.review_status != "PENDING":
            raise ValueError(
                f"Cặp này đã được xử lý (review_status={candidate.review_status})."
            )
        if decision not in {"MERGE", "KEEP_SEPARATE", "SKIP"}:
            raise ValueError("decision phải là MERGE, KEEP_SEPARATE hoặc SKIP.")
        try:
            canonical_id = None
            if decision == "KEEP_SEPARATE":
                canonical_a = self._canonical_for_raw(candidate.entity_a_id)
                canonical_b = self._canonical_for_raw(candidate.entity_b_id)
                if canonical_a.id == canonical_b.id:
                    raise ValueError("Hai entity đã thuộc cùng canonical cluster; không thể đánh dấu KEEP_SEPARATE mà không tách cluster.")
            if decision == "MERGE":
                canonical_id = self._merge_candidate(candidate)
                if candidate.review_status == "BLOCKED_CONFLICT":
                    self.db.commit()
                    raise ValueError(candidate.error_message)
            else:
                candidate.decision = decision
                candidate.review_status = (
                    "KEPT_SEPARATE" if decision == "KEEP_SEPARATE" else "SKIPPED"
                )
                candidate.reviewed_at = datetime.now(timezone.utc)
            self.db.commit()
            return {
                "pair_id": candidate.id,
                "decision": candidate.decision,
                "review_status": candidate.review_status,
                "canonical_entity_id": canonical_id,
            }
        except Exception:
            self.db.rollback()
            raise

    def auto_merge(self, document_id: str, run_id: str) -> dict:
        run = self.db.get(EntityResolutionRun, run_id)
        if run is None or run.document_id != document_id:
            raise LookupError("Không tìm thấy lần chạy ER thuộc tài liệu này.")
        candidates = list(self.db.scalars(
            select(EntityCandidate)
            .where(
                EntityCandidate.document_id == document_id,
                EntityCandidate.run_id == run_id,
                EntityCandidate.classification == "AUTO_MERGE",
                EntityCandidate.review_status == "PENDING",
            )
            .order_by(EntityCandidate.final_score.desc().nullslast(), EntityCandidate.id)
        ).all())
        merged = blocked = 0
        try:
            for candidate in candidates:
                result = self._merge_candidate(candidate)
                if result is None:
                    blocked += 1
                else:
                    merged += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "run_id": run_id,
            "auto_candidates": len(candidates),
            "merged_or_already_same_cluster": merged,
            "blocked_by_keep_separate": blocked,
        }

    def auto_process(self, document_id: str, run_id: str) -> dict:
        """Apply AUTO_MERGE candidates, then default all remaining PENDING pairs to no-merge."""
        auto_result = self.auto_merge(document_id, run_id)
        pending = list(self.db.scalars(
            select(EntityCandidate).where(
                EntityCandidate.document_id == document_id,
                EntityCandidate.run_id == run_id,
                EntityCandidate.review_status == "PENDING",
            )
        ).all())
        for candidate in pending:
            candidate.decision = "KEEP_SEPARATE"
            candidate.review_status = "KEPT_SEPARATE"
            candidate.reviewed_at = datetime.now(timezone.utc)
        self.db.commit()
        return {
            **auto_result,
            "defaulted_to_keep_separate": len(pending),
        }

    def canonical_relations(self, document_id: str) -> list[dict]:
        subject_member = aliased(CanonicalEntityMember)
        object_member = aliased(CanonicalEntityMember)
        subject_canonical = aliased(CanonicalEntity)
        object_canonical = aliased(CanonicalEntity)
        rows = self.db.execute(
            select(
                RawRelation.id,
                RawRelation.subject_entity_id,
                RawRelation.object_entity_id,
                RawRelation.relation_type,
                RawRelation.description,
                RawRelation.evidence,
                subject_member.canonical_entity_id,
                object_member.canonical_entity_id,
                subject_canonical.name,
                object_canonical.name,
            )
            .join(
                subject_member,
                subject_member.raw_entity_id == RawRelation.subject_entity_id,
            )
            .join(
                object_member,
                object_member.raw_entity_id == RawRelation.object_entity_id,
            )
            .join(
                subject_canonical,
                subject_canonical.id == subject_member.canonical_entity_id,
            )
            .join(
                object_canonical,
                object_canonical.id == object_member.canonical_entity_id,
            )
            .where(RawRelation.document_id == document_id)
            .order_by(RawRelation.id)
        ).all()
        return [
            {
                "raw_relation_id": row[0],
                "raw_subject_entity_id": row[1],
                "raw_object_entity_id": row[2],
                "relation_type": row[3],
                "description": row[4],
                "evidence": row[5],
                "canonical_subject_id": row[6],
                "canonical_object_id": row[7],
                "canonical_subject_name": row[8],
                "canonical_object_name": row[9],
            }
            for row in rows
        ]
