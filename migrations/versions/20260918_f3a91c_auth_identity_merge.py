"""Merge password authentication and workspace identity without replacing users.

Both branches retain their published ancestry. Password credentials and legacy
sessions remain in users/session_tokens; identity records refer to those same
user IDs, so project ownership and membership do not need to be rewritten.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "f3a91c"
down_revision = ("e2fc39", "b2d5f88c0e31")
branch_labels = None
depends_on = None


def upgrade():
    users = sa.table(
        "users",
        sa.column("id", sa.String(40)),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    accounts = sa.table(
        "identity_accounts",
        sa.column("user_id", sa.String(40)),
        sa.column("enabled", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    # Existing account enablement may be stricter than users.is_active. Never
    # overwrite it or mint replacement credentials while joining the branches.
    missing_accounts = sa.select(
        users.c.id,
        users.c.is_active,
        sa.func.coalesce(users.c.created_at, sa.literal(datetime.utcnow())),
    ).where(~sa.exists().where(accounts.c.user_id == users.c.id))
    op.get_bind().execute(
        accounts.insert().from_select(
            ["user_id", "enabled", "created_at"], missing_accounts
        )
    )


def downgrade():
    raise RuntimeError(
        "Merged identity and authentication history must be retained; "
        "restore a verified backup for rollback."
    )
