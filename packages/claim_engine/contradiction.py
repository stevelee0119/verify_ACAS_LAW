"""제11.4장 Timeline 및 Cross-document contradiction.

Rule-based contradiction과 LLM semantic contradiction을 분리해 근거 수준을 다르게 표시한다.
Rule-based는 Evidence Grade A/C, LLM 기반은 D로 둔다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Event, Finding

ENGINE_NAME = "claim_engine.contradiction"

# 선행해야 하는 사건 유형 (앞의 것이 뒤의 것보다 먼저여야 한다)
ORDER_RULES: List[Tuple[str, str, str]] = [
    ("INCORPORATION", "CONTRACT", "법인 설립일 이후에만 그 법인의 계약체결이 가능하다"),
    ("CONTRACT", "TERMINATION", "계약 체결일 이후에만 해지가 가능하다"),
    ("CONTRACT", "PAYMENT", "계약 체결일 이전의 계약상 지급은 통상 성립하지 않는다"),
    ("INCIDENT", "FILING", "사건 발생일 이후에만 고소·제출이 가능하다"),
    ("FILING", "DECISION", "접수일 이후에만 결정·선고가 가능하다"),
]


@dataclass
class TimelineIssue:
    kind: str
    earlier: Event
    later: Event
    rule: str


def analyze_timeline(events: List[Event]) -> List[Finding]:
    """시간적으로 불가능하거나 상충되는 관계를 탐지한다."""
    findings: List[Finding] = []
    dated = [e for e in events if e.date]
    by_kind: Dict[str, List[Event]] = defaultdict(list)
    for event in dated:
        by_kind[event.event_kind].append(event)

    for first_kind, second_kind, rule in ORDER_RULES:
        firsts = by_kind.get(first_kind) or []
        seconds = by_kind.get(second_kind) or []
        if not firsts or not seconds:
            continue
        earliest_first = min(firsts, key=lambda e: e.date)  # type: ignore[arg-type]
        for later in seconds:
            if later.date and earliest_first.date and later.date < earliest_first.date:
                features = {
                    "deterministic_rule": True,
                    "forensic_signal": 1,
                    "rule": rule,
                    "earlier_date": earliest_first.date.isoformat(),
                    "later_date": later.date.isoformat(),
                }
                findings.append(
                    Finding.create(
                        type=FindingType.TIMELINE_CONTRADICTION,
                        status=VerificationStatus.CONTRADICTED,
                        severity=Severity.HIGH,
                        evidence_grade=EvidenceGrade.C,
                        title=f"시간 순서가 성립하지 않는다: {second_kind}({later.date}) < {first_kind}({earliest_first.date})",
                        detail=f"{rule}. 두 서술의 날짜 관계가 역전되어 있다.",
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=later.document_id,
                        block_id=later.block_id,
                        page=later.page,
                        engine=ENGINE_NAME,
                        tags=["TIMELINE"],
                        evidence=[
                            Evidence.create(
                                description=f"{first_kind} 서술",
                                grade=EvidenceGrade.C,
                                document_id=earliest_first.document_id,
                                block_id=earliest_first.block_id,
                                page=earliest_first.page,
                                excerpt=earliest_first.description,
                            ),
                            Evidence.create(
                                description=f"{second_kind} 서술",
                                grade=EvidenceGrade.C,
                                document_id=later.document_id,
                                block_id=later.block_id,
                                page=later.page,
                                excerpt=later.description,
                                supports=False,
                            ),
                        ],
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# 문서간 모순 (제11.4장)
# ---------------------------------------------------------------------------
AMOUNT_RE = re.compile(r"(?:금\s*)?(\d[\d,]*)\s*원")
KEY_FACT_PATTERNS = [
    ("CONTRACT_DATE", re.compile(r"계약(?:을)?\s*체결", re.UNICODE)),
    ("TERMINATION_DATE", re.compile(r"(해지|해제)", re.UNICODE)),
    ("PAYMENT_AMOUNT", re.compile(r"(지급|송금|변제)", re.UNICODE)),
]


def cross_document_contradictions(events_by_document: Dict[str, List[Event]]) -> List[Finding]:
    """동일 사실에 관한 서로 다른 문서의 날짜 진술이 충돌하는지 확인한다."""
    findings: List[Finding] = []
    if len(events_by_document) < 2:
        return findings

    by_kind: Dict[str, List[Tuple[str, Event]]] = defaultdict(list)
    for document_id, events in events_by_document.items():
        for event in events:
            if event.date and event.event_kind != "GENERIC":
                by_kind[event.event_kind].append((document_id, event))

    for kind, items in by_kind.items():
        documents = {document_id for document_id, _ in items}
        if len(documents) < 2:
            continue
        earliest_by_document: Dict[str, Event] = {}
        for document_id, event in items:
            current = earliest_by_document.get(document_id)
            if current is None or (event.date and current.date and event.date < current.date):
                earliest_by_document[document_id] = event
        dates = {document_id: event.date for document_id, event in earliest_by_document.items()}
        distinct = set(dates.values())
        if len(distinct) < 2:
            continue
        items_sorted = sorted(earliest_by_document.items(), key=lambda kv: kv[1].date or date.min)
        first_doc, first_event = items_sorted[0]
        last_doc, last_event = items_sorted[-1]
        features = {
            "deterministic_rule": True,
            "cross_layer_mismatch": False,
            "forensic_signal": len(distinct),
            "kind": kind,
            "dates": {d: (v.isoformat() if v else None) for d, v in dates.items()},
        }
        findings.append(
            Finding.create(
                type=FindingType.CROSS_DOCUMENT_CONTRADICTION,
                status=VerificationStatus.CONTRADICTED,
                severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.C,
                title=f"문서간 {kind} 일자 진술이 다르다",
                detail=(
                    "; ".join(f"{document_id}: {value}" for document_id, value in dates.items())
                    + ". 동일 사건에 관한 서술로 보이나 날짜가 일치하지 않는다. 서로 다른 사실을 가리킬 수 있으므로 확인이 필요하다."
                ),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=last_doc,
                block_id=last_event.block_id,
                page=last_event.page,
                engine=ENGINE_NAME,
                tags=["CROSS_DOCUMENT"],
                evidence=[
                    Evidence.create(
                        description=f"{first_doc} 서술",
                        grade=EvidenceGrade.C,
                        document_id=first_doc,
                        block_id=first_event.block_id,
                        page=first_event.page,
                        excerpt=first_event.description,
                    ),
                    Evidence.create(
                        description=f"{last_doc} 서술",
                        grade=EvidenceGrade.C,
                        document_id=last_doc,
                        block_id=last_event.block_id,
                        page=last_event.page,
                        excerpt=last_event.description,
                        supports=False,
                    ),
                ],
            )
        )
    return findings


def build_timeline(events: List[Event]) -> List[Dict[str, Any]]:
    """UI Timeline 표시용 정렬 결과."""
    dated = sorted([e for e in events if e.date], key=lambda e: e.date)  # type: ignore[arg-type]
    return [e.to_dict() for e in dated]
