"""제5.1~5.2장 사실관계 원장과 충돌집합.

두 가지를 지킨다.

1. 기록에 적힌 사실(EXPLICIT)과 해석으로 도출한 사실(INFERRED)을 섞지 않는다.
   "다음 달 말까지 인수인계하고 퇴사"에서 2025-12-31을 얻었다면 그것은
   기록의 기재가 아니라 해석값이며, 그 사실을 표시하지 않으면 뒤따르는
   계산 전체가 근거 없는 확정처럼 보이게 된다.
2. 같은 subject-predicate에 값이 다른 자료가 있으면 어느 하나를 고르지 않고
   모두 보존한다. 충돌을 지우는 것이 가장 흔한 오류다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    ConflictResolution,
    EvidenceGrade,
    FindingType,
    Severity,
    SupportType,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding

ENGINE_NAME = "claim_engine.fact_ledger"


def _comparable(value: Any) -> Any:
    """값을 비교 가능한 형태로 만든다. 못 바꾸면 원형을 쓴다."""
    if isinstance(value, (date, Decimal, int, float, bool)):
        return value
    text = str(value).strip()
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return text


@dataclass
class Fact:
    """제5.1장 사실 하나."""

    fact_id: str
    predicate: str
    subject: str
    value: Any
    value_type: str = "string"
    source_spans: List[str] = field(default_factory=list)
    support_type: SupportType = SupportType.EXPLICIT
    inference_rule: str = ""
    confidence: float = 0.0
    document_id: Optional[str] = None
    page: Optional[int] = None
    block_id: Optional[str] = None
    conflicts_with: List[str] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.subject.strip(), self.predicate.strip())

    @property
    def sourced(self) -> bool:
        return bool(self.source_spans)

    def to_dict(self) -> Dict[str, Any]:
        value = self.value
        if isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        return {
            "fact_id": self.fact_id,
            "predicate": self.predicate,
            "subject": self.subject,
            "value": value,
            "value_type": self.value_type,
            "source_spans": list(self.source_spans),
            "support_type": str(self.support_type),
            "inference_rule": self.inference_rule,
            "confidence": round(self.confidence, 3),
            "document_id": self.document_id,
            "page": self.page,
            "conflicts_with": list(self.conflicts_with),
        }


@dataclass
class ConflictSet:
    """제5.2장. 같은 항목에 값이 다른 근거들의 묶음."""

    conflict_id: str
    subject: str
    predicate: str
    facts: List[Fact] = field(default_factory=list)
    resolution: ConflictResolution = ConflictResolution.UNRESOLVED
    resolution_note: str = ""
    resolved_value: Any = None

    @property
    def values(self) -> List[Any]:
        seen: List[Any] = []
        for fact in self.facts:
            marker = _comparable(fact.value)
            if marker not in seen:
                seen.append(marker)
        return seen

    @property
    def resolved(self) -> bool:
        return self.resolution != ConflictResolution.UNRESOLVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "facts": [f.to_dict() for f in self.facts],
            "distinct_values": [str(v) for v in self.values],
            "resolution": str(self.resolution),
            "resolution_note": self.resolution_note,
            "resolved": self.resolved,
            "note": ("충돌하는 근거를 삭제하지 않고 모두 보존한다. "
                     "우선순위 판단은 담당 변호사의 몫이다."),
        }


class FactLedger:
    """사실 원장. 추가 순서와 무관하게 같은 충돌집합을 만든다."""

    def __init__(self) -> None:
        self._facts: List[Fact] = []
        self._counter = 0

    # --- 등록 ---------------------------------------------------------------
    def add(self, *, predicate: str, subject: str, value: Any,
            value_type: str = "string", source_spans: Optional[Sequence[str]] = None,
            support_type: SupportType = SupportType.EXPLICIT,
            inference_rule: str = "", document_id: Optional[str] = None,
            page: Optional[int] = None, block_id: Optional[str] = None,
            confidence: Optional[float] = None) -> Fact:
        self._counter += 1
        spans = list(source_spans or [])
        if support_type == SupportType.INFERRED and not inference_rule:
            raise ValueError("해석으로 도출한 사실은 도출 근거(inference_rule)를 적어야 한다")
        if confidence is None:
            confidence = confidence_score({
                "deterministic_rule": support_type == SupportType.EXPLICIT,
                "official_source_absent": not spans,
                "source_count": len(spans),
                "heuristic_only": support_type == SupportType.INFERRED,
            })
        fact = Fact(
            fact_id=f"F-{self._counter:03d}",
            predicate=predicate, subject=subject, value=value, value_type=value_type,
            source_spans=spans, support_type=support_type, inference_rule=inference_rule,
            confidence=float(confidence), document_id=document_id, page=page, block_id=block_id,
        )
        self._facts.append(fact)
        return fact

    @property
    def facts(self) -> List[Fact]:
        return list(self._facts)

    def find(self, subject: str, predicate: str) -> List[Fact]:
        key = (subject.strip(), predicate.strip())
        return [f for f in self._facts if f.key == key]

    # --- 충돌 ---------------------------------------------------------------
    def conflicts(self) -> List[ConflictSet]:
        """값이 둘 이상인 subject-predicate마다 충돌집합을 만든다."""
        grouped: Dict[tuple, List[Fact]] = {}
        for fact in self._facts:
            grouped.setdefault(fact.key, []).append(fact)

        out: List[ConflictSet] = []
        for index, (key, facts) in enumerate(sorted(grouped.items(), key=lambda kv: kv[0]), start=1):
            distinct = {_comparable(f.value) for f in facts}
            if len(distinct) < 2:
                continue
            ids = [f.fact_id for f in facts]
            for fact in facts:
                fact.conflicts_with = [i for i in ids if i != fact.fact_id]
            out.append(ConflictSet(
                conflict_id=f"CONF-{index:03d}",
                subject=key[0], predicate=key[1], facts=list(facts),
            ))
        return out

    # --- 검출 ---------------------------------------------------------------
    def findings(self, *, asserted_conclusions: Optional[Dict[tuple, Any]] = None) -> List[Finding]:
        """원장에서 나오는 Finding.

        asserted_conclusions는 문서가 단정한 값이다. 충돌이 풀리지 않은
        항목을 문서가 하나로 단정했다면 제5.2장의 SOURCE_CONFLICT_IGNORED다.
        """
        out: List[Finding] = []
        asserted = asserted_conclusions or {}

        for fact in self._facts:
            if fact.sourced:
                continue
            out.append(Finding.create(
                type=FindingType.FACT_UNSUPPORTED,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.C,
                title=f"기록 근거가 확인되지 않은 사실: {fact.subject} / {fact.predicate}",
                detail=(f"값 '{fact.value}'에 연결된 원문 위치가 없다. 기록에서 확인되지 않은 "
                        f"전제이므로 결론의 근거로 쓸 수 없다."),
                confidence=fact.confidence,
                document_id=fact.document_id,
                page=fact.page,
                block_id=fact.block_id,
                engine=ENGINE_NAME,
                tags=["fact_ledger", "unsupported"],
            ))

        for conflict in self.conflicts():
            key = (conflict.subject, conflict.predicate)
            if key not in asserted or conflict.resolved:
                continue
            values = ", ".join(str(v) for v in conflict.values)
            out.append(Finding.create(
                type=FindingType.SOURCE_CONFLICT_IGNORED,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.B,
                title=f"상충자료가 있는데 단정했다: {conflict.subject} / {conflict.predicate}",
                detail=(f"기록에는 서로 다른 값이 있다({values}). 그럼에도 문서는 "
                        f"'{asserted[key]}'로 단정한다. 충돌 해소 근거를 밝히거나 "
                        f"불확실성을 표시해야 한다."),
                confidence=0.7,
                evidence=[Evidence.create(
                    description=f"충돌집합 {conflict.conflict_id}: {values}",
                    grade=EvidenceGrade.B,
                )],
                engine=ENGINE_NAME,
                tags=["conflict_set", conflict.conflict_id],
            ))
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self._facts],
            "conflict_sets": [c.to_dict() for c in self.conflicts()],
            "explicit_count": sum(1 for f in self._facts if f.support_type == SupportType.EXPLICIT),
            "inferred_count": sum(1 for f in self._facts if f.support_type == SupportType.INFERRED),
            "note": ("해석으로 도출한 사실은 기록의 기재와 구분해 표시한다. "
                     "충돌은 해소하지 않고 보존한다."),
        }
