"""감사추적 조회 엔드포인트 (제15장)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import accessible_project, current_user, require_admin
from ..db import AuditEventRow, User, get_db
from ..services import make_audit

router = APIRouter(tags=["audit"])


@router.get("/projects/{project_id}/audit")
def list_audit(
    project_id: str,
    limit: int = Query(default=200, le=1000),
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    accessible_project(session, user, project_id)
    rows = (
        session.execute(
            select(AuditEventRow)
            .where(AuditEventRow.project_id == project_id)
            .order_by(AuditEventRow.sequence.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "project_id": project_id,
        "events": [
            {
                "sequence": r.sequence,
                "event_type": r.event_type,
                "actor": r.actor,
                "document_id": r.document_id,
                "payload": r.payload,
                "previous_hash": r.previous_hash,
                "event_hash": r.event_hash,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/audit/verify")
def verify_chain(admin: User = Depends(require_admin),
                 session: Session = Depends(get_db)) -> Dict[str, Any]:
    """Audit Hash Chain 무결성 검증.

    체인은 기관 전체를 가로지르므로 프로젝트 단위로 나눌 수 없다.
    따라서 관리자만 조회한다.
    """
    return make_audit(session).verify()


@router.get("/projects/{project_id}/manifest")
def get_manifest(project_id: str, user: User = Depends(current_user),
                 session: Session = Depends(get_db)) -> Dict[str, Any]:
    accessible_project(session, user, project_id)
    return make_audit(session).manifest(project_id=project_id)
