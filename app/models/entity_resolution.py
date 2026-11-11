import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EntityResolutionRun(Base):
    __tablename__ = "entity_resolution_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED", server_default="COMPLETED")
    report_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NOT_SYNCED", server_default="NOT_SYNCED"
    )
    sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    neo4j_node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    neo4j_relation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class EntityCandidate(Base):
    __tablename__ = "entity_candidates"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "entity_a_id", "entity_b_id",
            name="uq_entity_candidate_run_pair",
        ),
        CheckConstraint("entity_a_id <> entity_b_id", name="ck_entity_candidate_distinct"),
        Index("ix_entity_candidate_run_class_status", "run_id", "classification", "review_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("entity_resolution_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_a_id: Mapped[str] = mapped_column(
        ForeignKey("raw_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_b_id: Mapped[str] = mapped_column(
        ForeignKey("raw_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )

    fuzzy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_method: Mapped[str] = mapped_column(String(20), nullable=False, default="HYBRID", server_default="HYBRID")
    fuzzy_exact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    fuzzy_match: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_match: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Snapshot evidence so a review remains explainable even if extraction is rerun.
    evidence_a: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_b: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PENDING", server_default="PENDING"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Non-null means this canonical record has been superseded by another one.
    merged_into_id: Mapped[str | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CanonicalEntityMember(Base):
    __tablename__ = "canonical_entity_members"

    # One raw entity can belong to exactly one current canonical cluster.
    raw_entity_id: Mapped[str] = mapped_column(
        ForeignKey("raw_entities.id", ondelete="CASCADE"), primary_key=True
    )
    canonical_entity_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
