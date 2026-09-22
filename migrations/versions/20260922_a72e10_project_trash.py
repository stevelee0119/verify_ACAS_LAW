"""Reversible project deletion without removing evidence or audit history."""
from alembic import op
import sqlalchemy as sa

revision = "a72e10"
down_revision = "f3a91c"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("projects")}
    for column in (sa.Column("deleted_at", sa.DateTime()), sa.Column("deleted_by", sa.String(80))):
        if column.name not in columns:
            op.add_column("projects", column)
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("projects")}
    if "ix_projects_deleted_at" not in indexes:
        op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])


def downgrade():
    raise RuntimeError("Project trash history must not be discarded; restore a verified backup to downgrade")
