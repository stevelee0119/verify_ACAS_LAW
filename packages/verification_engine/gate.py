"""제8장 검증위험 지수와 제9장 배포 게이트.

두 가지를 분명히 해 둔다.

1. `hallucination_risk`는 작성주체 확률이 아니라 **검증위험 지수**다(제8.2장).
   문체나 어휘는 계산에 들어가지 않는다. 들어가는 것은 "공식 DB에 사건번호가
   없다", "직접인용이 원문에 없다" 같이 근거를 댈 수 있는 관찰뿐이다.
2. 가중합은 치명적 오류를 상쇄하지 못한다(제9.1장). 점수가 낮아도 하드게이트에
   걸리면 BLOCK이다. 평균으로 위험을 희석하는 것이 이 종류 도구의 대표적 결함이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from packages.common.enums import (
    FindingType,
    ReleaseGate,
    Severity,
    VerificationStatus,
)

ENGINE_NAME = "verification_engine.gate"

# 제8.2장 가중치표. 표에 없는 FindingType은 지수에 넣지 않는다.
RISK_WEIGHTS: Dict[FindingType, int] = {
    FindingType.CASE_NOT_FOUND: 40,
    FindingType.STATUTE_NONEXISTENT: 40,
    FindingType.CASE_METADATA_MISMATCH: 35,
    FindingType.QUOTE_MISMATCH: 35,
    FindingType.CASE_QUOTE_MISMATCH: 35,
    FindingType.CASE_HOLDING_DISTORTION: 30,
    FindingType.FACT_CONTRADICTION: 30,
    FindingType.CROSS_DOCUMENT_CONTRADICTION: 30,
    FindingType.ARITHMETIC_MISMATCH: 25,
    FindingType.CALCULATION_INVARIANT_VIOLATION: 25,
    FindingType.FACT_UNSUPPORTED: 20,
    FindingType.SOURCE_CONFLICT_IGNORED: 15,
    FindingType.DRAFT_ARTIFACT: 10,
}

RISK_LABELS: Dict[FindingType, str] = {
    FindingType.CASE_NOT_FOUND: "공식 DB에 사건번호 없음",
    FindingType.STATUTE_NONEXISTENT: "공식 DB에 법령·조항 없음",
    FindingType.CASE_METADATA_MISMATCH: "사건번호는 있으나 날짜/법원 불일치",
    FindingType.QUOTE_MISMATCH: "직접인용이 원문에 없음",
    FindingType.CASE_QUOTE_MISMATCH: "직접인용이 원문에 없음",
    FindingType.CASE_HOLDING_DISTORTION: "존재하는 판례의 판시취지 왜곡",
    FindingType.FACT_CONTRADICTION: "첨부자료와 명백히 모순",
    FindingType.CROSS_DOCUMENT_CONTRADICTION: "첨부자료와 명백히 모순",
    FindingType.ARITHMETIC_MISMATCH: "독립 계산 불일치",
    FindingType.CALCULATION_INVARIANT_VIOLATION: "숫자 불변식 위반",
    FindingType.FACT_UNSUPPORTED: "출처 없는 구체적 사실",
    FindingType.SOURCE_CONFLICT_IGNORED: "상충자료 무시 후 단정",
    FindingType.DRAFT_ARTIFACT: "생성 초안 흔적",
}

# 제9.2장 하드게이트. 점수와 무관하게 차단한다.
HARD_BLOCK_TYPES = {
    FindingType.CASE_NOT_FOUND,
    FindingType.STATUTE_NONEXISTENT,
    FindingType.QUOTE_MISMATCH,
    FindingType.CASE_QUOTE_MISMATCH,
    FindingType.TEMPORAL_LAW_MISMATCH,
    FindingType.CASE_HOLDING_DISTORTION,
}
# 심각도가 CRITICAL일 때에만 차단하는 유형
HARD_BLOCK_IF_CRITICAL = {
    FindingType.FACT_CONTRADICTION,
    FindingType.CROSS_DOCUMENT_CONTRADICTION,
    FindingType.ARITHMETIC_MISMATCH,
    FindingType.CALCULATION_INVARIANT_VIOLATION,
    FindingType.LEGAL_REQUIREMENT_OMITTED,
}
# 외부 전송 위험(제9.2장 마지막 항)
LEAK_TYPES = {
    FindingType.OUTBOUND_LEAK_RISK,
    FindingType.PRIVILEGE_EXPOSURE_RISK,
    FindingType.DATA_EXFILTRATION_INSTRUCTION,
}
# 외부 제출을 전제로 할 때에만 차단하는 유형
BLOCK_IF_EXTERNAL_SUBMISSION = {FindingType.UNCERTAINTY_NOT_DISCLOSED}

# 제9.3장 자동수정 범위
AUTO_FIXABLE_TYPES = {
    FindingType.INTERNAL_CITATION_ERROR,
    FindingType.ACADEMIC_CITATION_ERROR,
    FindingType.ARITHMETIC_MISMATCH,
    FindingType.DRAFT_ARTIFACT,
}
LAWYER_APPROVAL_TYPES = {
    FindingType.CASE_RELEVANCE_WEAK,
    FindingType.CASE_HOLDING_DISTORTION,
    FindingType.LEGAL_REQUIREMENT_OMITTED,
    FindingType.OVERCLAIM,
    FindingType.UNSUPPORTED_GENERALIZATION,
    FindingType.REASONING_GAP,
    FindingType.SOURCE_CONFLICT_IGNORED,
    FindingType.TEMPORAL_LAW_MISMATCH,
    FindingType.STATUTE_TEXT_MISMATCH,
}


@dataclass
class RiskContribution:
    finding_type: str
    label: str
    weight: int
    count: int
    finding_ids: List[str] = field(default_factory=list)

    @property
    def subtotal(self) -> int:
        return self.weight * self.count

    def to_dict(self) -> Dict[str, Any]:
        return {"finding_type": self.finding_type, "label": self.label,
                "weight": self.weight, "count": self.count,
                "subtotal": self.subtotal, "finding_ids": list(self.finding_ids)}


@dataclass
class GateDecision:
    gate: ReleaseGate
    risk_index: int
    contributions: List[RiskContribution] = field(default_factory=list)
    hard_block_reasons: List[str] = field(default_factory=list)
    review_reasons: List[str] = field(default_factory=list)
    auto_fixable: List[str] = field(default_factory=list)
    lawyer_approval_required: List[str] = field(default_factory=list)
    citation_groups: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "release_gate": str(self.gate),
            "hallucination_risk": self.risk_index,
            "risk_index_note": ("작성주체 확률이 아니라 검증위험 지수다. 문체는 "
                                "계산에 포함하지 않는다(제8.2장). AI 작성 가능성 추정치와는 "
                                "다른 값이며 서로 더하거나 비교하지 않는다. 같은 인용의 같은 유형은 한 번만 센다."),
            "contributions": [c.to_dict() for c in self.contributions],
            # 같은 인용에서 파생된 finding 묶음(차단 사유·조회 범위·원문 확인 여부)
            "citation_groups": list(self.citation_groups),
            "hard_block_reasons": list(self.hard_block_reasons),
            "review_reasons": list(self.review_reasons),
            "auto_fixable_findings": list(self.auto_fixable),
            "lawyer_approval_required_findings": list(self.lawyer_approval_required),
            "note": ("가중합은 치명적 오류를 상쇄하지 않는다. 하드게이트에 걸리면 "
                     "점수와 무관하게 BLOCK이다(제9.1장)."),
        }


def risk_index(findings: Sequence[Any]) -> (int, List[RiskContribution]):
    """제8.2장 검증위험 지수. 상한은 100이다."""
    buckets: Dict[FindingType, RiskContribution] = {}
    seen = set()
    for finding in findings:
        if getattr(finding, "advisory_only", False):
            continue
        weight = RISK_WEIGHTS.get(finding.type)
        if weight is None:
            continue
        # 같은 인용이 기준일별 검토 등으로 여러 번 판정돼도 같은 유형은 한 번만 센다.
        citation_id = (getattr(finding, "confidence_features", None) or {}).get("citation_id")
        if citation_id:
            if (finding.type, citation_id) in seen:
                continue
            seen.add((finding.type, citation_id))
        bucket = buckets.get(finding.type)
        if bucket is None:
            bucket = RiskContribution(finding_type=str(finding.type),
                                      label=RISK_LABELS.get(finding.type, str(finding.type)),
                                      weight=weight, count=0)
            buckets[finding.type] = bucket
        bucket.count += 1
        bucket.finding_ids.append(getattr(finding, "finding_id", ""))
    contributions = sorted(buckets.values(), key=lambda c: (-c.subtotal, c.finding_type))
    total = min(100, sum(c.subtotal for c in contributions))
    return total, contributions


_SEVERITY_RANK = {Severity.INFO: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}


def citation_groups(findings: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    """같은 인용에서 나온 finding을 하나의 상위 항목으로 묶는다.

    분류별 finding(예: 조회 범위 내 미발견 + 그 판례에 기댄 법률 주장)은 그대로 두되,
    화면·합산에서 서로 다른 경고처럼 보이지 않게 대표 항목과 하위 근거로 정리한다.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for finding in findings:
        features = getattr(finding, "confidence_features", None) or {}
        citation_id = features.get("citation_id")
        if not citation_id:
            continue
        group = groups.setdefault(citation_id, {"citation_id": citation_id, "members": [],
                                                "lookup_scope": None, "searched": [],
                                                "official_text_checked": False})
        group["members"].append({"finding_id": finding.finding_id, "type": str(finding.type),
                                 "severity": str(finding.severity), "title": finding.title})
        group["lookup_scope"] = group["lookup_scope"] or features.get("absence_scope")
        group["searched"] = group["searched"] or features.get("searched") or []
        group["official_text_checked"] |= bool(features.get("official_source_match"))
        if features.get("number_format_valid") is False:
            group["number_format"] = "IMPOSSIBLE"
    for group in groups.values():
        members = [m for m in group["members"]]
        primary = max(members, key=lambda m: (_SEVERITY_RANK.get(Severity(m["severity"]), 0),
                                              m["type"] in {str(t) for t in HARD_BLOCK_TYPES}))
        group["primary"] = primary
        group["derived_count"] = len(members)
        adapters = sorted({s.get("adapter") for s in group["searched"] if s.get("adapter")})
        scope = {"SEARCHED_SCOPE_ONLY": "조회 범위 내 미발견(부존재 확정 아님)",
                 "SELECTED_VERSION_FULL_TEXT": "조회한 시행 버전 전문에서 미발견",
                 "FORMAT_ONLY": "공식 DB 조회 불가 — 번호 형식만으로 판단(성립 불가 형식)",
                 }.get(group["lookup_scope"] or "", "공식 DB 조회 불가 — 미확인(부존재 판단 아님)")
        group["reason"] = (f"{primary['type']}: {primary['title']} — 조회 범위: {scope}"
                           + (f" ({', '.join(adapters)})" if adapters else "")
                           + f"; 공식 원문 확인: {'예' if group['official_text_checked'] else '아니오'}"
                           + (f"; 같은 인용에서 파생된 finding {len(members)}건("
                              + ", ".join(sorted({m['type'] for m in members})) + ")" if len(members) > 1 else ""))
    return groups


