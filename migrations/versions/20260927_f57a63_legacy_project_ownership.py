"""Snapshot legacy projects for a one-time bootstrap-admin ownership transfer."""
from alembic import op
import sqlalchemy as sa

revision = "f57a63"
down_revision = "e46f52"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_project_ownership",
        sa.Column("project_id", sa.String(40), primary_key=True),
        sa.Column("previous_owner_id", sa.String(40)),
        sa.Column("previous_organization_id", sa.String(40)),
        sa.Column("target_owner_id", sa.String(40)),
        sa.Column("migrated_at", sa.DateTime()),
    )
    op.execute(sa.text(
        "INSERT INTO legacy_project_ownership (project_id, previous_owner_id, previous_organization_id) "
        "SELECT id, owner_id, organization_id FROM projects"
    ))


def downgrade():
    raise RuntimeError("Ownership history is preserved; restore a verified backup")
