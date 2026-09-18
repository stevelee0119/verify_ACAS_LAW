"""Compare like assertions, retaining uncertainty and source locations."""
from __future__ import annotations

from collections import defaultdict
from copy import copy
from dataclasses import fields
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Claim, Evidence, Event, Finding
from .structure import structure_claim_text

ENGINE_NAME = "claim_engine.contradiction"
EVENT_LABELS = {"INCORPORATION": "설립", "CONTRACT": "계약", "TERMINATION": "종료",
                "PAYMENT": "지급", "INCIDENT": "사건 발생", "FILING": "제출", "DECISION": "결정"}
ORDER_RULES = [
    ("INCORPORATION", "CONTRACT", "설립일과 계약 당시 당사자의 지위를 확인하세요."),
    ("CONTRACT", "TERMINATION", "종료가 같은 계약에 관한 것인지 확인하세요."),
    ("CONTRACT", "PAYMENT", "선지급 또는 앞선 구두 합의가 있는지 확인하세요."),
    ("INCIDENT", "FILING", "제출 서류가 어느 사건에 관한 것인지 확인하세요."),
    ("FILING", "DECISION", "제출과 결정이 같은 절차에 관한 것인지 확인하세요."),
]


def _structured(event: Event) -> Event:
    """Apply conservative surface flags even to legacy callers constructing Events."""
    result = copy(event)
    lexical = structure_claim_text(event.description)
    for name in ("negated", "hearsay", "quoted", "conditional", "alternative"):
        setattr(result, name, getattr(result, name) or lexical[name])
    for name in ("transaction_id", "event_identity", "object_id", "speaker_id", "target_id",
                 "amount", "currency", "amount_scope", "action"):
        if getattr(result, name) is None:
            setattr(result, name, lexical[name])
    if lexical["stance"] not in {"ASSERTED", "UNSPECIFIED"}:
        result.stance = lexical["stance"]
    elif result.stance == "UNSPECIFIED":
        result.stance = "ASSERTED"
    return result


def _assertion(event: Event) -> bool:
    return (event.stance == "ASSERTED" and not any((event.negated, event.hearsay,
            event.quoted, event.conditional, event.alternative)))


def _identity(event: Event) -> tuple:
    """An exhibit label never proves transaction identity."""
    return (event.project_id, event.transaction_id) if event.transaction_id else ()


def _compatible(first: Event, second: Event) -> bool:
    if not _identity(first) or _identity(first) != _identity(second):
        return False
    for name in ("speaker_id", "target_id", "object_id"):
        left, right = getattr(first, name), getattr(second, name)
        if left and right and left != right:
            return False
    return True


def _evidence(event: Event) -> Evidence:
    return Evidence.create("문서의 주장 내용 (독립적인 사실 입증은 아님)", EvidenceGrade.C,
                           document_id=event.document_id, block_id=event.block_id,
                           page=event.page, span=event.span, excerpt=event.description)


def _location(event: Event) -> dict[str, Any]:
    return {name: getattr(event, name) for name in (
        "event_id", "document_id", "block_id", "page", "span", "project_id",
        "source_run_id", "source_document_sha256", "event_identity", "transaction_id",
    )}


def analyze_timeline(events: list[Event]) -> list[Finding]:
    """Return contextual ordering candidates, never an automatic legal impossibility."""
    by_kind: dict[str, list[Event]] = defaultdict(list)
    for source in events:
        event = _structured(source)
        if event.date and _assertion(event) and event.project_id and event.transaction_id:
            by_kind[event.event_kind].append(event)
    findings = []
    for first_kind, second_kind, rule in ORDER_RULES:
        for first in by_kind[first_kind]:
            for second in by_kind[second_kind]:
                if not _compatible(first, second) or second.date >= first.date:
                    continue
                findings.append(Finding.create(
                    type=FindingType.TIMELINE_CONTRADICTION, status=VerificationStatus.UNVERIFIED,
                    severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.C,
                    title=f"날짜 순서 검토: {EVENT_LABELS[second_kind]}이(가) {EVENT_LABELS[first_kind]}보다 앞섬", detail=rule,
                    document_id=second.document_id, block_id=second.block_id, page=second.page,
                    engine=ENGINE_NAME, advisory_only=True, tags=["TIMELINE", "CONTEXT_REQUIRED"],
                    confidence_features={"identity": list(_identity(first)), "rule": rule,
                                         "sources": [_location(first), _location(second)],
                                         "extraction_confidence_is_probability": False},
                    evidence=[_evidence(first), _evidence(second)],
                ))
    return findings


