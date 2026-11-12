"""Add document workflow timestamp and status values for frontend pipeline."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_document_workflow"
down_revision = "0005_neo4j_sync_started_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("documents")}
    if "updated_at" not in columns:
        op.add_column(
            "documents",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        bind.execute(sa.text("UPDATE documents SET updated_at = uploaded_at WHERE updated_at IS NULL"))
        with op.batch_alter_table("documents") as batch:
            batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns("documents")}
    if "updated_at" in columns:
        op.drop_column("documents", "updated_at")
