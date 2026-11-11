import pandas as pd

from app.services.entity_resolution.embedding_matcher import EmbeddingMatcher
from app.services.entity_resolution.manage_raw_entity import ManageRawEntity
from app.services.entity_resolution.string_matcher import StringMatcher


class EntityResolutionService:
    """Run document-scoped ER in memory; this version previews candidates only."""

    def __init__(
        self,
        db,
        embedding_matcher: EmbeddingMatcher | None = None,
        string_matcher: StringMatcher | None = None,
    ) -> None:
        self.db = db
        self.embedding_matcher = embedding_matcher or EmbeddingMatcher()
        self.string_matcher = string_matcher or StringMatcher()

    def preview(self, document_id: str) -> pd.DataFrame:
        from sqlalchemy import select

        from app.models.document import Document
        from app.models.extraction import RawEntity

        document = self.db.get(Document, document_id)
        if document is None:
            raise LookupError("Không tìm thấy tài liệu.")

        rows = list(
            self.db.scalars(
                select(RawEntity)
                .where(RawEntity.document_id == document_id)
                .order_by(RawEntity.chunk_id, RawEntity.id)
            ).all()
        )

        manager = ManageRawEntity()
        manager.load_from_db(rows)
        manager.clean_entities()

        fuzzy = self.string_matcher.generate(manager)
        semantic = self.embedding_matcher.generate(manager)

        all_pairs = set(fuzzy) | set(semantic)
        records = []

        for pair in sorted(all_pairs):
            string_candidate = fuzzy.get(pair)
            embedding_candidate = semantic.get(pair)

            fuzzy_score = (
                string_candidate.fuzzy_score
                if string_candidate is not None
                else None
            )
            embedding_score = (
                embedding_candidate.embedding_score
                if embedding_candidate is not None
                else None
            )

            # Missing signal is unknown, not a zero score. Only calculate a
            # combined score when both independent retrieval paths found pair.
            final_score = (
                0.45 * fuzzy_score + 0.55 * embedding_score
                if fuzzy_score is not None and embedding_score is not None
                else None
            )

            records.append(
                {
                    "entity_a": pair[0],
                    "entity_b": pair[1],
                    "fuzzy_score": fuzzy_score,
                    "fuzzy_exact": (
                        string_candidate.is_exact
                        if string_candidate is not None
                        else False
                    ),
                    "embedding_score": embedding_score,
                    "final_score": final_score,
                    "fuzzy_match": (
                        string_candidate.matched_variants
                        if string_candidate is not None
                        else None
                    ),
                    "embedding_match": (
                        embedding_candidate.matched_variants
                        if embedding_candidate is not None
                        else None
                    ),
                    "decision": self._decision(
                        string_candidate,
                        fuzzy_score,
                        embedding_score,
                    ),
                }
            )

        return pd.DataFrame.from_records(
            records,
            columns=[
                "entity_a",
                "entity_b",
                "fuzzy_score",
                "fuzzy_exact",
                "embedding_score",
                "final_score",
                "fuzzy_match",
                "embedding_match",
                "decision",
            ],
        )

    @staticmethod
    def _decision(string_candidate, fuzzy_score, embedding_score) -> str:
        # Conservative initial policy. Thresholds are configuration candidates,
        # not validated production thresholds; calibrate using labelled pairs.
        if string_candidate is not None and string_candidate.is_exact:
            return "AUTO_MERGE_CANDIDATE"
        if (
            fuzzy_score is not None
            and embedding_score is not None
            and fuzzy_score >= 0.92
            and embedding_score >= 0.90
        ):
            return "AUTO_MERGE_CANDIDATE"
        if fuzzy_score is not None or embedding_score is not None:
            return "REVIEW"
        return "REJECT"
