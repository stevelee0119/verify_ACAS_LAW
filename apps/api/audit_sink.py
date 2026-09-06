"""DB 기반 Audit Sink. Append-only 해시 체인을 DB에 보존한다(제15.3장)."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.audit_engine import AuditEvent
from packages.common.enums import AuditEventType

from .db import AuditEventRow


class DBAuditSink:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: AuditEvent) -> None:
        self.session.add(
            AuditEventRow(
                sequence=event.sequence,
                project_id=event.project_id,
                document_id=event.document_id,
                event_type=str(event.event_type),
                actor=event.actor,
                payload=event.payload,
                previous_hash=event.previous_hash,
                event_hash=event.event_hash,
                created_at=event.created_at,
            )
        )
        self.session.commit()

    def last(self) -> Optional[AuditEvent]:
        row = self.session.execute(
            select(AuditEventRow).order_by(AuditEventRow.sequence.desc()).limit(1)
        ).scalar_one_or_none()
        return _to_event(row) if row else None

    def all(self) -> List[AuditEvent]:
        rows = self.session.execute(select(AuditEventRow).order_by(AuditEventRow.sequence)).scalars().all()
        return [_to_event(r) for r in rows]


def _to_event(row: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        sequence=row.sequence,
        event_type=AuditEventType(row.event_type),
        payload=row.payload or {},
        previous_hash=row.previous_hash,
        event_hash=row.event_hash,
        created_at=row.created_at,
        actor=row.actor or "system",
        project_id=row.project_id,
        document_id=row.document_id,
    )
