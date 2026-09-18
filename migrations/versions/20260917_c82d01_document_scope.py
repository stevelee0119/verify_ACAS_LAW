"""Persist verification scope and immutable execution settings."""
from alembic import op
import sqlalchemy as sa

revision = "c82d01"
down_revision = "a1c4e77b9d20"
branch_labels = None
depends_on = None


def upgrade():
    # The initial migration can create the current metadata on a fresh database.
    def add(table, column):
        columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        if column.name not in columns:
            op.add_column(table, column)

    add("projects", sa.Column("scope_revision", sa.Integer(), nullable=False, server_default="0"))
    add("projects", sa.Column("creation_key", sa.String(80)))
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("projects")}
    if "uq_project_creation_key" not in indexes:
        op.create_index("uq_project_creation_key", "projects", ["creation_key"], unique=True)
    for column in [
        sa.Column("included_in_verification", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope_changed_at", sa.DateTime()), sa.Column("scope_changed_by", sa.String(80)),
        sa.Column("exclusion_reason", sa.Text()), sa.Column("evidence_number", sa.String(120)),
        sa.Column("submitted_by", sa.String(30)),
    ]:
        add("documents", column)
    from apps.api.db import JSONType
    add("verification_runs", sa.Column("input_snapshot", JSONType()))


def downgrade():
    op.drop_column("verification_runs", "input_snapshot")
    for column in ["submitted_by", "evidence_number", "exclusion_reason", "scope_changed_by",
                   "scope_changed_at", "included_in_verification"]:
        op.drop_column("documents", column)
    op.drop_index("uq_project_creation_key", table_name="projects")
    op.drop_column("projects", "creation_key")
    op.drop_column("projects", "scope_revision")
