import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, settings
from app.models.document import Document, DocumentStatus
from app.repositories.document_repository import DocumentRepository


PDF_SIGNATURE = b"%PDF-"


class DocumentService:
    def __init__(self, db: Session):
        self.repository = DocumentRepository(db)

    async def upload(self, file: UploadFile) -> Document:
        original_name = Path(file.filename or "").name

        if not original_name:
            raise HTTPException(status_code=400, detail="Tên file không hợp lệ.")

        if Path(original_name).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Chỉ chấp nhận file có phần mở rộng .pdf.")

        storage_dir = settings.storage_dir.resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)

        document_id = str(uuid.uuid4())
        stored_filename = f"{document_id}.pdf"
        temp_path = storage_dir / f".{document_id}.uploading"
        final_path = storage_dir / stored_filename

        size = 0
        digest = hashlib.sha256()
        header = b""

        try:
            with temp_path.open("wb") as destination:
                while True:
                    chunk = await file.read(1024 * 1024)  # Read 1 MiB at a time.
                    if not chunk:
                        break

                    if len(header) < len(PDF_SIGNATURE):
                        header += chunk[: len(PDF_SIGNATURE) - len(header)]

                    size += len(chunk)
                    if size > settings.max_upload_size_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File vượt quá giới hạn {settings.max_upload_size_mb} MB.",
                        )

                    digest.update(chunk)
                    destination.write(chunk)

            if size == 0:
                raise HTTPException(status_code=400, detail="File tải lên đang rỗng.")

            if not header.startswith(PDF_SIGNATURE):
                raise HTTPException(
                    status_code=400,
                    detail="Nội dung file không có chữ ký PDF hợp lệ.",
                )

            # Atomic rename: incomplete uploads are never exposed as final files.
            os.replace(temp_path, final_path)

            document = Document(
                id=document_id,
                original_filename=original_name,
                stored_filename=stored_filename,
                file_path=(final_path.resolve().relative_to(BASE_DIR).as_posix() if final_path.resolve().is_relative_to(BASE_DIR) else str(final_path.resolve())),
                content_type="application/pdf",
                file_size=size,
                sha256=digest.hexdigest(),
                status=DocumentStatus.UPLOADED,
            )

            try:
                return self.repository.create(document)
            except Exception:
                # Avoid leaving an orphaned file if the database insert fails.
                final_path.unlink(missing_ok=True)
                raise

        except HTTPException:
            temp_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise
        except Exception:
            temp_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
