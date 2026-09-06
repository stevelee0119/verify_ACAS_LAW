"""감사추적 조회 엔드포인트 (제15장)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import AuditEventRow, get_db
from ..services import make_audit

router = APIRouter(tags=["audit"])


@router.get("/projects/{project_id}/audit")
def list_audit(
    project_id: str,
    limit: int = Query(default=200, le=1000),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
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
def verify_chain(session: Session = Depends(get_db)) -> Dict[str, Any]:
    """Audit Hash Chain 무결성 검증."""
    return make_audit(session).verify()


@router.get("/projects/{project_id}/manifest")
def get_manifest(project_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    return make_audit(session).manifest(project_id=project_id)
