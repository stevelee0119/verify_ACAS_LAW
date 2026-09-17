"""audit_events.sequence UNIQUE

해시 체인의 같은 자리를 두 이벤트가 차지하지 못하게 한다.
동시 기록 시 뒤늦은 쪽이 거부되면 DBAuditSink가 직전 이벤트를 다시 읽어 재시도한다.

Revision ID: a1c4e77b9d20
Revises: 98e07fd05c9e
Create Date: 2026-09-17 06:05:00.000000+00:00
"""
from __future__ import annotations

from alembic import op

revision = 'a1c4e77b9d20'
down_revision = '98e07fd05c9e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 이미 중복 sequence가 쌓인 DB는 제약을 걸 수 없다. 감사추적을 임의로
    # 고치는 것은 부록 C 제7항 위반이므로, 삭제하지 않고 명시적으로 실패시킨다.
    op.create_index("uq_audit_events_sequence", "audit_events", ["sequence"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_audit_events_sequence", table_name="audit_events")
