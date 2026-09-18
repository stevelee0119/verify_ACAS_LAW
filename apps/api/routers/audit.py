"""감사추적 조회 엔드포인트 (제15장)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.audit_engine.chain import GENESIS_HASH, compute_event_hash

from ..db import AuditEventRow, get_db
from ..identity import current_principal, filter_project_query, require_project
from ..services import make_audit

router = APIRouter(tags=["audit"])


def _project_events(session: Session, project_id: str):
    require_project(session, project_id)
    return filter_project_query(
        select(AuditEventRow).where(AuditEventRow.project_id == project_id),
        session, AuditEventRow.project_id)


def _event_dict(row: AuditEventRow) -> Dict[str, Any]:
    return {
        "sequence": row.sequence, "event_type": row.event_type, "actor": row.actor,
        "project_id": row.project_id, "document_id": row.document_id, "payload": row.payload,
        "previous_hash": row.previous_hash, "event_hash": row.event_hash,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/projects/{project_id}/audit")
def list_audit(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    rows = (
        session.execute(
            _project_events(session, project_id)
            .order_by(AuditEventRow.sequence.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "project_id": project_id,
        "events": [_event_dict(r) for r in rows],
    }


@router.get("/audit/verify")
def verify_chain(session: Session = Depends(get_db)) -> Dict[str, Any]:
    """Audit Hash Chain 무결성 검증."""
    if not current_principal().is_local:
        raise HTTPException(403, "Global audit verification is restricted to the local owner")
    return make_audit(session).verify()


@router.get("/projects/{project_id}/manifest")
def get_manifest(project_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = session.scalars(_project_events(session, project_id).order_by(AuditEventRow.sequence)).all()
    events = [_event_dict(row) for row in rows]
    hashes_valid = all(
        compute_event_hash(event["previous_hash"], {
            key: event[key] for key in ("sequence", "event_type", "actor", "project_id", "document_id", "payload")
        }) == event["event_hash"] for event in events)
    # Project events may be interleaved with other tenants. Per-event checks do
    # not prove global chain continuity, so never label them as that verification.
    verification = make_audit(session).verify() if current_principal().is_local else None
    return {
        "manifest_version": "1.0", "generated_at": datetime.utcnow().isoformat(),
        "project_id": project_id, "event_count": len(events), "events": events,
        "chain_valid": verification["valid"] if verification else None,
        "event_hashes_valid": hashes_valid,
        "verification_scope": "global_chain" if verification else "project_events",
        "head_hash_scope": "global_chain" if verification else "project_events",
        "head_hash": verification["head_hash"] if verification else (rows[-1].event_hash if rows else GENESIS_HASH),
    }
