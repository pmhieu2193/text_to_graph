from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.chunk import DocumentChunk


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, document):
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def get_by_id(self, document_id):
        return self.db.get(Document, document_id)

    def list(self, page=1, page_size=20, search=None, status=None):
        stmt = select(Document)
        count_stmt = select(func.count()).select_from(Document)
        if search:
            pattern = f"%{search.strip()}%"
            condition = Document.original_filename.ilike(pattern)
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        if status:
            stmt = stmt.where(Document.status == status)
            count_stmt = count_stmt.where(Document.status == status)
        total = self.db.scalar(count_stmt) or 0
        stmt = (
            stmt.order_by(Document.updated_at.desc(), Document.uploaded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt).all()), total

    def save_chunks(self, document_id, chunks):
        self.db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        rows = [DocumentChunk(document_id=document_id, **item) for item in chunks]
        self.db.add_all(rows)
        self.db.commit()
        return rows

    def list_chunks(self, document_id, page=1, page_size=20):
        total = self.db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.document_id == document_id
            )
        ) or 0
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt).all()), total

    def commit(self):
        self.db.commit()

    def refresh(self, obj):
        self.db.refresh(obj)
