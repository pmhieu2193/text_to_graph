import logging
import time
import random
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entity_resolution import CanonicalEntity, EntityResolutionRun

from app.models.document import Document

from app.providers.llm.base import (
    LLMConfigurationError,
    LLMOutputError,
    LLMPermanentError,
    LLMProviderError,
    LLMQuotaError,
    LLMTemporaryError,
)

from app.providers.llm.factory import get_llm_provider

from app.repositories.extraction_repository import (
    ExtractionRepository,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


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

    def _process_chunk(
        self,
        document_id: str,
        chunk,
    ) -> None:
        """
        Xử lý một chunk và lưu kết quả.

        Mỗi chunk có transaction riêng.
        """

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

        except Exception as exc:

            # Đảm bảo trạng thái FAILED được ghi lại.
            self.db.rollback()

            self.repository.mark_failed(
                chunk.id,
                f"{type(exc).__name__}: {exc}",
            )

            raise

    def _attempt_with_quota_fallback(
        self,
        document_id: str,
        chunk,
    ) -> None:
        """
        Gọi một chunk.

        Nếu primary key hết quota:
        - Chuyển sang fallback key.
        - Thử lại ngay chunk hiện tại.

        Nếu fallback key cũng hết quota:
        - Raise để Fail-Fast.
        """

        try:

            self._process_chunk(
                document_id,
                chunk,
            )

        except LLMQuotaError:

            switch = getattr(
                self.provider,
                "switch_to_fallback_key",
                None,
            )

            if switch is None or not switch():

                raise LLMQuotaError(
                    "Gemini hết quota và không còn API key dự phòng."
                )

            logger.warning(
                "Đã chuyển sang Gemini fallback key. "
                "Retry chunk_id=%s",
                chunk.id,
            )

            # Thử lại chính chunk vừa gặp lỗi quota.
            self._process_chunk(
                document_id,
                chunk,
            )

    def _wait_before_retry(self, retry_number: int) -> None:

        base_delay = min(
            settings.llm_base_delay * (2 ** (retry_number - 1)),
            settings.llm_max_delay,
        )

        # Jitter: thêm ngẫu nhiên tối đa 25%
        delay = base_delay + random.uniform(
            0,
            base_delay * 0.25,
        )

        logger.info(
            "Retry pass %s: waiting %.2f seconds",
            retry_number,
            delay,
        )

        time.sleep(delay)

    def _retry_chunks(
        self,
        document_id: str,
        chunks: list,
        max_retries: int,
    ) -> list:
        """
        Retry danh sách chunk lỗi.

        Trả về các chunk vẫn thất bại sau khi retry.
        """

        pending = list(chunks)

        for retry_number in range(
            1,
            max_retries + 1,
        ):

            if not pending:
                break

            self._wait_before_retry(
                retry_number
            )

            logger.info(
                "Retry pass %s/%s: %s chunks",
                retry_number,
                max_retries,
                len(pending),
            )

            remaining = []

            for chunk in pending:

                try:

                    self._attempt_with_quota_fallback(
                        document_id,
                        chunk,
                    )

                except (
                    LLMTemporaryError,
                    LLMOutputError,
                ) as exc:

                    logger.warning(
                        "Chunk vẫn lỗi sau retry %s: "
                        "chunk_id=%s, error=%s",
                        retry_number,
                        chunk.id,
                        exc,
                    )

                    remaining.append(chunk)

                except (
                    LLMConfigurationError,
                    LLMPermanentError,
                    LLMProviderError,
                ):

                    # Lỗi không thể phục hồi:
                    # dừng toàn bộ pipeline.
                    raise

                except Exception:

                    # Lỗi lập trình, DB hoặc hệ thống:
                    # không được âm thầm bỏ qua.
                    raise

            pending = remaining

        return pending

    def extract_document(
        self,
        document_id: str,
        force: bool = False,
    ):

        from app.core.config import settings

        document = self.db.get(
            Document,
            document_id,
        )

        if document is None:
            raise LookupError(
                "Không tìm thấy tài liệu."
            )

        # RawEntity IDs are referenced by ER candidates and canonical membership.
        # Never replace extraction rows while an ER run exists; reset ER first.
        existing_er = self.db.scalar(
            select(EntityResolutionRun.id)
            .where(EntityResolutionRun.document_id == document_id)
            .limit(1)
        )
        existing_canonical = self.db.scalar(
            select(CanonicalEntity.id)
            .where(CanonicalEntity.document_id == document_id)
            .limit(1)
        )
        if existing_er is not None or existing_canonical is not None:
            raise ValueError(
                "Tài liệu đã có ER run. Hãy reset Entity Resolution trước khi trích xuất lại."
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

        # Chứa các chunk cần retry.
        deferred_chunks = []

        # =====================================
        # PASS 1: PRIMARY PASS
        # =====================================

        logger.info(
            "Starting Primary Pass: document=%s, chunks=%s",
            document_id,
            len(chunks),
        )

        for chunk in chunks:

            previous = self.repository.get_run(
                chunk.id
            )

            # Bỏ qua chunk đã hoàn thành.
            if (
                previous
                and previous.status == "COMPLETED"
                and not force
            ):

                skipped += 1
                continue

            # Tránh xử lý đồng thời cùng một chunk.
            if (
                previous
                and previous.status == "RUNNING"
                and not self.repository.is_stale_running(previous)
            ):

                skipped += 1
                continue

            try:

                self._attempt_with_quota_fallback(
                    document_id,
                    chunk,
                )

                processed += 1

            except (
                LLMTemporaryError,
                LLMOutputError,
            ) as exc:

                # Lỗi có thể phục hồi:
                # ghi nhận để retry sau.
                logger.warning(
                    "Deferred chunk: chunk_id=%s, error=%s",
                    chunk.id,
                    exc,
                )

                deferred_chunks.append(chunk)

            except (
                LLMConfigurationError,
                LLMPermanentError,
                LLMProviderError,
            ):

                # Fatal error:
                # dừng toàn bộ pipeline.
                raise

            except Exception:

                # Lỗi hệ thống hoặc lỗi lập trình.
                raise

        # =====================================
        # PASS 2: RETRY PASS
        # =====================================

        logger.info(
            "Primary Pass completed. Deferred chunks=%s",
            len(deferred_chunks),
        )

        max_retries = max(
            0,
            settings.llm_max_retries,
        )

        if deferred_chunks and max_retries > 0:

            deferred_chunks = self._retry_chunks(
                document_id=document_id,
                chunks=deferred_chunks,
                max_retries=max_retries,
            )

        # =====================================
        # PASS 3: FALLBACK RETRY PASS
        # =====================================

        # Nếu đã retry primary key mà vẫn còn lỗi,
        # thử chuyển sang fallback key một lần.
        #
        # Nếu fallback đã được sử dụng từ trước
        # do quota error thì không chuyển lại.

        switch = getattr(
            self.provider,
            "switch_to_fallback_key",
            None,
        )

        if (
            deferred_chunks
            and max_retries > 0
            and switch is not None
            and switch()
        ):

            logger.warning(
                "Switching to fallback key for remaining chunks=%s",
                len(deferred_chunks),
            )

            deferred_chunks = self._retry_chunks(
                document_id=document_id,
                chunks=deferred_chunks,
                max_retries=max_retries,
            )

        # =====================================
        # FINAL RESULT
        # =====================================

        entities, relations, runs = (
            self.repository.get_document_result(
                document_id
            )
        )

        failed = sum(
            run.status == "FAILED"
            for run in runs
        )

        # Missing run rows also represent chunks that have not completed.
        pending = max(0, len(chunks) - completed - failed)

        completed = sum(
            run.status == "COMPLETED"
            for run in runs
        )

        logger.info(
            "Extraction completed: document=%s, "
            "completed=%s, failed=%s, skipped=%s",
            document_id,
            completed,
            failed,
            skipped,
        )

        return {
            "document_id": document_id,

            "provider": self.provider.provider_name,
            "model": self.provider.model_name,

            "total_chunks": len(chunks),

            "processed_chunks": processed,
            "skipped_chunks": skipped,

            "completed_chunks": completed,
            "failed_chunks": failed,
            "pending_chunks": pending,

            "entity_count": len(entities),
            "relation_count": len(relations),

            "using_fallback_key": getattr(
                self.provider,
                "using_fallback_key",
                False,
            ),
        }