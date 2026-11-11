"""Add persisted ER candidates, canonical entity clusters and review state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_entity_resolution_hitl"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _add_document_column_if_missing(name, column):
    inspector = inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_columns("documents")}
    if name not in existing:
        op.add_column("documents", column)


def upgrade() -> None:
    # Day-2 columns were historically added through create_all(), which does
    # not ALTER an existing SQLite table. Add them safely when adopting it.
    _add_document_column_if_missing(
        "page_count", sa.Column("page_count", sa.Integer(), nullable=True)
    )
    _add_document_column_if_missing(
        "chunk_count",
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_document_column_if_missing(
        "extracted_text_path", sa.Column("extracted_text_path", sa.String(500), nullable=True)
    )
    _add_document_column_if_missing(
        "processed_at", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_document_column_if_missing(
        "error_message", sa.Column("error_message", sa.Text(), nullable=True)
    )

    op.create_table(
        "entity_resolution_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="COMPLETED"),
        sa.Column("report_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_entity_resolution_runs_document_id", "entity_resolution_runs", ["document_id"])

    op.create_table(
        "entity_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("entity_resolution_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_a_id", sa.String(36), sa.ForeignKey("raw_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_b_id", sa.String(36), sa.ForeignKey("raw_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fuzzy_score", sa.Float(), nullable=True),
        sa.Column("embedding_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("match_method", sa.String(20), nullable=False, server_default="HYBRID"),
        sa.Column("fuzzy_exact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fuzzy_match", sa.JSON(), nullable=True),
        sa.Column("embedding_match", sa.JSON(), nullable=True),
        sa.Column("evidence_a", sa.JSON(), nullable=False),
        sa.Column("evidence_b", sa.JSON(), nullable=False),
        sa.Column("classification", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "entity_a_id", "entity_b_id", name="uq_entity_candidate_run_pair"),
        sa.CheckConstraint("entity_a_id <> entity_b_id", name="ck_entity_candidate_distinct"),
    )
    op.create_index("ix_entity_candidates_run_id", "entity_candidates", ["run_id"])
    op.create_index("ix_entity_candidates_document_id", "entity_candidates", ["document_id"])
    op.create_index("ix_entity_candidates_entity_a_id", "entity_candidates", ["entity_a_id"])
    op.create_index("ix_entity_candidates_entity_b_id", "entity_candidates", ["entity_b_id"])
    op.create_index(
        "ix_entity_candidate_run_class_status",
        "entity_candidates",
        ["run_id", "classification", "review_status"],
    )

    op.create_table(
        "canonical_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("merged_into_id", sa.String(36), sa.ForeignKey("canonical_entities.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_canonical_entities_document_id", "canonical_entities", ["document_id"])
    op.create_index("ix_canonical_entities_entity_type", "canonical_entities", ["entity_type"])
    op.create_index("ix_canonical_entities_merged_into_id", "canonical_entities", ["merged_into_id"])

    op.create_table(
        "canonical_entity_members",
        sa.Column("raw_entity_id", sa.String(36), sa.ForeignKey("raw_entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("canonical_entity_id", sa.String(36), sa.ForeignKey("canonical_entities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_canonical_entity_members_canonical_entity_id", "canonical_entity_members", ["canonical_entity_id"])
    op.create_index("ix_canonical_entity_members_document_id", "canonical_entity_members", ["document_id"])


def downgrade() -> None:
    op.drop_table("canonical_entity_members")
    op.drop_table("canonical_entities")
    op.drop_table("entity_candidates")
    op.drop_table("entity_resolution_runs")
    # Keep compatibility columns on documents: removing them could discard
    # data written by a newer application version.
