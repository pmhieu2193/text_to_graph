
import pandas as pd

from app.core.config import settings
from app.services.entity_resolution.embedding_matcher import EmbeddingMatcher
from app.services.entity_resolution.manage_raw_entity import ManageRawEntity
from app.services.entity_resolution.report_writer import (
    EntityResolutionReportWriter,
)
from app.services.entity_resolution.string_matcher import StringMatcher


class EntityResolutionService:
    """Document-scoped entity resolution preview."""

    def __init__(
        self,
        db,
        embedding_matcher: EmbeddingMatcher | None = None,
        string_matcher: StringMatcher | None = None,
        report_writer: EntityResolutionReportWriter | None = None,
    ) -> None:
        self.db = db

        self.embedding_matcher = (
            embedding_matcher or EmbeddingMatcher()
        )

        self.string_matcher = (
            string_matcher
            or StringMatcher(top_k=settings.er_string_top_k)
        )

        self.report_writer = (
            report_writer or EntityResolutionReportWriter()
        )

    def preview(self, document_id: str) -> tuple[pd.DataFrame, str]:
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

            final_score = None

            if (
                fuzzy_score is not None
                and embedding_score is not None
            ):
                final_score = (
                    0.45 * fuzzy_score
                    + 0.55 * embedding_score
                )

            records.append({
                "entity_a": pair[0],
                "entity_b": pair[1],

                "fuzzy_score": fuzzy_score,
                "fuzzy_exact": (
                    string_candidate.is_exact
                    if string_candidate else False
                ),

                "embedding_score": embedding_score,
                "final_score": final_score,

                "fuzzy_match": (
                    string_candidate.matched_variants
                    if string_candidate else None
                ),

                "embedding_match": (
                    embedding_candidate.matched_variants
                    if embedding_candidate else None
                ),

                "decision": self._decision(
                    string_candidate,
                    fuzzy_score,
                    embedding_score,
                ),
            })

        columns = [
            "entity_a",
            "entity_b",
            "fuzzy_score",
            "fuzzy_exact",
            "embedding_score",
            "final_score",
            "fuzzy_match",
            "embedding_match",
            "decision",
        ]

        dataframe = pd.DataFrame.from_records(
            records,
            columns=columns,
        )

        report_path = self.report_writer.write(
            document_id=document_id,
            dataframe=dataframe,
        )

        return dataframe, str(report_path)

    @staticmethod
    def _decision(
        string_candidate,
        fuzzy_score,
        embedding_score,
    ) -> str:
        # Exact match không tự động merge mặc định.
        if (
            string_candidate is not None
            and string_candidate.is_exact
            and settings.er_auto_merge_exact
        ):
            return "AUTO_MERGE_CANDIDATE"

        # AUTO cần đồng thời đạt cả hai ngưỡng.
        if (
            fuzzy_score is not None
            and embedding_score is not None
            and fuzzy_score >= settings.er_fuzzy_auto_threshold
            and embedding_score >= settings.er_embedding_auto_threshold
        ):
            return "AUTO_MERGE_CANDIDATE"

        # Chỉ cần một tín hiệu đạt ngưỡng REVIEW.
        fuzzy_review = (
            fuzzy_score is not None
            and fuzzy_score >= settings.er_fuzzy_review_threshold
        )

        embedding_review = (
            embedding_score is not None
            and embedding_score >= settings.er_embedding_review_threshold
        )

        if fuzzy_review or embedding_review:
            return "REVIEW"

        return "REJECT"
