"""제4.1~4.2장 판정값을 이 시스템의 다단계 판정에서 끌어낸다.

이 시스템은 인용 하나에 존재·버전·조항·시점·문언을 따로 기록한다. 명세의
여섯 값(VERIFIED_EXACT … NOT_FOUND)보다 세밀하므로 그 구조를 바꾸지 않고,
명세 어휘로 읽을 수 있는 단일 값을 파생시켜 함께 싣는다.

한 가지 원칙만 지킨다. 조회에 실패한 것과 원문에서 발견되지 않은 것을
같은 값으로 만들지 않는다. 앞은 UNVERIFIABLE, 뒤는 NOT_FOUND다. 둘을 섞으면
공식 API 장애가 "그런 판례는 없다"로 둔갑한다(제11.1장, 제16장 인수기준).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from packages.common.enums import SourceVerdict

ENGINE_NAME = "legal_engine.spec_mapping"

# 조회 자체가 되지 않았음을 뜻하는 표현. 어댑터가 "없음"을 확인한 경우와 다르다.
LOOKUP_FAILURE_HINTS = (
    "확보하지 못", "조회하지 못", "확인 불가", "지원하지 않", "장애", "응답 없",
    "환경변수", "인증", "시간 초과", "요청 실패",
)
NOT_FOUND_HINTS = ("검색 결과 없", "존재하지 않", "발견되지 않", "찾지 못")


def _any(hints: Sequence[str], notes: Sequence[str]) -> bool:
    joined = " ".join(notes or ())
    return any(hint in joined for hint in hints)


def spec_source_verdict(levels: Dict[str, str], notes: Sequence[str] = (),
                        *, has_official_record: bool = False) -> SourceVerdict:
    """다단계 판정을 명세 제4.1장의 단일 값으로 환산한다."""
    existence = levels.get("existence") or levels.get("level1") or "UNVERIFIED"
    content = levels.get("content") or levels.get("level3") or "UNVERIFIED"
    temporal = levels.get("temporal", "")
    metadata = levels.get("metadata") or levels.get("level2") or ""

    if existence != "VERIFIED":
        if _any(NOT_FOUND_HINTS, notes):
            return SourceVerdict.NOT_FOUND
        if _any(LOOKUP_FAILURE_HINTS, notes) or not has_official_record:
            return SourceVerdict.UNVERIFIABLE
        return SourceVerdict.NOT_FOUND

    if content == "CONTRADICTED" or metadata == "CONTRADICTED":
        return SourceVerdict.MISMATCH
    if levels.get("version") == "CONTRADICTED":
        return SourceVerdict.WRONG_VERSION
    if content == "VERIFIED" and temporal == "VERIFIED":
        return SourceVerdict.VERIFIED_EXACT
    if content == "PARTIALLY_VERIFIED" and temporal == "VERIFIED":
        return SourceVerdict.VERIFIED_PARAPHRASE
    # 존재는 확인했으나 문언 또는 시점 확인이 남았다. 통과로 올리지 않는다.
    return SourceVerdict.PARTIAL


# --- 제4.2장 관련성 축 ---------------------------------------------------------
RELEVANCE_AXES = ("issue_similarity", "fact_similarity", "legal_basis_similarity",
                  "procedural_posture_similarity", "holding_support_strength")

RELEVANCE_THRESHOLD = 0.5


def relevance_review(axes: Optional[Dict[str, Optional[float]]] = None) -> Dict[str, Any]:
    """제4.2장 관련성 평가.

    축을 측정하지 못했으면 0점이 아니라 미측정이다. 이 구분이 없으면
    "관련성 점수가 낮으니 경고" 와 "관련성을 재 본 적이 없다"가 같은 표시를
    받는다. 근거 없는 숫자를 만들지 않기 위해 기본값은 전부 None이다.

    값은 임베딩 단계나 검토자가 채운다. 이 함수는 채워진 값만 해석한다.
    """
    supplied = dict(axes or {})
    scored: Dict[str, Optional[float]] = {}
    for name in RELEVANCE_AXES:
        value = supplied.get(name)
        scored[name] = None if value is None else round(max(0.0, min(1.0, float(value))), 3)

    measured = [name for name, value in scored.items() if value is not None]
    weak = [name for name in measured if scored[name] < RELEVANCE_THRESHOLD]

    if not measured:
        status = "NOT_MEASURED"
    elif weak:
        status = "WEAK"
    elif len(measured) < len(RELEVANCE_AXES):
        status = "PARTIALLY_MEASURED"
    else:
        status = "SUPPORTED"

    return {
        "axes": scored,
        "measured_axes": measured,
        "weak_axes": weak,
        "threshold": RELEVANCE_THRESHOLD,
        "status": status,
        "note": ("사건번호가 실재해도 판시취지에 맞지 않으면 통과시키지 않는다(제4.2장). "
                 "측정하지 않은 축은 0점이 아니라 미측정이며, 관련성 검증을 마쳤다는 "
                 "표시로 쓸 수 없다."),
    }


def relevance_finding(review: Dict[str, Any], *, case_number: str = "",
                      citation_id: str = "", document_id: Optional[str] = None,
                      page: Optional[int] = None):
    """제1.2장 CASE_RELEVANCE_WEAK.

    측정하지 않은 관련성에는 Finding을 내지 않는다. 재지 않은 것을 약하다고
    말하는 것은 근거 없는 판정이다.
    """
    from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
    from packages.common.schemas import Finding

    if (review or {}).get("status") != "WEAK":
        return None
    axes = review["axes"]
    weak = ", ".join(f"{name} {axes[name]}" for name in review["weak_axes"])
    return Finding.create(
        type=FindingType.CASE_RELEVANCE_WEAK,
        status=VerificationStatus.PARTIALLY_VERIFIED,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.C,
        title=f"판례는 존재하나 쟁점 관련성이 약하다{f': {case_number}' if case_number else ''}",
        detail=(f"관련성 축 가운데 기준({review['threshold']}) 미만인 항목: {weak}. "
                f"존재 확인과 관련성은 별개이며, 하나의 '검증 완료'로 표시하지 않는다."),
        confidence=0.6,
        document_id=document_id, page=page, engine=ENGINE_NAME,
        tags=["relevance", citation_id],
    )
