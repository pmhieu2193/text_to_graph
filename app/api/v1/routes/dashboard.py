from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document, DocumentStatus
from app.models.extraction import RawEntity, RawRelation
from app.models.entity_resolution import EntityCandidate, EntityResolutionRun

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    documents = db.scalar(select(func.count()).select_from(Document)) or 0
    finalized = db.scalar(
        select(func.count()).select_from(Document).where(Document.status.in_([DocumentStatus.FINALIZED, DocumentStatus.NEO4J_SYNCED]))
    ) or 0
    # Count only persisted extraction rows; this also supports documents created
    # before the workflow-status migration.
    raw_entities = db.scalar(select(func.count()).select_from(RawEntity)) or 0
    raw_relations = db.scalar(select(func.count()).select_from(RawRelation)) or 0
    pending_review = db.scalar(
        select(func.count()).select_from(EntityCandidate).join(
            EntityResolutionRun, EntityResolutionRun.id == EntityCandidate.run_id
        ).where(
            EntityResolutionRun.status != "FINALIZED",
            EntityCandidate.review_status == "PENDING",
        )
    ) or 0
    recent = db.scalars(
        select(Document).order_by(Document.uploaded_at.desc()).limit(8)
    ).all()
    return {
        "total_documents": documents,
        "finalized_documents": finalized,
        "raw_entity_count": raw_entities,
        "raw_relation_count": raw_relations,
        "pending_review_count": pending_review,
        "recent_documents": [
            {
                "document_id": item.id,
                "filename": item.original_filename,
                "status": item.status.value,
                "uploaded_at": item.uploaded_at,
                "updated_at": item.updated_at,\n                "file_size": item.file_size,\n                "chunk_count": item.chunk_count,
            } for item in recent
        ],
    }


@router.get("/documents/{document_id}/workflow")
def get_document_workflow(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found.")
    run = db.scalar(
        select(EntityResolutionRun).where(EntityResolutionRun.document_id == document_id)
    )
    raw_entity_count = db.scalar(
        select(func.count()).select_from(RawEntity).where(RawEntity.document_id == document_id)
    ) or 0
    raw_relation_count = db.scalar(
        select(func.count()).select_from(RawRelation).where(RawRelation.document_id == document_id)
    ) or 0
    pending_count = 0
    if run is not None:
        pending_count = db.scalar(
            select(func.count()).select_from(EntityCandidate).where(
                EntityCandidate.run_id == run.id,
                EntityCandidate.review_status == "PENDING",
            )
        ) or 0
    return {
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "status": document.status.value,
            "uploaded_at": document.uploaded_at,
            "updated_at": document.updated_at,
            "page_count": document.page_count,
            "chunk_count": document.chunk_count,
            "file_size": document.file_size,
            "error_message": document.error_message,
        },
        "processing": {"completed": document.status not in {DocumentStatus.UPLOADED, DocumentStatus.FAILED}},
        "extraction": {"completed": document.status in {
            DocumentStatus.EXTRACTED, DocumentStatus.ENTITY_RESOLUTION,
            DocumentStatus.HUMAN_REVIEW, DocumentStatus.FINALIZED, DocumentStatus.NEO4J_SYNCED,
        }, "raw_entity_count": raw_entity_count, "raw_relation_count": raw_relation_count},
        "entity_resolution": {
            "completed": run is not None,
            "run_status": run.status if run else None,
            "pending_count": pending_count,
            "sync_status": run.sync_status if run else "NOT_SYNCED",
        },
        "finalized": bool(run and run.status == "FINALIZED"),
        "neo4j_synced": bool(run and run.sync_status == "SYNCED"),\n        "metrics": {\n            "raw_entity_count": raw_entity_count,\n            "canonical_entity_count": canonical_entity_count,\n            "entity_reduction_count": raw_entity_count - canonical_entity_count,\n            "entity_reduction_percent": entity_reduction,\n            "raw_relation_count": raw_relation_count,\n            "canonical_relation_count": canonical_relation_count,\n            "relation_reduction_count": raw_relation_count - canonical_relation_count,\n            "relation_reduction_percent": relation_reduction,\n            "removed_self_loop_count": removed_self_loop_count,\n        },
    }
