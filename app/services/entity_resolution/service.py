from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import delete, select, update
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
                aliases=self._collect_aliases([entity]),
            )
            self.db.add(canonical)
            self.db.flush()
            self.db.add(CanonicalEntityMember(
                raw_entity_id=entity.id,
                canonical_entity_id=canonical.id,
                document_id=document_id,
            ))
        self.db.flush()

    @staticmethod
    def _collect_aliases(entities: list[RawEntity], canonical_name: str | None = None) -> list[str]:
        """Collect unique observed names and aliases while preserving order."""
        values: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            for value in [entity.name, *(entity.aliases or [])]:
                if not isinstance(value, str):
                    continue
                cleaned = " ".join(value.split()).strip()
                key = cleaned.casefold()
                if cleaned and key not in seen:
                    seen.add(key)
                    values.append(cleaned)
        if canonical_name:
            values = [value for value in values if value.casefold() != canonical_name.casefold()]
        return values

    def _refresh_canonical_aliases(self, document_id: str) -> None:
        """Rebuild aliases from every raw member; raw extraction remains untouched."""
        rows = self.db.execute(
            select(CanonicalEntity, RawEntity)
            .join(CanonicalEntityMember, CanonicalEntityMember.canonical_entity_id == CanonicalEntity.id)
            .join(RawEntity, RawEntity.id == CanonicalEntityMember.raw_entity_id)
            .where(
                CanonicalEntityMember.document_id == document_id,
                RawEntity.document_id == document_id,
                CanonicalEntity.document_id == document_id,
                CanonicalEntity.merged_into_id.is_(None),
            )
            .order_by(CanonicalEntity.created_at, RawEntity.id)
        ).all()
        grouped: dict[str, tuple[CanonicalEntity, list[RawEntity]]] = {}
        for canonical, raw in rows:
            grouped.setdefault(canonical.id, (canonical, []))[1].append(raw)
        for canonical, members in grouped.values():
            canonical.aliases = self._collect_aliases(members, canonical.name)

    def preview(self, document_id: str) -> tuple[pd.DataFrame, str, str]:
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")
        existing_run = self.db.scalar(
            select(EntityResolutionRun.id).where(EntityResolutionRun.document_id == document_id).limit(1)
        )
        if existing_run is not None:
            raise ValueError("Tài liệu đã có ER run. Hãy gọi API reset ER trước khi preview lại.")

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
            "pair_id", "run_id", "entity_a_id", "entity_a", "evidence_a",
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
            "run_id": candidate.run_id,
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
        self, document_id: str, run_id: str, raw_ids_a: set[str], raw_ids_b: set[str]
    ) -> bool:
        if not raw_ids_a or not raw_ids_b:
            return False
        pairs = self.db.scalars(
            select(EntityCandidate).where(
                EntityCandidate.document_id == document_id,
                EntityCandidate.run_id == run_id,
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
        # Guard against corrupt/cross-document candidate rows and incompatible
        # entity classes. Never silently merge unlike semantic node types.
        if (
            canonical_a.document_id != candidate.document_id
            or canonical_b.document_id != candidate.document_id
        ):
            candidate.review_status = "BLOCKED_CONFLICT"
            candidate.error_message = "Candidate chứa entity ngoài phạm vi tài liệu."
            return None
        if (canonical_a.entity_type or "").strip().casefold() != (
            canonical_b.entity_type or ""
        ).strip().casefold():
            candidate.review_status = "BLOCKED_CONFLICT"
            candidate.error_message = (
                f"Không thể gộp khác entity_type: "
                f"{canonical_a.entity_type} != {canonical_b.entity_type}."
            )
            return None
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
            candidate.document_id, candidate.run_id, members_a, members_b
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
        # Bulk reassignment changes the membership rows used by the next pair
        # in an A-B-C chain; expire cached ORM objects before resolving again.
        self.db.expire_all()
        return survivor.id

    def decide(self, document_id: str, pair_id: str, decision: str) -> dict:
        candidate = self.db.get(EntityCandidate, pair_id)
        if candidate is None or candidate.document_id != document_id:
            raise LookupError("Không tìm thấy cặp candidate thuộc tài liệu này.")
        run = self.db.get(EntityResolutionRun, candidate.run_id)
        if run is None or run.document_id != document_id or run.status == "FINALIZED":
            raise ValueError("Lần chạy ER đã finalize hoặc không còn hợp lệ.")
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

    def _apply_auto_merge(self, document_id: str, run_id: str) -> dict:
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
        for candidate in candidates:
            result = self._merge_candidate(candidate)
            if result is None:
                blocked += 1
            else:
                merged += 1
        return {
            "auto_candidates": len(candidates),
            "merged_or_already_same_cluster": merged,
            "blocked_by_keep_separate": blocked,
        }

    def auto_merge(self, document_id: str, run_id: str) -> dict:
        """Apply only AUTO_MERGE candidates; this does not finalize the run."""
        run = self.db.get(EntityResolutionRun, run_id)
        if run is None or run.document_id != document_id:
            raise LookupError("Không tìm thấy lần chạy ER thuộc tài liệu này.")
        if run.status == "FINALIZED":
            raise ValueError("Lần chạy ER đã finalize; không thể thay đổi kết quả.")
        try:
            result = self._apply_auto_merge(document_id, run_id)
            self._refresh_canonical_aliases(document_id)
            self.db.commit()
            return {"run_id": run_id, **result}
        except Exception:
            self.db.rollback()
            raise

    def _canonical_entities_payload(self, document_id: str) -> list[dict]:
        rows = self.db.execute(
            select(CanonicalEntity, CanonicalEntityMember.raw_entity_id)
            .outerjoin(
                CanonicalEntityMember,
                CanonicalEntityMember.canonical_entity_id == CanonicalEntity.id,
            )
            .where(
                CanonicalEntity.document_id == document_id,
                CanonicalEntityMember.document_id == document_id,
                CanonicalEntity.merged_into_id.is_(None),
                CanonicalEntityMember.raw_entity_id.is_not(None),
            )
            .order_by(CanonicalEntity.name, CanonicalEntity.id)
        ).all()
        grouped: dict[str, dict] = {}
        for canonical, raw_id in rows:
            item = grouped.setdefault(canonical.id, {
                "canonical_entity_id": canonical.id,
                "name": canonical.name,
                "entity_type": canonical.entity_type,
                "aliases": list(canonical.aliases or []),
                "raw_entity_ids": [],
            })
            if raw_id:
                item["raw_entity_ids"].append(raw_id)
        return list(grouped.values())

    def _canonical_relations_payload(self, document_id: str) -> tuple[list[dict], int]:
        """Map raw edges to canonical endpoints and collapse duplicate edges."""
        subject_member = aliased(CanonicalEntityMember)
        object_member = aliased(CanonicalEntityMember)
        subject_canonical = aliased(CanonicalEntity)
        object_canonical = aliased(CanonicalEntity)
        rows = self.db.execute(
            select(
                RawRelation.id, RawRelation.subject_entity_id, RawRelation.object_entity_id,
                RawRelation.relation_type, RawRelation.description, RawRelation.evidence,
                subject_member.canonical_entity_id, object_member.canonical_entity_id,
                subject_canonical.name, object_canonical.name,
            )
            .join(subject_member, subject_member.raw_entity_id == RawRelation.subject_entity_id)
            .join(object_member, object_member.raw_entity_id == RawRelation.object_entity_id)
            .join(subject_canonical, subject_canonical.id == subject_member.canonical_entity_id)
            .join(object_canonical, object_canonical.id == object_member.canonical_entity_id)
            .where(
                RawRelation.document_id == document_id,
                subject_member.document_id == document_id,
                object_member.document_id == document_id,
                subject_canonical.document_id == document_id,
                object_canonical.document_id == document_id,
                subject_canonical.merged_into_id.is_(None),
                object_canonical.merged_into_id.is_(None),
            )
            .order_by(RawRelation.id)
        ).all()

        grouped: dict[tuple[str, str, str], dict] = {}
        self_loops = 0
        for row in rows:
            raw_id, raw_subject, raw_object, rel_type, description, evidence, c_subject, c_object, s_name, o_name = row
            # A relation whose endpoints collapse to the same canonical node is
            # not useful as an inter-entity edge. Keep the raw relation intact.
            if c_subject == c_object:
                self_loops += 1
                continue
            normalized_type = " ".join((rel_type or "").split()).casefold()
            key = (c_subject, c_object, normalized_type)
            item = grouped.setdefault(key, {
                "canonical_subject_id": c_subject,
                "canonical_subject_name": s_name,
                "canonical_object_id": c_object,
                "canonical_object_name": o_name,
                "relation_type": rel_type,
                "descriptions": [],
                "evidence": [],
                "raw_relation_ids": [],
                "raw_subject_entity_ids": [],
                "raw_object_entity_ids": [],
                "raw_subject_entity_id": raw_subject,
                "raw_object_entity_id": raw_object,
                "raw_relation_count": 0,
            })
            item["raw_relation_ids"].append(raw_id)
            if raw_subject not in item["raw_subject_entity_ids"]:
                item["raw_subject_entity_ids"].append(raw_subject)
            if raw_object not in item["raw_object_entity_ids"]:
                item["raw_object_entity_ids"].append(raw_object)
            item["raw_relation_count"] += 1
            if description and description not in item["descriptions"]:
                item["descriptions"].append(description)
            evidence_values = evidence if isinstance(evidence, list) else [evidence]
            for value in evidence_values:
                if value and value not in item["evidence"]:
                    item["evidence"].append(value)

        result = []
        for item in grouped.values():
            item["description"] = " | ".join(item.pop("descriptions"))
            result.append(item)
        result.sort(key=lambda item: (
            item["canonical_subject_name"], item["relation_type"],
            item["canonical_object_name"],
        ))
        return result, self_loops

    def finalize(self, document_id: str, run_id: str) -> dict:
        """Commit the final ER state and export an auditable workbook.

        Explicit user decisions are preserved. Remaining AUTO_MERGE candidates
        are merged; all other PENDING candidates become SKIP, never
        KEEP_SEPARATE. SKIP is not a semantic assertion of distinct identity.
        """
        run = self.db.get(EntityResolutionRun, run_id)
        if run is None or run.document_id != document_id:
            raise LookupError("Không tìm thấy lần chạy ER thuộc tài liệu này.")
        if run.status == "FINALIZED":
            raise ValueError("Lần chạy ER này đã được finalize trước đó.")
        report_path = None
        try:
            auto_result = self._apply_auto_merge(document_id, run_id)

            pending = list(self.db.scalars(
                select(EntityCandidate).where(
                    EntityCandidate.document_id == document_id,
                    EntityCandidate.run_id == run_id,
                    EntityCandidate.review_status == "PENDING",
                )
            ).all())
            for candidate in pending:
                candidate.decision = "SKIP"
                candidate.review_status = "SKIPPED"
                candidate.reviewed_at = datetime.now(timezone.utc)

            self._refresh_canonical_aliases(document_id)
            entities = self._canonical_entities_payload(document_id)
            relations, self_loop_count = self._canonical_relations_payload(document_id)
            candidates = self.list_candidates(document_id, run_id)

            counts = self.db.execute(
                select(EntityCandidate.review_status, EntityCandidate.decision)
                .where(
                    EntityCandidate.document_id == document_id,
                    EntityCandidate.run_id == run_id,
                )
            ).all()
            summary = {
                "candidate_count": len(counts),
                "merged_count": sum(1 for status, decision in counts if status == "MERGED" or decision == "MERGE"),
                "kept_separate_count": sum(1 for status, decision in counts if decision == "KEEP_SEPARATE"),
                "skipped_count": sum(1 for status, decision in counts if status == "SKIPPED" or decision == "SKIP"),
                "blocked_conflict_count": sum(1 for status, _ in counts if status == "BLOCKED_CONFLICT"),
                "canonical_entity_count": len(entities),
                "canonical_relation_count": len(relations),
                "deduplicated_relation_count": sum(item["raw_relation_count"] - 1 for item in relations),
                "removed_self_loop_count": self_loop_count,
            }
            report_path = self.report_writer.write_final(
                document_id=document_id,
                run_id=run_id,
                candidates=candidates,
                canonical_entities=entities,
                canonical_relations=relations,
                summary={**summary, **auto_result, "defaulted_to_skip": len(pending)},
            )
            run.report_path = str(report_path)
            run.status = "FINALIZED"
            run.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return {
                "document_id": document_id,
                "run_id": run_id,
                "status": run.status,
                **summary,
                **auto_result,
                "defaulted_to_skip": len(pending),
                "report_path": str(report_path),
                "canonical_entities": entities,
                "canonical_relations": relations,
            }
        except Exception:
            self.db.rollback()
            if report_path:
                try:
                    report_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def reset(self, document_id: str) -> dict:
        """Delete ER-dependent rows only. Raw extraction and FAISS cache are preserved."""
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")

        runs = list(self.db.scalars(
            select(EntityResolutionRun).where(EntityResolutionRun.document_id == document_id)
        ).all())
        if any(run.sync_status != "NOT_SYNCED" for run in runs):
            raise ValueError(
                "Tài liệu đã đồng bộ Neo4j. Hãy xóa graph của document khỏi Neo4j trước khi reset."
            )
        try:
            # Break self-referencing RESTRICT edges before deleting canonical rows.
            self.db.execute(
                update(CanonicalEntity)
                .where(CanonicalEntity.document_id == document_id)
                .values(merged_into_id=None)
            )
            self.db.execute(
                delete(CanonicalEntityMember).where(
                    CanonicalEntityMember.document_id == document_id
                )
            )
            self.db.execute(
                delete(CanonicalEntity).where(CanonicalEntity.document_id == document_id)
            )
            self.db.execute(
                delete(EntityCandidate).where(EntityCandidate.document_id == document_id)
            )
            self.db.execute(
                delete(EntityResolutionRun).where(EntityResolutionRun.document_id == document_id)
            )
            self.db.commit()
            return {
                "document_id": document_id,
                "status": "RESET",
                "deleted_runs": len(runs),
                "preserved": [
                    "raw_entities", "raw_relations", "document_chunks",
                    "chunk_extraction_runs", "FAISS .index", "FAISS .meta.json",
                    "ER report files",
                ],
            }
        except Exception:
            self.db.rollback()
            raise

    def canonical_entities(self, document_id: str) -> list[dict]:
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")
        self._ensure_canonical_members(document_id)
        self._refresh_canonical_aliases(document_id)
        result = self._canonical_entities_payload(document_id)
        self.db.commit()
        return result

    def canonical_relations(self, document_id: str) -> list[dict]:
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")
        self._ensure_canonical_members(document_id)
        result, _self_loops = self._canonical_relations_payload(document_id)
        self.db.commit()
        return result
