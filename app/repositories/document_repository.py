from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document


class DocumentRepository:
    """Database access for documents. API routes should not write SQL directly."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, document: Document) -> Document:
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def get_by_id(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

    def list(self, page: int = 1, page_size: int = 20) -> tuple[list[Document], int]:
        total = self.db.scalar(select(func.count()).select_from(Document)) or 0
        statement = (
            select(Document)
            .order_by(Document.uploaded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.scalars(statement).all())
        return items, total
