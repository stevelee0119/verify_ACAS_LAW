"""Track report generation progress so long builds do not hold one HTTP request."""
from alembic import op
from apps.api.workspace import ReportJob

revision = "c94d32"
down_revision = "b83f21"
branch_labels = None
depends_on = None


def upgrade():
    ReportJob.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Report generation history must be preserved; restore a verified backup to downgrade")
