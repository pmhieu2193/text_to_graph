import uuid

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class ChunkExtractionRun(Base):
    __tablename__ = "chunk_extraction_runs"

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            name="uq_extraction_run_chunk",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    model_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0"
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RawEntity(Base):
    __tablename__ = "raw_entities"

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "local_id",
            name="uq_raw_entity_chunk_local",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    local_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    entity_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    evidence: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    model_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )


class RawRelation(Base):
    __tablename__ = "raw_relations"

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "local_id",
            name="uq_raw_relation_chunk_local",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    local_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    subject_entity_id: Mapped[str] = mapped_column(
        ForeignKey("raw_entities.id", ondelete="CASCADE"),
        nullable=False,
    )

    object_entity_id: Mapped[str] = mapped_column(
        ForeignKey("raw_entities.id", ondelete="CASCADE"),
        nullable=False,
    )

    relation_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    evidence: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    model_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )