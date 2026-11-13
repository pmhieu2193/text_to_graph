from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListResponse, DocumentResponse, ChunkListResponse, ProcessResult
from app.services.document_service import DocumentService
from app.services.processing_service import DocumentProcessingService
from app.services.extraction_service import DocumentExtractionService
from app.services.entity_resolution.service import EntityResolutionService
from app.services.entity_resolution.neo4j_sync import Neo4jGraphSyncService
from app.models.document import DocumentStatus
from app.models.document import Document
from app.models.entity_resolution import EntityResolutionRun


router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await DocumentService(db).upload(file)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=255),
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    items, total = DocumentRepository(db).list(page, page_size, search=search, status=status_filter)
    return dict(items=items, total=total, page=page, page_size=page_size)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = DocumentRepository(db).get_by_id(document_id)
    if doc is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return doc


@router.post("/{document_id}/process", response_model=ProcessResult)
def process_document(document_id: str, db: Session = Depends(get_db)):
    try:
        result = DocumentProcessingService(db).process(document_id)
        return result
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Xử lý PDF thất bại: {exc}") from exc


@router.post("/{document_id}/quick-process")
def quick_process_document(document_id: str, db: Session = Depends(get_db)):
    """Run PDF processing, extraction and ER preview; stop at the failed stage."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    if doc.status != DocumentStatus.UPLOADED:
        raise HTTPException(409, detail={
            "stage": "processing",
            "message": "Quick process chỉ áp dụng cho tài liệu mới upload, chưa chạy quy trình.",
            "current_status": doc.status.value,
        })
    try:
        processing = DocumentProcessingService(db).process(document_id)
    except Exception as exc:
        raise HTTPException(500, detail={"stage": "processing", "message": str(exc)}) from exc

    try:
        extraction = DocumentExtractionService(db).extract_document(document_id)
        if extraction.get("failed_chunks", 0) or extraction.get("pending_chunks", 0):
            raise RuntimeError("Một số chunk extraction chưa hoàn tất.")
        doc = db.get(Document, document_id)
        doc.status = DocumentStatus.EXTRACTED
        doc.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.CHUNKED
            doc.error_message = str(exc)[:2000]
            db.commit()
        raise HTTPException(502, detail={"stage": "extraction", "message": str(exc)}) from exc

    try:
        dataframe, report_path, run_id = EntityResolutionService(db).preview(document_id)
        doc = db.get(Document, document_id)
        doc.status = DocumentStatus.ENTITY_RESOLUTION
        doc.error_message = None
        db.commit()
        return {
            "document_id": document_id,
            "status": doc.status.value,
            "completed_stage": "entity-resolution",
            "run_id": run_id,
            "candidate_count": len(dataframe),
            "report_path": report_path,
        }
    except Exception as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.EXTRACTED
            doc.error_message = str(exc)[:2000]
            db.commit()
        raise HTTPException(502, detail={"stage": "entity-resolution", "message": str(exc)}) from exc


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    keep_neo4j: bool = Query(False, description="Giữ graph trong Neo4j sau khi xóa document local."),
    db: Session = Depends(get_db),
):
    from pathlib import Path
    from sqlalchemy import delete, update
    from app.core.config import settings, BASE_DIR
    from app.models.chunk import DocumentChunk
    from app.models.extraction import ChunkExtractionRun, RawEntity, RawRelation
    from app.models.entity_resolution import (
        CanonicalEntity, CanonicalEntityMember, EntityCandidate, EntityResolutionRun
    )
    from app.services.processing_service import resolve_document_path

    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    runs = list(db.query(EntityResolutionRun).filter(
        EntityResolutionRun.document_id == document_id
    ).all())
    if any(run.sync_status == "SYNCING" for run in runs):
        raise HTTPException(status_code=409, detail="Document đang được đồng bộ Neo4j; hãy thử xóa lại sau khi sync kết thúc.")
    if not keep_neo4j and any(run.sync_status != "NOT_SYNCED" for run in runs):
        try:
            Neo4jGraphSyncService(db).delete_document_graph(document_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Không xóa document vì chưa xóa/kiểm chứng được graph Neo4j: {exc}",
            ) from exc

    pdf_path = resolve_document_path(doc.file_path)
    extracted_path = resolve_document_path(doc.extracted_text_path) if doc.extracted_text_path else None
    try:
        # Explicit deletion order also works when SQLite foreign-key enforcement
        # was disabled in an older local database.
        db.execute(delete(EntityCandidate).where(EntityCandidate.document_id == document_id))
        db.execute(delete(CanonicalEntityMember).where(CanonicalEntityMember.document_id == document_id))
        db.execute(update(CanonicalEntity).where(
            CanonicalEntity.document_id == document_id
        ).values(merged_into_id=None))
        db.execute(delete(CanonicalEntity).where(CanonicalEntity.document_id == document_id))
        db.execute(delete(EntityResolutionRun).where(EntityResolutionRun.document_id == document_id))
        db.execute(delete(RawRelation).where(RawRelation.document_id == document_id))
        db.execute(delete(RawEntity).where(RawEntity.document_id == document_id))
        db.execute(delete(ChunkExtractionRun).where(ChunkExtractionRun.document_id == document_id))
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        db.delete(doc)
        db.commit()
    except Exception:
        db.rollback()
        raise

    removed_files = []
    for path in (pdf_path, extracted_path, settings.extracted_text_dir / f"{document_id}.txt", BASE_DIR / "storage" / "extracted" / f"{document_id}.txt"):
        if path and path.is_file():
            path.unlink(missing_ok=True)
            removed_files.append(str(path))
    # Indexes and reports are named with this document's UUID. Only exact
    # document-specific patterns are removed; other documents are untouched.
    for directory in (settings.er_index_dir, settings.er_report_dir, BASE_DIR / 'storage' / 'entity_resolution' / 'indexes', BASE_DIR / 'storage' / 'entity_resolution' / 'reports'):
        if directory.exists():
            for path in directory.glob(f"*{document_id}*"):
                if path.is_file():
                    path.unlink(missing_ok=True)
                    removed_files.append(str(path))
    return {
        "document_id": document_id,
        "deleted": True,
        "neo4j_graph_kept": keep_neo4j,
        "removed_files": removed_files,
    }


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
def list_chunks(
    document_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    repo = DocumentRepository(db)
    if repo.get_by_id(document_id) is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    items, total = repo.list_chunks(document_id, page, page_size)
    return dict(items=items, total=total, page=page, page_size=page_size)
