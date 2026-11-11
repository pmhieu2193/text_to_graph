"""Baseline the existing application schema.

This migration intentionally uses create_all(checkfirst=True) for the legacy
tables. It creates missing tables on a fresh database and leaves existing
tables/data untouched when adopting a database created by the previous app.
New schema changes belong in subsequent explicit Alembic revisions.
"""
from alembic import op

from app.core.database import Base
from app.models.document import Document
from app.models.chunk import DocumentChunk
from app.models.extraction import ChunkExtractionRun, RawEntity, RawRelation

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    legacy_tables = [
        Document.__table__,
        DocumentChunk.__table__,
        ChunkExtractionRun.__table__,
        RawEntity.__table__,
        RawRelation.__table__,
    ]
    Base.metadata.create_all(bind=op.get_bind(), tables=legacy_tables, checkfirst=True)


def downgrade() -> None:
    # Baseline represents pre-existing user data. Do not drop legacy tables.
    pass
