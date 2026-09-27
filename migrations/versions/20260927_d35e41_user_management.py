"""사용자 관리 및 저장소 용량 쿼터 필드 추가 마이그레이션.

- users 테이블에 전화번호, 소속, 가입사유, 승인상태, 쿼터 등의 컬럼 추가
- 기존 활성 사용자는 자동으로 APPROVED 처리
- 관리자 계정 초기 정보 보장
"""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = "d35e41"
down_revision = "c94d32"
branch_labels = None
depends_on = None


def upgrade():
    # users 테이블에 사용자 관리 및 쿼터 컬럼 추가
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("phone_number", sa.String(30), nullable=True, server_default=""))
        batch_op.add_column(sa.Column("affiliation", sa.String(150), nullable=True, server_default=""))
        batch_op.add_column(sa.Column("registration_reason", sa.Text(), nullable=True, server_default=""))
        batch_op.add_column(sa.Column("approval_status", sa.String(20), nullable=False, server_default="PENDING"))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("approved_by", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True, server_default=""))
        batch_op.add_column(sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=False, server_default="1073741824"))
        batch_op.add_column(sa.Column("quota_warning_sent_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_users_approval_status", ["approval_status"])

    bind = op.get_bind()
    # 기존에 등록된 사용자들은 APPROVED 상태로 전환
    bind.execute(
        sa.text("UPDATE users SET approval_status = 'APPROVED' WHERE is_active = true")
    )
    # 기존 관리자 계정 정보 갱신 (요구사항 2 반영)
    bind.execute(
        sa.text(
            "UPDATE users SET display_name = '이창민', affiliation = '종합행정학교 법무교육단', "
            "phone_number = '010-4724-1500', registration_reason = '프로그램 개발' "
            "WHERE role = 'ADMIN' AND (display_name IS NULL OR display_name = '' OR display_name = '관리자')"
        )
    )


def downgrade():
    raise RuntimeError("사용자 관리 및 감사 추적 이력은 보존되어야 하므로 다운그레이드를 허용하지 않습니다.")
