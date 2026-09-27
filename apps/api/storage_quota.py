"""개인 저장소 용량 계산 및 쿼터 관리 모듈.

- 휴지통을 포함한 사용자 소유 프로젝트의 원본 문서 용량 합산
- 일반 사용자 1GB, 관리자 제한 없음
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Document, Project, User

USER_STORAGE_QUOTA_BYTES = 1024 ** 3


def get_user_storage_limit_bytes(user: User) -> int | None:
    # Role policy also applies to existing accounts with legacy stored quotas.
    return None if user.role == "ADMIN" else USER_STORAGE_QUOTA_BYTES


def get_user_storage_usage_bytes(session: Session, user_id: str) -> int:
    """휴지통에 보존된 원본도 영구 삭제 전까지 사용량에 포함한다."""
    if not user_id:
        return 0
    total = session.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0))
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
        )
    )
    return int(total or 0)


def check_user_quota(session: Session, user: User, additional_bytes: int = 0) -> tuple[bool, int, int | None]:
    """사용자의 쿼터 초과 여부를 확인한다.
    
    Returns:
        (초과 여부, 현재 사용량, 한도). 관리자 한도는 None이다.
    """
    quota = get_user_storage_limit_bytes(user)
    used = get_user_storage_usage_bytes(session, user.id)
    is_exceeded = quota is not None and (used + additional_bytes) > quota
    return is_exceeded, used, quota
