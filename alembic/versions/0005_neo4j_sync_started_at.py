"""Track when Neo4j synchronization started for stale-run recovery."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_neo4j_sync_started_at"
down_revision = "0004_neo4j_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("entity_resolution_runs")}
    if "sync_started_at" not in columns:
        op.add_column(
            "entity_resolution_runs",
            sa.Column("sync_started_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("entity_resolution_runs")}
    if "sync_started_at" in columns:
        op.drop_column("entity_resolution_runs", "sync_started_at")
