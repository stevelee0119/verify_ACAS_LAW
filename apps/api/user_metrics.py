"""UTC monthly activity aggregates. Elapsed job time is not CPU/GPU utilization."""
from __future__ import annotations

import calendar
from datetime import datetime

from sqlalchemy import case, cast, extract, func, select
from sqlalchemy.dialects.postgresql import JSONB

from .db import AuditEventRow, Document, Project, User, VerificationRun
from .workspace import ReportJob


def get_month_range(year, month):
    return datetime(year, month, 1), datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59, 999999)


def _seconds(session, end, start):
    value = ((func.julianday(end) - func.julianday(start)) * 86400
             if session.get_bind().dialect.name == "sqlite" else extract("epoch", end - start))
    return case((value > 0, value), else_=0)


def _monthly_metrics(session, users, year, month):
    start, end = get_month_range(year, month)
    ids = [user.id for user in users]
    if not ids:
        return {}
    event = (func.json_extract(AuditEventRow.payload, "$.event")
             if session.get_bind().dialect.name == "sqlite"
             else cast(AuditEventRow.payload, JSONB)["event"].astext)
    logins = dict(session.execute(select(AuditEventRow.actor, func.count()).where(
        AuditEventRow.actor.in_(ids), AuditEventRow.event_type == "API_QUERY",
        event == "LOGIN_SUCCEEDED", AuditEventRow.created_at.between(start, end),
    ).group_by(AuditEventRow.actor)).all())
    runs = {row[0]: row[1:] for row in session.execute(select(
        Project.owner_id, func.count(VerificationRun.id),
        func.coalesce(func.sum(_seconds(session, VerificationRun.finished_at, VerificationRun.started_at)), 0),
    ).join(VerificationRun, VerificationRun.project_id == Project.id).where(
        Project.owner_id.in_(ids), VerificationRun.started_at.between(start, end),
    ).group_by(Project.owner_id))}
    reports = dict(session.execute(select(Project.owner_id, func.coalesce(func.sum(
        _seconds(session, ReportJob.finished_at, ReportJob.created_at)), 0)
    ).join(ReportJob, ReportJob.project_id == Project.id).where(
        Project.owner_id.in_(ids), ReportJob.created_at.between(start, end),
    ).group_by(Project.owner_id)).all())
    storage = dict(session.execute(select(Project.owner_id, func.sum(Document.size_bytes)
    ).join(Document, Document.project_id == Project.id).where(
        Project.owner_id.in_(ids), Project.deleted_at.is_(None),
    ).group_by(Project.owner_id)).all())
    uploads = dict(session.execute(select(Project.owner_id, func.sum(Document.size_bytes)
    ).join(Document, Document.project_id == Project.id).where(
        Project.owner_id.in_(ids), Document.uploaded_at.between(start, end),
    ).group_by(Project.owner_id)).all())
    results = {}
    for user in users:
        used, quota = int(storage.get(user.id) or 0), int(user.storage_quota_bytes or 1073741824)
        uploaded = int(uploads.get(user.id) or 0)
        count, seconds = runs.get(user.id, (0, 0))
        seconds = float(seconds) + float(reports.get(user.id, 0))
        results[user.id] = {
            "year": year, "month": month, "timezone": "UTC",
            "login_count": int(logins.get(user.id, 0)), "verification_count": int(count),
            "storage_used_bytes": used, "storage_used_mb": round(used / 1048576, 2),
            "storage_quota_bytes": quota, "storage_quota_mb": round(quota / 1048576, 2),
            "storage_usage_percent": round(used / quota * 100, 1) if quota else 0,
            "storage_measurement": "CURRENT_ACTIVE_ORIGINALS",
            "monthly_upload_bytes": uploaded, "monthly_upload_mb": round(uploaded / 1048576, 2),
            "compute_seconds": round(seconds, 1), "compute_minutes": round(seconds / 60, 1),
            "compute_measurement": "ELAPSED_JOB_TIME_INCLUDING_WAIT",
        }
    return results


def get_user_monthly_metrics(session, user_id, year, month):
    user = session.get(User, user_id)
    return _monthly_metrics(session, [user] if user else [], year, month).get(user_id, {})


def get_all_users_monthly_metrics(session, year, month, organization_id=None):
    query = select(User)
    if organization_id is not None:
        query = query.where(User.organization_id == organization_id)
    return _monthly_metrics(session, session.scalars(query).all(), year, month)


def get_user_historical_metrics(session, user_id, months=12):
    now, history = datetime.utcnow(), []
    for offset in range(months - 1, -1, -1):
        year, month = divmod(now.year * 12 + now.month - 1 - offset, 12)
        row = get_user_monthly_metrics(session, user_id, year, month + 1)
        # There are no month-end snapshots; do not repeat today's storage as history.
        for key in ("storage_used_bytes", "storage_used_mb", "storage_usage_percent"):
            row[key] = None
        row["storage_measurement"] = "HISTORICAL_SNAPSHOT_UNAVAILABLE"
        history.append(row)
    return history
