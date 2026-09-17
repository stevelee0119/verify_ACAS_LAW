"""DB 기반 Audit Sink. Append-only 해시 체인을 DB에 보존한다(제15.3장).

해시 체인은 직전 이벤트의 event_hash를 물고 들어간다. 따라서
"직전 이벤트 조회 → 해시 계산 → 적재"가 쪼개지면, 동시에 기록하는 두 주체가
같은 previous_hash를 읽어 체인이 갈라진다. API 요청 스레드와 Worker가
동시에 기록하는 구조(제3.1장)에서는 실제로 발생한다.

두 층으로 막는다.
1. 프로세스 내부: 모듈 전역 락으로 임계구역을 직렬화한다.
2. 프로세스 사이(Celery Worker·다중 API 인스턴스): sequence UNIQUE 제약이
   뒤늦은 기록을 거부하고, 여기서 직전 이벤트를 다시 읽어 재시도한다.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.audit_engine import AuditChainConflict, AuditEvent
from packages.common.enums import AuditEventType

from .db import AuditEventRow

# 같은 프로세스 안의 기록자를 직렬화한다. Sink 인스턴스는 세션마다 새로 만들어지므로
# 락은 인스턴스가 아니라 모듈에 둔다.
_SEQUENCE_LOCK = threading.Lock()
MAX_APPEND_ATTEMPTS = 8
RETRY_BACKOFF_SECONDS = 0.01


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

    def append_chained(self, build: Callable[[Optional[AuditEvent]], AuditEvent]) -> AuditEvent:
        """직전 이벤트 조회부터 적재까지를 하나의 임계구역으로 묶는다."""
        # 호출자가 들고 있던 변경사항이 재시도의 rollback에 말려 사라지지 않도록
        # 감사 이벤트를 다루기 전에 확정한다.
        if self.session.in_transaction():
            self.session.commit()

        for attempt in range(MAX_APPEND_ATTEMPTS):
            with _SEQUENCE_LOCK:
                event = build(self.last())
                try:
                    self.append(event)
                    return event
                except IntegrityError:
                    # 다른 프로세스가 같은 sequence를 선점했다. 다시 읽고 이어 붙인다.
                    self.session.rollback()
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1) * (0.5 + random.random()))

        raise AuditChainConflict(
            f"감사추적 기록이 {MAX_APPEND_ATTEMPTS}회 경합했다. 체인을 깨뜨리지 않기 위해 중단한다."
        )


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
