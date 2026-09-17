"""인증: users 자격증명 컬럼과 session_tokens

Revision ID: b2d5f88c0e31
Revises: a1c4e77b9d20
Create Date: 2026-09-17 12:20:00.000000+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b2d5f88c0e31'
down_revision = 'a1c4e77b9d20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(), nullable=True))

    op.create_table(
        'session_tokens',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        # 토큰 원문은 저장하지 않는다. 유출되어도 세션을 탈취할 수 없게 한다.
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_session_tokens_user_id'), 'session_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_session_tokens_token_hash'), 'session_tokens', ['token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_tokens_token_hash'), table_name='session_tokens')
    op.drop_index(op.f('ix_session_tokens_user_id'), table_name='session_tokens')
    op.drop_table('session_tokens')
    for column in ('locked_until', 'failed_login_count', 'last_login_at', 'is_active', 'password_hash'):
        op.drop_column('users', column)
