"""Add canonical entity aliases for merged raw entity names."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_canonical_entity_aliases"
down_revision = "0002_entity_resolution_hitl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("canonical_entities")}
    if "aliases" not in columns:
        op.add_column(
            "canonical_entities",
            sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("canonical_entities")}
    if "aliases" in columns:
        op.drop_column("canonical_entities", "aliases")
