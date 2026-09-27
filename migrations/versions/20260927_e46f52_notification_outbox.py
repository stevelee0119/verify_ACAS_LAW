"""Persist user email delivery attempts independently of approval."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e46f52"
down_revision = "d35e41"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text().with_variant(JSONB(), "postgresql")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("attempted_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])
    op.create_index("ix_user_notifications_status", "user_notifications", ["status"])


def downgrade():
    raise RuntimeError("Notification delivery evidence must be preserved")
