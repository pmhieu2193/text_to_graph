from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document
from app.models.extraction import RawEntity, RawRelation

router = APIRouter(tags=["Raw Extraction"])

@router.get("/documents/{document_id}/raw-entities")
def list_raw_entities(document_id: str, search: str | None = Query(None, max_length=200), entity_type: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    stmt = select(RawEntity).where(RawEntity.document_id == document_id)
    count_stmt = select(func.count()).select_from(RawEntity).where(RawEntity.document_id == document_id)
    if search:
        condition = RawEntity.name.ilike(f"%{search.strip()}%")
        stmt, count_stmt = stmt.where(condition), count_stmt.where(condition)
    if entity_type:
        stmt, count_stmt = stmt.where(RawEntity.entity_type == entity_type), count_stmt.where(RawEntity.entity_type == entity_type)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(RawEntity.name).offset((page - 1) * page_size).limit(page_size)).all()
    items = [{"name": x.name, "entity_type": x.entity_type, "aliases": x.aliases or [], "description": x.description, "evidence": x.evidence or [], "confidence": x.confidence} for x in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}

@router.get("/documents/{document_id}/raw-relations")
def list_raw_relations(document_id: str, search: str | None = Query(None, max_length=200), relation_type: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    if db.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    stmt = select(RawRelation).where(RawRelation.document_id == document_id)
    count_stmt = select(func.count()).select_from(RawRelation).where(RawRelation.document_id == document_id)
    if relation_type:
        stmt, count_stmt = stmt.where(RawRelation.relation_type == relation_type), count_stmt.where(RawRelation.relation_type == relation_type)
    if search:
        ids = select(RawEntity.id).where(RawEntity.document_id == document_id, RawEntity.name.ilike(f"%{search.strip()}%"))
        condition = RawRelation.subject_entity_id.in_(ids) | RawRelation.object_entity_id.in_(ids)
        stmt, count_stmt = stmt.where(condition), count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(RawRelation.relation_type).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for row in rows:
        subject, obj = db.get(RawEntity, row.subject_entity_id), db.get(RawEntity, row.object_entity_id)
        items.append({"subject": subject.name if subject else "Unknown", "relation_type": row.relation_type, "object": obj.name if obj else "Unknown", "description": row.description, "evidence": row.evidence, "confidence": row.confidence})
    return {"items": items, "total": total, "page": page, "page_size": page_size}