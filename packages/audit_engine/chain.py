"""제15장 Chain of Custody 및 감사추적.

event_hash = SHA256(previous_hash + canonical_json(event_payload))
각 이벤트는 previous_hash를 포함해 중간 Audit Log 변경을 탐지할 수 있게 한다.
사용자의 Review로 원래 AI Finding과 Audit Trail을 삭제하지 않는다(부록 C 제7항).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from packages.common.enums import AuditEventType

GENESIS_HASH = "0" * 64


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(previous_hash: str, payload: Dict[str, Any]) -> str:
    return hashlib.sha256((previous_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


@dataclass
class AuditEvent:
    sequence: int
    event_type: AuditEventType
    payload: Dict[str, Any]
    previous_hash: str
    event_hash: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    actor: str = "system"
    project_id: Optional[str] = None
    document_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": str(self.event_type),
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
            "created_at": self.created_at.isoformat(),
            "actor": self.actor,
            "project_id": self.project_id,
            "document_id": self.document_id,
        }


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def last(self) -> Optional[AuditEvent]: ...
    def all(self) -> List[AuditEvent]: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self._events: List[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def last(self) -> Optional[AuditEvent]:
        return self._events[-1] if self._events else None

    def all(self) -> List[AuditEvent]:
        return list(self._events)


class AuditChain:
    """Append-only 해시 체인. 기존 이벤트는 수정·삭제하지 않는다."""

    def __init__(self, sink: Optional[AuditSink] = None) -> None:
        self.sink = sink or InMemoryAuditSink()

    def record(
        self,
        event_type: AuditEventType,
        payload: Dict[str, Any],
        *,
        actor: str = "system",
        project_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> AuditEvent:
        last = self.sink.last()
        previous_hash = last.event_hash if last else GENESIS_HASH
        sequence = (last.sequence + 1) if last else 1
        body = {
            "sequence": sequence,
            "event_type": str(event_type),
            "actor": actor,
            "project_id": project_id,
            "document_id": document_id,
            "payload": payload,
        }
        event = AuditEvent(
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=compute_event_hash(previous_hash, body),
            actor=actor,
            project_id=project_id,
            document_id=document_id,
        )
        self.sink.append(event)
        return event

    def verify(self) -> Dict[str, Any]:
        """체인 무결성을 검증한다."""
        events = self.sink.all()
        previous_hash = GENESIS_HASH
        broken_at: Optional[int] = None
        for index, event in enumerate(events):
            body = {
                "sequence": event.sequence,
                "event_type": str(event.event_type),
                "actor": event.actor,
                "project_id": event.project_id,
                "document_id": event.document_id,
                "payload": event.payload,
            }
            expected = compute_event_hash(previous_hash, body)
            if event.previous_hash != previous_hash or event.event_hash != expected:
                broken_at = index
                break
            previous_hash = event.event_hash
        return {
            "valid": broken_at is None,
            "event_count": len(events),
            "broken_at_index": broken_at,
            "head_hash": events[-1].event_hash if events else GENESIS_HASH,
        }

    def manifest(self, *, project_id: Optional[str] = None) -> Dict[str, Any]:
        """제20.2장 Chain of Custody Manifest JSON."""
        events = [e for e in self.sink.all() if project_id is None or e.project_id == project_id]
        verification = self.verify()
        return {
            "manifest_version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "project_id": project_id,
            "event_count": len(events),
            "chain_valid": verification["valid"],
            "head_hash": verification["head_hash"],
            "events": [e.to_dict() for e in events],
        }