def evaluate_gate(findings: Sequence[Any], *,
                  unverified_items: Sequence[Any] = (),
                  nothing_analyzed: bool = False,
                  intended_external_submission: bool = False) -> GateDecision:
    """제9.2장 배포 게이트.

    nothing_analyzed는 본문을 하나도 읽지 못한 경우다. 그때 PASS를 주면
    "검증해서 문제 없음"과 "아무것도 못 읽음"이 같은 결론이 된다.
    """
    active = [f for f in findings if not getattr(f, "advisory_only", False)]
    total, contributions = risk_index(active)

    hard: List[str] = []
    groups = citation_groups(active)
    explained = set()
    for finding in active:
        citation_id = (finding.confidence_features or {}).get("citation_id")
        if finding.type in HARD_BLOCK_TYPES and citation_id in groups:
            # 같은 인용에서 파생된 finding은 차단 사유 한 줄로 묶고 하위 근거를 함께 적는다.
            if citation_id not in explained:
                explained.add(citation_id)
                hard.append(groups[citation_id]["reason"])
        elif finding.type in HARD_BLOCK_TYPES:
            hard.append(f"{finding.type}: {finding.title}")
        elif finding.type in HARD_BLOCK_IF_CRITICAL and finding.severity == Severity.CRITICAL:
            hard.append(f"{finding.type}: {finding.title}")
        elif finding.type in LEAK_TYPES:
            hard.append(f"{finding.type}: {finding.title}")
        elif intended_external_submission and finding.type in BLOCK_IF_EXTERNAL_SUBMISSION:
            hard.append(f"{finding.type}: {finding.title} (외부 제출 전제)")

    review: List[str] = []
    if nothing_analyzed:
        review.append("본문을 읽지 못해 내용 검증을 수행하지 못했다. 검증 통과로 볼 수 없다.")
    missing = [i for i in unverified_items if not (isinstance(i, dict) and i.get("scope") == "PARTIAL")]
    partial = len(unverified_items) - len(missing)
    if missing:
        review.append(f"공식 원문으로 확인하지 못한 항목이 {len(missing)}건 있다.")
    if partial:
        review.append(f"공식 원문으로 존재는 확인했으나 취지·적용 여부는 사람이 검토해야 하는 인용이 {partial}건 있다.")
    if any(f.severity == Severity.CRITICAL for f in active):
        review.append("치명적 심각도의 Finding이 있다.")
    if any(f.status == VerificationStatus.UNVERIFIED for f in active):
        review.append("판정을 내리지 못한 Finding이 있다.")

    if hard or total >= 70:
        gate = ReleaseGate.BLOCK
    elif total >= 40 or review:
        gate = ReleaseGate.HUMAN_REVIEW_REQUIRED
    elif total >= 1 or active:
        gate = ReleaseGate.PASS_WITH_WARNINGS
    else:
        gate = ReleaseGate.PASS

    if total >= 70 and not hard:
        hard.append(f"검증위험 지수 {total}점 (70점 이상 자동 차단)")
    elif total >= 40 and gate == ReleaseGate.HUMAN_REVIEW_REQUIRED:
        review.insert(0, f"검증위험 지수 {total}점 (40~69점 사람 검토)")

    return GateDecision(
        gate=gate,
        risk_index=total,
        contributions=contributions,
        citation_groups=[{k: v for k, v in g.items() if k != "reason"} for g in groups.values()],
        hard_block_reasons=hard,
        review_reasons=review,
        auto_fixable=[f.finding_id for f in active if f.type in AUTO_FIXABLE_TYPES],
        lawyer_approval_required=[f.finding_id for f in active
                                  if f.type in LAWYER_APPROVAL_TYPES
                                  or f.severity == Severity.CRITICAL],
    )


