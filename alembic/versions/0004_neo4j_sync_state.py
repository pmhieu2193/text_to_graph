"""Track Neo4j synchronization state for finalized ER runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_neo4j_sync_state"
down_revision = "0003_canonical_entity_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("entity_resolution_runs")}
    additions = [
        ("sync_status", sa.Column("sync_status", sa.String(20), nullable=False, server_default="NOT_SYNCED")),
        ("synced_at", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True)),
        ("sync_error", sa.Column("sync_error", sa.Text(), nullable=True)),
        ("neo4j_node_count", sa.Column("neo4j_node_count", sa.Integer(), nullable=False, server_default="0")),
        ("neo4j_relation_count", sa.Column("neo4j_relation_count", sa.Integer(), nullable=False, server_default="0")),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("entity_resolution_runs", column)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("entity_resolution_runs")}
    for name in (
        "neo4j_relation_count",
        "neo4j_node_count",
        "sync_error",
        "synced_at",
        "sync_status",
    ):
        if name in columns:
            op.drop_column("entity_resolution_runs", name)
