import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import BASE_DIR, settings
from app.models.entity_resolution import CanonicalEntity, EntityResolutionRun
from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services.pdf_extractor import PDFExtractor
from app.services.text_chunker import TextChunker

logger = logging.getLogger(__name__)


def resolve_document_path(stored_path: str) -> Path:
    """Resolve current and legacy document paths without depending on cwd."""
    raw = Path(stored_path)
    if raw.is_absolute():
        return raw
    normalized = stored_path.replace("\\", "/")
    legacy_relative = (BASE_DIR / normalized).resolve()
    if normalized.startswith("storage/documents/"):
        normalized = "data/documents/" + normalized.removeprefix("storage/documents/")
    elif normalized.startswith("storage/extracted/"):
        normalized = "data/extracted/" + normalized.removeprefix("storage/extracted/")
    current = (BASE_DIR / normalized).resolve()
    return current if current.exists() or not legacy_relative.exists() else legacy_relative

class DocumentProcessingService:
    def __init__(self, db):
        self.db = db
        self.repo = DocumentRepository(db)
        self.extractor = PDFExtractor()
        self.chunker = TextChunker(settings.chunk_size, settings.chunk_overlap)

    def process(self, document_id):
        doc = self.repo.get_by_id(document_id)
        if doc is None:
            raise LookupError("Không tìm thấy tài liệu.")
        if doc.status == DocumentStatus.PROCESSING:
            raise RuntimeError("Tài liệu đang được xử lý.")

        existing_er = self.db.scalar(
            select(EntityResolutionRun.id)
            .where(EntityResolutionRun.document_id == document_id).limit(1)
        )
        existing_canonical = self.db.scalar(
            select(CanonicalEntity.id)
            .where(CanonicalEntity.document_id == document_id).limit(1)
        )
        if existing_er is not None or existing_canonical is not None:
            raise RuntimeError(
                "Tài liệu đã có ER run. Hãy reset Entity Resolution trước khi xử lý lại PDF."
            )

        source_path = resolve_document_path(doc.file_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy PDF nguồn: {source_path}")

        doc.status = DocumentStatus.PROCESSING
        doc.error_message = None
        self.repo.commit()
        try:
            extracted = self.extractor.extract(str(source_path))
            chunks = self.chunker.split(extracted)
            rows = [
                dict(
                    chunk_index=c.chunk_index,
                    content=c.content,
                    char_count=c.char_count,
                    page_start=c.page_start,
                    page_end=c.page_end,
                )
                for c in chunks
            ]
            # Chunks in SQLite are the canonical extracted-text store. Do not
            # create a duplicate full-text .txt file on disk.
            self.repo.save_chunks(doc.id, rows)
            old_text_path = resolve_document_path(doc.extracted_text_path) if doc.extracted_text_path else None
            if old_text_path and old_text_path.is_file():
                old_text_path.unlink(missing_ok=True)
            doc.extracted_text_path = None
            doc.page_count = len(extracted.pages)
            doc.chunk_count = len(chunks)
            doc.processed_at = datetime.now(timezone.utc)
            doc.status = DocumentStatus.CHUNKED
            doc.error_message = None
            self.repo.commit()
            self.repo.refresh(doc)
            return dict(
                document_id=doc.id,
                status=doc.status,
                page_count=doc.page_count,
                chunk_count=doc.chunk_count,
                extracted_char_count=len(extracted.full_text),
            )
        except Exception as exc:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(exc)[:2000]
            self.repo.commit()
            raise
