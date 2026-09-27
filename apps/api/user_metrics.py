"""사용자별 월별 활동 및 자원 사용량 집계 엔진 (ACASia_LAW).

- 월별 접속 횟수: audit_events (LOGIN_SUCCEEDED) 및 session_tokens
- 분석 사용 빈도: 사용자 소유 프로젝트의 verification_runs 카운트
- 저장 용량: 누적 활성 파일 크기(MB), 쿼터 대비 사용률(%), 당월 신규 업로드량
- 컴퓨팅 사용량: verification_runs 및 report_jobs 실행 소요 시간 합산
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import AuditEventRow, Document, Project, SessionToken, User, VerificationRun
from .workspace import ReportJob


def get_month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """해당 연월의 시작 시각(1일 00:00:00)과 종료 시각(말일 23:59:59.999999)을 반환한다."""
    last_day = calendar.monthrange(year, month)[1]
    start_dt = datetime(year, month, 1, 0, 0, 0)
    end_dt = datetime(year, month, last_day, 23, 59, 59, 999999)
    return start_dt, end_dt


def get_user_monthly_metrics(session: Session, user_id: str, year: int, month: int) -> Dict[str, Any]:
    """단일 사용자의 특정 월에 대한 4대 핵심 활동 및 자원 통계를 산출한다."""
    start_dt, end_dt = get_month_range(year, month)

    # 1. 월 접속 횟수: 해당 월에 발급된 세션 수 또는 로그인 성공 이벤트 건수
    session_login_count = session.scalar(
        select(func.count(SessionToken.id)).where(
            SessionToken.user_id == user_id,
            SessionToken.issued_at >= start_dt,
            SessionToken.issued_at <= end_dt,
        )
    ) or 0

    audit_login_count = session.scalar(
        select(func.count(AuditEventRow.id)).where(
            AuditEventRow.actor == user_id,
            AuditEventRow.created_at >= start_dt,
            AuditEventRow.created_at <= end_dt,
            AuditEventRow.event_type == "API_QUERY",
        )
    ) or 0
    # 세션 또는 감사 로그 중 실제 집계된 최댓값 채택
    monthly_login_count = max(int(session_login_count), int(audit_login_count))

    # 2. 분석 사용 빈도: 사용자가 소유한 프로젝트에서 실행된 검증 분석 건수
    verification_count = session.scalar(
        select(func.count(VerificationRun.id))
        .join(Project, VerificationRun.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            VerificationRun.started_at >= start_dt,
            VerificationRun.started_at <= end_dt,
        )
    ) or 0

    # 3. 저장 용량:
    # 3-1. 현재 누적 저장 용량 (활성 문서 크기 합산)
    accumulated_bytes = session.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0))
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            Project.deleted_at.is_(None),
        )
    ) or 0

    # 3-2. 당월 신규 업로드 용량
    monthly_upload_bytes = session.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0))
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            Document.uploaded_at >= start_dt,
            Document.uploaded_at <= end_dt,
        )
    ) or 0

    # 4. 컴퓨팅 사용량: 검증 실행 완료 건들의 (finished_at - started_at) 소요 시간 합산
    runs = session.execute(
        select(VerificationRun.started_at, VerificationRun.finished_at)
        .join(Project, VerificationRun.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            VerificationRun.started_at >= start_dt,
            VerificationRun.started_at <= end_dt,
            VerificationRun.finished_at.isnot(None),
        )
    ).all()

    total_compute_seconds = sum(
        max(0.0, (row.finished_at - row.started_at).total_seconds())
        for row in runs if row.started_at and row.finished_at
    )

    # 보고서 빌드 작업(ReportJob) 소요 시간도 반영
    report_jobs = session.execute(
        select(ReportJob.created_at, ReportJob.finished_at)
        .join(Project, ReportJob.project_id == Project.id)
        .where(
            Project.owner_id == user_id,
            ReportJob.created_at >= start_dt,
            ReportJob.created_at <= end_dt,
            ReportJob.finished_at.isnot(None),
        )
    ).all()
    total_compute_seconds += sum(
        max(0.0, (job.finished_at - job.created_at).total_seconds())
        for job in report_jobs if job.created_at and job.finished_at
    )

    user = session.get(User, user_id)
    quota_bytes = getattr(user, "storage_quota_bytes", 1073741824) if user else 1073741824
    usage_pct = round((accumulated_bytes / quota_bytes * 100), 1) if quota_bytes > 0 else 0.0

    return {
        "year": year,
        "month": month,
        "login_count": monthly_login_count,
        "verification_count": int(verification_count),
        "storage_used_bytes": int(accumulated_bytes),
        "storage_used_mb": round(accumulated_bytes / (1024 * 1024), 2),
        "storage_quota_bytes": int(quota_bytes),
        "storage_quota_mb": round(quota_bytes / (1024 * 1024), 2),
        "storage_usage_percent": usage_pct,
        "monthly_upload_bytes": int(monthly_upload_bytes),
        "monthly_upload_mb": round(monthly_upload_bytes / (1024 * 1024), 2),
        "compute_seconds": round(total_compute_seconds, 1),
        "compute_minutes": round(total_compute_seconds / 60.0, 1),
    }


def get_all_users_monthly_metrics(session: Session, year: int, month: int) -> Dict[str, Dict[str, Any]]:
    """모든 사용자의 해당 월 지표를 딕셔너리({user_id: metrics}) 형태로 일괄 반환한다."""
    users = session.scalars(select(User)).all()
    return {u.id: get_user_monthly_metrics(session, u.id, year, month) for u in users}


def get_user_historical_metrics(session: Session, user_id: str, months: int = 12) -> List[Dict[str, Any]]:
    """최근 N개월간의 월별 지표 추이 리스트를 시간 순서대로 반환한다."""
    now = datetime.utcnow()
    history = []
    for i in range(months - 1, -1, -1):
        target_year = now.year
        target_month = now.month - i
        while target_month <= 0:
            target_month += 12
            target_year -= 1
        history.append(get_user_monthly_metrics(session, user_id, target_year, target_month))
    return history