def _comparable_amount(event: Event) -> Decimal | None:
    if not event.amount or not event.currency:
        return None
    try:
        value = Decimal(event.amount)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def cross_document_contradictions(events_by_document: dict[str, list[Event]]) -> list[Finding]:
    """Compare individual events; transaction-only contract matches stay candidates.

    Payments without an event_identity are never compared: one transaction can
    contain many installments. Results describe conflicting assertions, not proof.
    """
    groups: dict[tuple, list[Event]] = defaultdict(list)
    for document_id, events in events_by_document.items():
        for source in events:
            event = _structured(source)
            if source.document_id and source.document_id != document_id:
                raise ValueError("Event document_id conflicts with the document group")
            event.document_id = document_id
            if not _assertion(event) or not _identity(event) or event.event_kind == "GENERIC":
                continue
            if not event.event_identity and event.event_kind != "CONTRACT":
                continue
            groups[(_identity(event), event.event_kind, event.event_identity)].append(event)
    findings = []
    for (_, kind, event_identity), events in groups.items():
        for first, second in combinations(events, 2):
            if first.document_id == second.document_id or not _compatible(first, second):
                continue
            differences = {}
            if first.date and second.date and first.date != second.date:
                differences["date"] = [first.date.isoformat(), second.date.isoformat()]
            left, right = _comparable_amount(first), _comparable_amount(second)
            if (event_identity and first.currency == second.currency
                    and first.amount_scope == second.amount_scope and left is not None and right is not None
                    and left != right):
                differences["amount"] = [str(left), str(right)]
            if not differences:
                continue
            identified = bool(event_identity and first.project_id and first.speaker_id and first.target_id
                              and first.speaker_id == second.speaker_id and first.target_id == second.target_id)
            findings.append(Finding.create(
                type=FindingType.CROSS_DOCUMENT_CONTRADICTION, status=VerificationStatus.UNVERIFIED,
                severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.C,
                title=f"{EVENT_LABELS.get(kind, kind)}에 관한 문서의 기재가 다릅니다", detail=(
                    "식별자가 일치하는 같은 행위에 서로 다른 값이 기재되어 있습니다. 각 원문의 주장을 확인하세요."
                    if identified else "불일치 후보입니다. 같은 사건·당사자·개별 행위인지 먼저 확인하세요."),
                engine=ENGINE_NAME, document_id=second.document_id, block_id=second.block_id, page=second.page,
                advisory_only=True, tags=["CROSS_DOCUMENT", "ASSERTION_CONFLICT" if identified else "IDENTITY_UNCERTAIN"],
                confidence_features={"comparison_scope": "EXPLICIT_EVENT" if identified else "CANDIDATE",
                                     "differences": differences, "sources": [_location(first), _location(second)],
                                     "evidence_relationship": "UNASSESSED"},
                evidence=[_evidence(first), _evidence(second)],
            ))
    return findings


def claim_contradictions(claims: list[Claim], *, project_id: str) -> list[Finding]:
    """Adapt structured claims to comparison, within one explicit project."""
    if not project_id:
        raise ValueError("project_id is required")
    by_document: dict[str, list[Event]] = defaultdict(list)
    event_fields = {field.name for field in fields(Event)} - {"event_id", "date", "description", "event_kind"}
    for claim in claims:
        if claim.project_id != project_id or not claim.document_id or not claim.action:
            continue
        try:
            claimed_date = date.fromisoformat(claim.asserted_date) if claim.asserted_date else None
        except ValueError:
            continue
        kwargs = {name: getattr(claim, name) for name in event_fields if hasattr(claim, name)}
        by_document[claim.document_id].append(Event(
            event_id=claim.claim_id, date=claimed_date, description=claim.text,
            event_kind=claim.action, **kwargs))
    return cross_document_contradictions(by_document)


def build_timeline(events: list[Event]) -> list[dict[str, Any]]:
    return [event.to_dict() for event in sorted((e for e in events if e.date), key=lambda e: e.date)]
