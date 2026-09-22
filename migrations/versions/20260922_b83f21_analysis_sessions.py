"""Bind password sessions to durable analyses without changing existing credentials."""
from alembic import op
from apps.api.identity import AnalysisSessionLease

revision = "b83f21"
down_revision = "a72e10"
branch_labels = None
depends_on = None


def upgrade():
    AnalysisSessionLease.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Active analysis sessions must be preserved; restore a verified backup to downgrade")
