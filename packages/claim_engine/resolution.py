"""제5.3장 회의록·의결 검증.

명목상 표결 결과와 유효표를 각각 계산한다. 의결권 없는 참석자(옵저버 등)의
표가 명목 집계에 섞여 있으면 "가결"이라는 문서의 서술과 유효표 계산이
갈리며, 그 차이가 이 모듈이 찾아내려는 것이다.

정족수 기준은 이 모듈이 임의로 정하지 않는다. 법령·정관·계약 중 무엇을
적용할지는 호출자가 근거와 함께 지정하고, 계산 결과에는 그 근거가 그대로
실린다. 체크리스트 매칭만으로 법률 결론을 확정하지 않는다(제7.2장).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence

from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding

ENGINE_NAME = "claim_engine.resolution"

FOR, AGAINST, ABSTAIN = "FOR", "AGAINST", "ABSTAIN"


@dataclass
class Attendee:
    """참석자 한 사람. 지위와 의결권을 별도 필드로 둔다(제5.3장)."""

    name: str
    position: str = ""
    """예: 사내이사, 사외이사, 옵저버, 감사, 대리인."""
    has_voting_right: Optional[bool] = None
    """None이면 기록에서 확인되지 않았다는 뜻이다. True로 추정하지 않는다."""
    attended: bool = True
    special_interest: bool = False
    """특별이해관계 여부. 확인되면 유효표에서 제외한다."""
    source_span: Optional[str] = None
    note: str = ""

    @property
    def counts(self) -> bool:
        return bool(self.attended and self.has_voting_right and not self.special_interest)

    @property
    def exclusion_reason(self) -> str:
        if not self.attended:
            return "불출석"
        if self.has_voting_right is None:
            return "의결권 확인 불가"
        if not self.has_voting_right:
            return f"의결권 없음({self.position or '지위 미상'})"
        if self.special_interest:
            return "특별이해관계"
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "position": self.position,
                "has_voting_right": self.has_voting_right, "attended": self.attended,
                "special_interest": self.special_interest, "counts": self.counts,
                "exclusion_reason": self.exclusion_reason,
                "source_span": self.source_span, "note": self.note}


@dataclass
class QuorumRule:
    """정족수 기준. 어디에서 온 기준인지를 반드시 함께 둔다."""

    name: str
    basis_kind: str
    """LAW, ARTICLES(정관), CONTRACT 중 하나."""
    basis_citation: str
    """예: "상법 제391조 제1항". 검증보고서에 그대로 표시된다."""
    attendance_fraction: Optional[Fraction] = None
    """의사정족수. 전체 구성원 대비 출석 비율 하한(초과 요건)."""
    approval_fraction: Fraction = Fraction(1, 2)
    """의결정족수. 유효 출석표 대비 찬성 비율 하한(초과 요건)."""
    strict: bool = True
    """True이면 '초과', False이면 '이상'."""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "basis_kind": self.basis_kind,
                "basis_citation": self.basis_citation,
                "attendance_fraction": str(self.attendance_fraction) if self.attendance_fraction else None,
                "approval_fraction": str(self.approval_fraction),
                "comparison": "초과" if self.strict else "이상"}


# 기본으로 제공하는 기준. 자동 적용하지 않고, 호출자가 고른 경우에만 쓴다.
BOARD_RESOLUTION_COMMERCIAL_ACT = QuorumRule(
    name="이사회 결의(상법 기본)",
    basis_kind="LAW",
    basis_citation="상법 제391조 제1항",
    attendance_fraction=Fraction(1, 2),
    approval_fraction=Fraction(1, 2),
    strict=True,
)
"""정관에 다른 정함이 있으면 그 정함이 우선한다(같은 항 단서). 정관을 확인하지
못한 상태에서 이 기준만으로 결의의 적법 여부를 확정하면 안 된다."""


@dataclass
class Tally:
    for_: int = 0
    against: int = 0
    abstain: int = 0

    @property
    def cast(self) -> int:
        return self.for_ + self.against + self.abstain

    def to_dict(self) -> Dict[str, Any]:
        return {"찬성": self.for_, "반대": self.against, "기권": self.abstain, "투표수": self.cast}


@dataclass
class ResolutionResult:
    agenda: str
    nominal: Tally
    effective: Tally
    excluded: List[Dict[str, str]] = field(default_factory=list)
    total_members: Optional[int] = None
    rule: Optional[QuorumRule] = None
    attendance_met: Optional[bool] = None
    approval_met: Optional[bool] = None
    undetermined_reason: str = ""

    @property
    def differs(self) -> bool:
        return self.nominal.to_dict() != self.effective.to_dict()

    @property
    def passed(self) -> Optional[bool]:
        """가결 여부. 판단할 수 없으면 None이며 True로 추정하지 않는다."""
        if self.approval_met is None:
            return None
        if self.attendance_met is None and self.rule and self.rule.attendance_fraction:
            return None
        return bool(self.approval_met and (self.attendance_met is not False))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agenda": self.agenda,
            "nominal_tally": self.nominal.to_dict(),
            "effective_tally": self.effective.to_dict(),
            "excluded": list(self.excluded),
            "total_members": self.total_members,
            "rule": self.rule.to_dict() if self.rule else None,
            "attendance_met": self.attendance_met,
            "approval_met": self.approval_met,
            "passed": self.passed,
            "undetermined_reason": self.undetermined_reason,
            "note": ("명목표와 유효표를 각각 제시한다. 정족수 기준은 지정된 근거에 따른 "
                     "계산이며, 정관·계약의 다른 정함이 있는지는 사람이 확인해야 한다."),
        }


def _meets(numerator: int, denominator: int, fraction: Fraction, strict: bool) -> bool:
    if denominator <= 0:
        return False
    ratio = Fraction(numerator, denominator)
    return ratio > fraction if strict else ratio >= fraction


def evaluate_resolution(*, agenda: str, votes: Dict[str, Sequence[Attendee]],
                        total_members: Optional[int] = None,
                        rule: Optional[QuorumRule] = None) -> ResolutionResult:
    """명목표와 유효표를 각각 센다.

    votes는 {"FOR": [...], "AGAINST": [...], "ABSTAIN": [...]} 형태다.
    """
    nominal = Tally()
    effective = Tally()
    excluded: List[Dict[str, str]] = []
    undetermined = ""

    for bucket, attr in ((FOR, "for_"), (AGAINST, "against"), (ABSTAIN, "abstain")):
        for attendee in votes.get(bucket, ()):  # 기록에 적힌 그대로가 명목표다
            setattr(nominal, attr, getattr(nominal, attr) + 1)
            if attendee.counts:
                setattr(effective, attr, getattr(effective, attr) + 1)
            else:
                excluded.append({"name": attendee.name, "vote": bucket,
                                 "reason": attendee.exclusion_reason,
                                 "source_span": attendee.source_span or ""})
                if attendee.has_voting_right is None and attendee.attended:
                    undetermined = ("의결권 유무가 기록에서 확인되지 않은 참석자가 있다. "
                                    "유효표는 확인된 의결권자만으로 계산했다.")

    attendance_met: Optional[bool] = None
    approval_met: Optional[bool] = None
    if rule is not None:
        denominator = effective.cast
        if denominator > 0:
            approval_met = _meets(effective.for_, denominator, rule.approval_fraction, rule.strict)
        if rule.attendance_fraction is not None and total_members:
            attendance_met = _meets(denominator, total_members, rule.attendance_fraction, rule.strict)
        elif rule.attendance_fraction is not None:
            undetermined = (undetermined + " 구성원 총수가 확인되지 않아 의사정족수를 계산하지 못했다.").strip()

    return ResolutionResult(
        agenda=agenda, nominal=nominal, effective=effective, excluded=excluded,
        total_members=total_members, rule=rule,
        attendance_met=attendance_met, approval_met=approval_met,
        undetermined_reason=undetermined,
    )


def resolution_findings(result: ResolutionResult, *, asserted_passed: Optional[bool] = None,
                        document_id: Optional[str] = None,
                        page: Optional[int] = None) -> List[Finding]:
    """문서의 서술과 유효표 계산을 대조한다.

    asserted_passed는 문서가 "적법하게 가결되었다"고 적었는지 여부다.
    """
    out: List[Finding] = []

    if result.differs:
        reasons = "; ".join(f"{e['name']}({e['vote']}) - {e['reason']}" for e in result.excluded)
        out.append(Finding.create(
            type=FindingType.FACT_CONTRADICTION,
            status=VerificationStatus.CONTRADICTED,
            severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.A,
            title=f"명목표와 유효표가 다르다: {result.agenda}",
            detail=(f"명목 {result.nominal.to_dict()} / 유효 {result.effective.to_dict()}. "
                    f"제외 사유: {reasons}"),
            confidence=0.9,
            document_id=document_id, page=page, engine=ENGINE_NAME,
            evidence=[Evidence.create(description=f"유효표 계산: {result.effective.to_dict()}",
                                      grade=EvidenceGrade.A)],
            tags=["resolution", "vote_count"],
        ))

    if asserted_passed is True:
        if result.passed is False:
            out.append(Finding.create(
                type=FindingType.FACT_CONTRADICTION,
                status=VerificationStatus.CONTRADICTED,
                severity=Severity.CRITICAL,
                evidence_grade=EvidenceGrade.A,
                title=f"가결로 기재되었으나 유효표로는 정족수에 미달한다: {result.agenda}",
                detail=(f"유효표 {result.effective.to_dict()}, 적용 기준 "
                        f"{result.rule.basis_citation if result.rule else '미지정'}."),
                confidence=0.9,
                document_id=document_id, page=page, engine=ENGINE_NAME,
                tags=["resolution", "quorum"],
            ))
        elif result.passed is None:
            out.append(Finding.create(
                type=FindingType.LEGAL_REQUIREMENT_OMITTED,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.C,
                title=f"가결로 기재되었으나 정족수 충족을 확인할 수 없다: {result.agenda}",
                detail=(result.undetermined_reason
                        or "정족수 기준 또는 구성원 총수가 지정되지 않아 계산하지 못했다. "
                           "정관·계약의 정함을 확인해야 한다."),
                confidence=0.6,
                document_id=document_id, page=page, engine=ENGINE_NAME,
                tags=["resolution", "quorum", "unverified"],
            ))
    return out
