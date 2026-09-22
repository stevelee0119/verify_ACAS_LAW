"""제15장 Chain of Custody 및 감사추적.

event_hash = SHA256(previous_hash + canonical_json(event_payload))
각 이벤트는 previous_hash를 포함해 중간 Audit Log 변경을 탐지할 수 있게 한다.
사용자의 Review로 원래 AI Finding과 Audit Trail을 삭제하지 않는다(부록 C 제7항).
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

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


class AuditChainConflict(RuntimeError):
    """동시 기록 경합을 해소하지 못했다. 체인을 깨뜨리는 대신 실패시킨다."""


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def last(self) -> Optional[AuditEvent]: ...
    def all(self) -> List[AuditEvent]: ...

    # 선택 규약. 구현하면 "직전 이벤트 조회 → 해시 계산 → 적재"를 Sink가
    # 하나의 임계구역으로 묶는다. 이 구간이 쪼개지면 두 기록자가 같은
    # previous_hash를 읽어 체인이 갈라진다.
    # def append_chained(self, build: Callable[[Optional[AuditEvent]], AuditEvent]) -> AuditEvent: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def last(self) -> Optional[AuditEvent]:
        with self._lock:
            return self._events[-1] if self._events else None

    def all(self) -> List[AuditEvent]:
        with self._lock:
            return list(self._events)

    def append_chained(self, build):
        with self._lock:
            event = build(self._events[-1] if self._events else None)
            self._events.append(event)
            return event

    def append_chained_many(self, builds):
        with self._lock:
            created = []
            previous = self._events[-1] if self._events else None
            for build in builds:
                previous = build(previous)
                self._events.append(previous)
                created.append(previous)
            return created


class AuditChain:
    """Append-only 해시 체인. 기존 이벤트는 수정·삭제하지 않는다."""

    def __init__(self, sink: Optional[AuditSink] = None) -> None:
        self.sink = sink or InMemoryAuditSink()

    def _builder(
        self,
        event_type: AuditEventType,
        payload: Dict[str, Any],
        *,
        actor: str = "system",
        project_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> Callable[[Optional[AuditEvent]], AuditEvent]:
        """직전 이벤트를 받아 다음 이벤트를 만드는 함수. 단건·묶음이 공유한다."""
        def build(last: Optional[AuditEvent]) -> AuditEvent:
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
            return AuditEvent(
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                previous_hash=previous_hash,
                event_hash=compute_event_hash(previous_hash, body),
                actor=actor,
                project_id=project_id,
                document_id=document_id,
            )

        return build

    def record(
        self,
        event_type: AuditEventType,
        payload: Dict[str, Any],
        *,
        actor: str = "system",
        project_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> AuditEvent:
        build = self._builder(event_type, payload, actor=actor,
                              project_id=project_id, document_id=document_id)

        # 직전 이벤트를 읽고 적재하기까지가 하나의 임계구역이어야 한다.
        # 이 사이에 다른 기록자가 끼어들면 두 이벤트가 같은 previous_hash를
        # 물고 들어가 체인이 갈라진다. Sink가 그 보장을 제공하면 위임한다.
        chained: Optional[Callable[..., AuditEvent]] = getattr(self.sink, "append_chained", None)
        if chained is not None:
            return chained(build)
        event = build(self.sink.last())
        self.sink.append(event)
        return event

    def record_many(self, items) -> List[AuditEvent]:
        """여러 이벤트를 한 번에 잇는다.

        결과 체인은 하나씩 기록한 것과 같다. 다른 점은 트랜잭션 수뿐이다.
        출처 조회 기록처럼 한 문서에 수천 건이 나오는 경우, 건마다 트랜잭션을
        열면 그 쓰기가 DB 쓰기 잠금을 독차지해 다른 작업이 밀린다.

        items는 (event_type, payload) 또는 (event_type, payload, kwargs)다.
        """
        builds = []
        for item in items:
            event_type, payload = item[0], item[1]
            kwargs = item[2] if len(item) > 2 else {}
            builds.append(self._builder(event_type, payload, **kwargs))
        if not builds:
            return []
        batched = getattr(self.sink, "append_chained_many", None)
        if batched is not None:
            return list(batched(builds))
        events = []
        for build in builds:
            event = build(self.sink.last())
            self.sink.append(event)
            events.append(event)
        return events

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
