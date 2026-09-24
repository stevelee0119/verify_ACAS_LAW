"""인용 검증 결과를 서로 독립된 확인 항목으로 나눈다.

인용 하나의 상태(VERIFIED·PARTIALLY_VERIFIED·UNVERIFIED …)는 가장 약한 단계를 따른다.
그 값 하나만 보여 주면 "법령과 조문은 공식 원문으로 확인했고 적용 기준일만 없다"가
"확인 못 함"과 같아 보인다. 여기서는 단계마다 무엇을 확인했고 무엇이 남았는지를
따로 적는다. 판정 로직은 바꾸지 않고, verifier가 남긴 levels를 옮겨 적기만 한다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 화면·보고서에 쓰는 항목 이름. 순서가 곧 표시 순서다.
STATUTE_COMPONENTS = [
    ("law_existence", "법령 존재", "existence"),
    ("article_existence", "조문 존재", "article"),
    ("version", "해당 시행 버전", "version"),
    ("text_match", "조문 본문 대조", "content"),
    ("temporal_applicability", "시간적 적용(기준일)", "temporal"),
    ("case_applicability", "사건 적용 가능성", "applicability"),
]
ADMIN_RULE_COMPONENTS = [
    ("rule_existence", "행정규칙 존재", "existence"),
    ("rule_identity", "발령기관·종류·번호·시행일", "metadata"),
    ("article_existence", "조항 존재", "article"),
    ("text_match", "조항 본문 대조", "content"),
    ("delegation_basis", "위임 근거", "delegation"),
    ("legal_effect", "법적 구속력·대외적 효력", "legal_effect"),
    ("case_applicability", "사건 적용 가능성", "applicability"),
]
CASE_COMPONENTS = [
    ("number_format", "사건번호 형식", "number_format"),
    ("case_existence", "판례 존재(조회 범위 내)", "level1"),
    ("metadata", "법원·선고일·재판유형", "level2"),
    ("quote_match", "직접 인용문 대조", "level3"),
    ("holding", "판시 취지", "level4"),
    ("context", "문맥 왜곡", "level5"),
    ("case_applicability", "사건 적용 가능성", "applicability"),
]
DECISION_COMPONENTS = [
    ("existence", "해석례·재결례 존재", "existence"),
    ("metadata", "기관·일자", "metadata"),
    ("full_text", "공식 전문 확보", "full_text"),
    ("quote_match", "인용문 대조", "quote"),
    ("case_applicability", "사건 적용 가능성", "applicability"),
]

# 단계 값 → (정규화한 상태, 사람이 읽는 설명)
_MEANING = {
    "VERIFIED": ("CONFIRMED", "공식 원문으로 확인"),
    "AVAILABLE": ("TEXT_AVAILABLE", "공식 본문 확보(인용문 없음)"),
    "NOT_ASSERTED": ("NOT_APPLICABLE", "문서가 조문 내용을 주장하지 않음(근거 표시만)"),
    "PARTIALLY_VERIFIED": ("PARTIAL", "일부 일치"),
    "TRUNCATED": ("PARTIAL", "원문 일부만 인용"),
    "CONTRADICTED": ("MISMATCH", "공식 원문과 불일치"),
    "NOT_FOUND": ("NOT_FOUND_IN_SEARCHED_SCOPE", "조회 범위 내 미발견(부존재 확정 아님)"),
    "NOT_FOUND_IN_SELECTED_VERSION": ("NOT_FOUND_IN_SELECTED_VERSION",
                                      "조회한 시행 버전 전체 조문에서 미발견"),
    "DELETED": ("DELETED", "조회한 버전에서 삭제된 조문"),
    "IMPOSSIBLE": ("INVALID_FORMAT", "성립할 수 없는 번호 형식"),
    "VALID": ("CONFIRMED", "형식상 성립 가능"),
    "UNVERIFIED": ("UNVERIFIED", "확인하지 못함"),
    "PENDING_LLM": ("NOT_RUN", "의미 검토 전"),
    "REVIEW_NEEDED": ("REVIEW_NEEDED", "사람 검토 필요"),
    "CLAIM_NOT_VERIFIED": ("REVIEW_NEEDED", "문서의 효력 주장은 자동 확인하지 않음"),
    "MENTIONED_IN_OFFICIAL_TEXT": ("PARTIAL", "공식 본문에 근거 법령 언급 있음"),
    "NOT_STATED": ("NOT_APPLICABLE", "문서가 제시하지 않음"),
    "NOT_CITED": ("NOT_APPLICABLE", "문서가 인용하지 않음"),
}


def _spec_for(citation_type: str) -> List[tuple]:
    if citation_type == "STATUTE":
        return STATUTE_COMPONENTS
    if citation_type == "ADMIN_RULE":
        return ADMIN_RULE_COMPONENTS
    if citation_type in ("CASE", "CONSTITUTIONAL"):
        return CASE_COMPONENTS
    if citation_type in ("INTERPRETATION", "ADMIN_APPEAL"):
        return DECISION_COMPONENTS
    return []


def citation_components(citation_type: str, levels: Dict[str, Any],
                        *, article_cited: bool = True) -> List[Dict[str, Any]]:
    """verifier의 levels를 독립 항목 목록으로 옮긴다. 값이 없는 단계는 '확인하지 못함'이다."""
    out = []
    for key, label, level_key in _spec_for(citation_type):
        raw = levels.get(level_key)
        if raw is None:
            if level_key == "article" and not article_cited:
                raw = "NOT_CITED"
            elif level_key == "applicability":
                raw = "REVIEW_NEEDED"
            elif level_key == "number_format":
                raw = "VALID" if levels.get("level1") else "UNVERIFIED"
            else:
                raw = "UNVERIFIED"
        status, meaning = _MEANING.get(str(raw), ("UNVERIFIED", str(raw)))
        out.append({"key": key, "label": label, "status": status, "raw": str(raw), "meaning": meaning})
    return out


def identity_confirmed(citation_type: str, components: List[Dict[str, Any]]) -> bool:
    """인용 대상 자체(법령·조문, 판례 사건)가 공식 원문으로 확인됐는지.

    시간적 적용·사건 적용은 여기에 넣지 않는다. 그것이 남았다고 인용 대상이
    '미확인'인 것은 아니다.
    """
    by_key = {c["key"]: c["status"] for c in components}
    ok = ("CONFIRMED", "NOT_APPLICABLE")
    if citation_type == "STATUTE":
        return by_key.get("law_existence") == "CONFIRMED" and by_key.get("article_existence") in ok
    if citation_type == "ADMIN_RULE":
        return by_key.get("rule_existence") == "CONFIRMED" and by_key.get("article_existence") in ok
    if citation_type in ("CASE", "CONSTITUTIONAL"):
        return by_key.get("case_existence") == "CONFIRMED" and by_key.get("metadata") == "CONFIRMED"
    if citation_type in ("INTERPRETATION", "ADMIN_APPEAL"):
        return by_key.get("existence") == "CONFIRMED"
    return False


def component_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """문서 단위 집계. '확인 0건'처럼 가장 약한 단계만 세지 않고 단계별로 센다."""
    summary = {"identity_confirmed": 0, "content_confirmed": 0, "temporal_pending": 0,
               "not_found_in_searched_scope": 0, "invalid_format": 0, "mismatch": 0, "lookup_unverified": 0,
               "fully_verified": 0}
    for entry in entries:
        components = entry.get("components") or []
        statuses = {c["key"]: c["status"] for c in components}
        if entry.get("identity_confirmed"):
            summary["identity_confirmed"] += 1
            if statuses.get("temporal_applicability") not in (None, "CONFIRMED"):
                summary["temporal_pending"] += 1
            # 인용 대상과, 문서가 그 대상에 대해 주장한 내용(인용문·조문 내용)까지 공식 원문으로 확인한 수.
            # 시간적 적용(기준일)만 남은 인용이 '미확인'으로 읽히지 않게 따로 센다(v2 R5).
            content = statuses.get("text_match") or statuses.get("quote_match") or statuses.get("quote")
            if content in ("CONFIRMED", "NOT_APPLICABLE") and not any(
                    c["status"] == "MISMATCH" for c in components):
                summary["content_confirmed"] += 1
        if any(c["status"] == "INVALID_FORMAT" for c in components):
            summary["invalid_format"] += 1
        elif any(c["status"].startswith("NOT_FOUND") for c in components):
            summary["not_found_in_searched_scope"] += 1
        elif any(c["status"] == "MISMATCH" for c in components):
            summary["mismatch"] += 1
        elif not entry.get("identity_confirmed"):
            summary["lookup_unverified"] += 1
        if entry.get("status") == "VERIFIED":
            summary["fully_verified"] += 1
    return summary


def affected_by_unavailable(source_name: str, citation_types: List[str]) -> Optional[List[str]]:
    """사용하지 못한 출처가 어떤 인용 유형의 검증에 쓰이는지. 관련 없으면 None."""
    domains = {
        "law_go_kr": {"CASE", "CONSTITUTIONAL", "STATUTE", "INTERPRETATION", "ADMIN_APPEAL", "ADMIN_RULE"},
        "kci": {"ACADEMIC"}, "crossref": {"ACADEMIC"}, "openalex": {"ACADEMIC"},
        "semantic_scholar": {"ACADEMIC"},
    }
    domain = domains.get(source_name.split(":")[0])
    if domain is None:
        return list(citation_types)  # 모르는 출처는 영향이 없다고 가정하지 않는다
    hit = [t for t in citation_types if t in domain]
    return hit or None
