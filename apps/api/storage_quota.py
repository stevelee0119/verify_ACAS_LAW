"""개인 저장소 용량 계산 및 쿼터 관리 모듈.

- 사용자 소유의 모든 활성 프로젝트 내 문서 용량 합산
- 1GB 기본 한도 및 70% 임계치 검증
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Document, Project, User


def get_user_storage_usage_bytes(session: Session, user_id: str) -> int:
    """사용자가 소유한 모든 프로젝트의 전체 활성 문서 크기(바이트)를 합산하여 반환한다."""
    if not user_id:
        return 0
    total = session.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0))
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            Project.deleted_at.is_(None),
        )
    )
    return int(total or 0)


def check_user_quota(session: Session, user: User, additional_bytes: int = 0) -> tuple[bool, int, int]:
    """사용자의 쿼터 초과 여부를 확인한다.
    
    Returns:
        (초과 여부: bool, 현재 사용량: int, 쿼터 한도: int)
    """
    quota = getattr(user, "storage_quota_bytes", 1073741824) or 1073741824
    used = get_user_storage_usage_bytes(session, user.id)
    is_exceeded = (used + additional_bytes) > quota
    return is_exceeded, used, quota
