"""Identity, durable verification jobs and centralized cost ledger."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e2fc39"
down_revision = "d14ac2e9b150"
branch_labels = None
depends_on = None


def text(name, size=None, **kw):
    return sa.Column(name, sa.String(size) if size else sa.Text(), **kw)


def timestamp(name, nullable=True):
    return sa.Column(name, sa.DateTime(), nullable=nullable)


def json(name, nullable=False):
    return sa.Column(name, sa.Text().with_variant(postgresql.JSONB(), "postgresql"), nullable=nullable)


def foreign(name, target, primary_key=False):
    return sa.Column(name, sa.String(40), sa.ForeignKey(target), primary_key=primary_key, nullable=False)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    tables = {
        "identity_accounts": [foreign("user_id", "users.id", True), sa.Column("enabled", sa.Boolean(), nullable=False), timestamp("created_at", False)],
        "identity_api_tokens": [text("id", 40, primary_key=True), foreign("user_id", "users.id"),
            text("token_hash", 64, nullable=False, unique=True), text("label", 120, nullable=False),
            timestamp("created_at", False), timestamp("expires_at", False), timestamp("revoked_at")],
        "identity_external": [text("id", 40, primary_key=True), foreign("user_id", "users.id"),
            text("issuer", 500, nullable=False), text("subject", 255, nullable=False), sa.UniqueConstraint("issuer", "subject")],
        "identity_browser_sessions": [text("id", 40, primary_key=True), foreign("user_id", "users.id"),
            text("secret_hash", 64, nullable=False, unique=True), text("source_kind", 12, nullable=False),
            text("source_id", 40, nullable=False), timestamp("created_at", False), timestamp("expires_at", False), timestamp("revoked_at")],
        "durable_jobs": [foreign("run_id", "verification_runs.id", True), foreign("project_id", "projects.id"),
            json("snapshot"), text("snapshot_hash", 64, nullable=False), text("dedup_key", 64, unique=True),
            text("retry_of", 40, unique=True), text("budget_run_id", 40, nullable=False), text("state", 24, nullable=False),
            text("owner", 64), sa.Column("fence", sa.Integer(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False), timestamp("available_at", False), timestamp("lease_expires_at"),
            timestamp("heartbeat_at"), timestamp("dispatch_until"), text("task_id", 80), text("last_error"),
            timestamp("created_at", False), timestamp("updated_at", False)],
        "job_attempts": [sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), foreign("run_id", "verification_runs.id"),
            sa.Column("fence", sa.Integer(), nullable=False), text("owner", 64, nullable=False), text("state", 24, nullable=False),
            text("error"), json("partial_result"), json("executions"), timestamp("started_at", False), timestamp("finished_at"),
            sa.UniqueConstraint("run_id", "fence")],
        "budget_accounts": [text("id", 120, primary_key=True), sa.Column("limit_units", sa.BigInteger(), nullable=False),
            sa.Column("reserved_units", sa.BigInteger(), nullable=False), sa.Column("spent_units", sa.BigInteger(), nullable=False), timestamp("updated_at", False)],
        "budget_reservations": [text("id", 64, primary_key=True), text("run_id", 80, nullable=False), text("monthly_account", 120, nullable=False),
            text("run_account", 120, nullable=False), text("state", 24, nullable=False), sa.Column("reserved_units", sa.BigInteger(), nullable=False),
            sa.Column("charged_units", sa.BigInteger()), json("detail"), timestamp("created_at", False), timestamp("settled_at")],
    }
    indexes = {"identity_api_tokens": ["user_id"], "identity_external": ["user_id"], "identity_browser_sessions": ["user_id"],
        "durable_jobs": ["project_id", "state", "available_at", "lease_expires_at"], "job_attempts": ["run_id"],
        "budget_reservations": ["run_id", "monthly_account"]}
    for name, columns in tables.items():
        if name not in existing:
            op.create_table(name, *columns)
            for column in indexes.get(name, []):
                op.create_index(f"ix_{name}_{column}", name, [column])
    if "review_drafts" in existing and "base_revision" not in {c["name"] for c in sa.inspect(bind).get_columns("review_drafts")}:
        op.add_column("review_drafts", sa.Column("base_revision", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    raise RuntimeError("Identity, review and job history must be preserved; restore a reviewed backup instead")