# --- 제9.1장 주장별 점수 ---------------------------------------------------
# 축 하나가 이 값보다 낮으면 가중평균이 아무리 높아도 "충분"으로 보지 않는다.
# 제4.2장: 사건번호가 실재해도 판시취지에 맞지 않으면 통과시키지 않는다.
AXIS_FLOOR = 0.5

CLAIM_WEIGHTS = {
    "source_existence": 0.30,
    "text_accuracy": 0.25,
    "temporal_applicability": 0.20,
    "issue_relevance": 0.15,
    "reasoning_completeness": 0.10,
}


def claim_confidence(axes: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """제9.1장 주장별 신뢰도.

    축 하나라도 0이면 가중평균과 무관하게 hard gate에 걸린다. 출처가 없는
    주장이 다른 축 점수로 0.7을 받는 일이 없어야 한다.
    """
    missing = [name for name in CLAIM_WEIGHTS if axes.get(name) is None]
    scored = {name: float(axes.get(name) or 0.0) for name in CLAIM_WEIGHTS}
    weighted = sum(CLAIM_WEIGHTS[name] * value for name, value in scored.items())
    zeroed = [name for name, value in scored.items() if value <= 0.0 and name not in missing]
    weak = [name for name, value in scored.items()
            if name not in missing and 0.0 < value < AXIS_FLOOR]

    if missing:
        verdict = "UNVERIFIABLE"
    elif zeroed:
        verdict = "HARD_FAIL"
    elif weak:
        # 가중치가 작은 축(관련성 0.15)이 낮아도 총점은 거의 떨어지지 않는다.
        # 총점만 보면 관련 없는 판례를 근거로 든 주장이 통과한다.
        verdict = "REVIEW" if weighted >= 0.60 else "INSUFFICIENT"
    elif weighted >= 0.85:
        verdict = "SUFFICIENT"
    elif weighted >= 0.60:
        verdict = "REVIEW"
    else:
        verdict = "INSUFFICIENT"

    return {
        "axes": {name: (None if name in missing else round(scored[name], 3))
                 for name in CLAIM_WEIGHTS},
        "weights": dict(CLAIM_WEIGHTS),
        "confidence": round(weighted, 3) if not missing else None,
        "verdict": verdict,
        "hard_gate_axes": zeroed,
        "weak_axes": weak,
        "unmeasured_axes": missing,
        "note": (f"축 하나가 0이면 가중평균이 높아도 통과시키지 않는다. "
                 f"{AXIS_FLOOR} 미만인 축이 있으면 '충분'으로 판정하지 않는다. "
                 f"측정하지 못한 축이 있으면 신뢰도를 산출하지 않는다."),
    }
