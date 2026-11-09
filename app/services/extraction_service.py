from sqlalchemy.orm import Session

from app.models.document import Document

from app.providers.llm.base import (
    LLMProviderError,
)

from app.providers.llm.factory import get_llm_provider

from app.repositories.extraction_repository import (
    ExtractionRepository,
)


class DocumentExtractionService:

    def __init__(
        self,
        db: Session,
        provider=None,
    ):

        self.db = db

        self.repository = ExtractionRepository(db)

        # Cho phép inject provider khi test.
        self.provider = provider or get_llm_provider()

    def extract_document(
        self,
        document_id: str,
        force: bool = False,
    ):

        document = self.db.get(
            Document,
            document_id,
        )

        if document is None:
            raise LookupError(
                "Không tìm thấy tài liệu."
            )

        self.provider.validate_configuration()

        chunks = self.repository.list_chunks(
            document_id
        )

        if not chunks:
            raise ValueError(
                "Tài liệu chưa có chunk. "
                "Hãy gọi API /process trước."
            )

        processed = 0
        skipped = 0
        failed = 0

        for chunk in chunks:

            previous = self.repository.get_run(
                chunk.id
            )

            # Không xử lý lại chunk đã hoàn thành
            # trừ khi force=True.

            if (
                previous
                and previous.status == "COMPLETED"
                and not force
            ):

                skipped += 1
                continue

            # Tránh xử lý đồng thời cùng một chunk.
            # Nếu process cũ đã chết, cho phép reclaim
            # sau 30 phút.

            if (
                previous
                and previous.status == "RUNNING"
                and not self.repository.is_stale_running(previous)
            ):

                skipped += 1
                continue

            self.repository.mark_running(
                document_id=document_id,
                chunk_id=chunk.id,
                provider=self.provider.provider_name,
                model=self.provider.model_name,
            )

            try:

                payload = self.provider.extract(
                    chunk.content
                )

                self.repository.save_result(
                    document_id=document_id,
                    chunk_id=chunk.id,
                    provider=self.provider.provider_name,
                    model=self.provider.model_name,
                    payload=payload,
                )

                processed += 1

            except LLMProviderError as exc:

                self.db.rollback()

                self.repository.mark_failed(
                    chunk.id,
                    str(exc),
                )

                failed += 1

            except Exception as exc:

                self.db.rollback()

                self.repository.mark_failed(
                    chunk.id,
                    f"Unexpected extraction error: {exc}",
                )

                failed += 1

        entities, relations, runs = (
            self.repository.get_document_result(
                document_id
            )
        )

        pending = sum(
            run.status in {"PENDING", "RUNNING"}
            for run in runs
        )

        return {
            "document_id": document_id,

            "provider": self.provider.provider_name,
            "model": self.provider.model_name,

            "total_chunks": len(chunks),

            "processed_chunks": processed,
            "skipped_chunks": skipped,
            "failed_chunks": failed,
            "pending_chunks": pending,

            "entity_count": len(entities),
            "relation_count": len(relations),
        }