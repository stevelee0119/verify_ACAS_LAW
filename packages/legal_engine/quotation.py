"""제4.5장 직접인용 대조.

따옴표 안의 구절은 공백과 문장부호를 제외하고 원문과 엄격 대조한다.
생략은 말줄임표 등 명시 표시가 있어야 하고, 생략으로 의미가 바뀌면 오류다.

원문을 확보하지 못한 인용은 일치도 불일치도 아니다. UNVERIFIED로 남긴다.
검색 스니펫으로 대조해 통과시키지 않는다(제11.1장).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding

ENGINE_NAME = "legal_engine.quotation"

# 직접인용 표지. 「」는 조문, 『』는 서명(書名)에 쓰이므로 인용부호에서 제외한다.
QUOTE_PATTERNS = [
    re.compile(r"[“](?P<q>[^”]{6,600})[”]"),
    re.compile(r'"(?P<q>[^"\n]{6,600})"'),
    re.compile(r"[‘](?P<q>[^’]{10,600})[’]"),
]

ELLIPSIS_MARKERS = ("…", "···", "...", "(중략)", "〔중략〕", "[중략]", "(생략)", "(이하 생략)")

# 생략되면 의미가 뒤집히는 어구. 이 어구가 원문에만 있고 인용문에 없으면
# 단순한 축약이 아니라 취지가 바뀐 인용이다.
MEANING_BEARING = (
    "아니", "없", "못", "제외", "다만", "그러나", "단서", "예외",
    "한하여", "한한다", "경우에만", "원칙적으로", "특별한 사정이 없는 한",
)

STRICT_MATCH_RATIO = 0.995
NEAR_MATCH_RATIO = 0.90


def normalize_for_compare(text: str) -> str:
    """공백과 문장부호를 제외한 비교용 문자열.

    원문 대조에서 띄어쓰기와 쉼표 차이를 불일치로 잡으면 실제 왜곡이
    그 소음에 묻힌다. 반대로 어미나 조사를 지우면 취지 변경을 놓치므로
    글자 자체는 건드리지 않는다.
    """
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s.,·:;'\"“”‘’()\[\]〔〕【】「」『』]", "", text)


def extract_quotes(text: str) -> List[Tuple[str, int, int]]:
    """본문에서 직접인용 구절과 그 위치를 뽑는다."""
    found: List[Tuple[str, int, int]] = []
    occupied: List[Tuple[int, int]] = []
    for pattern in QUOTE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("q")
            if any(s <= start < e or s < end <= e for s, e in occupied):
                continue
            occupied.append((start, end))
            found.append((match.group("q").strip(), start, end))
    return sorted(found, key=lambda item: item[1])


@dataclass
class QuoteCheck:
    """인용 한 건의 대조 결과."""

    quoted: str
    status: VerificationStatus
    ratio: Optional[float] = None
    has_ellipsis_marker: bool = False
    omitted_meaning_terms: List[str] = field(default_factory=list)
    source_label: str = ""
    source_excerpt: str = ""
    span: Optional[Tuple[int, int]] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"quoted": self.quoted, "status": str(self.status),
                "ratio": round(self.ratio, 4) if self.ratio is not None else None,
                "has_ellipsis_marker": self.has_ellipsis_marker,
                "omitted_meaning_terms": list(self.omitted_meaning_terms),
                "source_label": self.source_label,
                "source_excerpt": self.source_excerpt, "note": self.note}


def _best_window(needle: str, haystack: str) -> float:
    """원문 안에서 인용문과 가장 닮은 구간의 유사도."""
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
    blocks = matcher.get_matching_blocks()
    covered = sum(b.size for b in blocks)
    return covered / len(needle)


def check_quote(quoted: str, source_text: Optional[str], *,
                source_label: str = "", span: Optional[Tuple[int, int]] = None) -> QuoteCheck:
    """인용문 한 건을 원문과 대조한다."""
    if source_text is None:
        return QuoteCheck(
            quoted=quoted, status=VerificationStatus.UNVERIFIED, source_label=source_label,
            span=span,
            note=("공식 원문을 확보하지 못해 대조하지 못했다. 검색 요약이나 모델의 "
                  "기억으로 일치를 인정하지 않는다."),
        )

    has_marker = any(marker in quoted for marker in ELLIPSIS_MARKERS)
    needle = normalize_for_compare(re.sub("|".join(map(re.escape, ELLIPSIS_MARKERS)), "", quoted))
    haystack = normalize_for_compare(source_text)
    ratio = _best_window(needle, haystack)

    omitted = [term for term in MEANING_BEARING
               if normalize_for_compare(term) in haystack and normalize_for_compare(term) not in needle]

    if ratio >= STRICT_MATCH_RATIO:
        status = VerificationStatus.VERIFIED
        note = "공백·문장부호를 제외하고 원문과 일치한다."
        if omitted and has_marker:
            note += " 생략 표시가 있으나 생략된 부분에 단서·예외 표현이 포함되어 있는지 확인이 필요하다."
    elif ratio >= NEAR_MATCH_RATIO and has_marker:
        status = VerificationStatus.PARTIALLY_VERIFIED
        note = "생략 표시가 있는 인용이다. 생략으로 취지가 달라지지 않았는지 확인이 필요하다."
    elif ratio >= NEAR_MATCH_RATIO:
        status = VerificationStatus.CONTRADICTED
        note = "원문과 다른 부분이 있으나 생략 표시가 없다."
    else:
        status = VerificationStatus.CONTRADICTED
        note = "원문에서 해당 표현을 찾지 못했다."

    return QuoteCheck(quoted=quoted, status=status, ratio=ratio,
                      has_ellipsis_marker=has_marker,
                      omitted_meaning_terms=omitted if status != VerificationStatus.VERIFIED else [],
                      source_label=source_label, source_excerpt=source_text[:300],
                      span=span, note=note)


def quote_findings(checks: Sequence[QuoteCheck], *, document_id: Optional[str] = None,
                   page: Optional[int] = None,
                   finding_type: FindingType = FindingType.QUOTE_MISMATCH) -> List[Finding]:
    """제4.5장 QUOTE_MISMATCH. 원문 미확보는 Finding이 아니라 미검증 항목이다."""
    out: List[Finding] = []
    for check in checks:
        if check.status in (VerificationStatus.VERIFIED, VerificationStatus.UNVERIFIED):
            continue
        critical = check.status == VerificationStatus.CONTRADICTED
        detail = (f"인용: “{check.quoted[:160]}”\n"
                  f"원문 대조 유사도 {check.ratio:.3f}. {check.note}")
        if check.omitted_meaning_terms:
            terms = ", ".join(check.omitted_meaning_terms[:5])
            detail += f"\n원문에는 있으나 인용문에 빠진 한정 표현: {terms}. 생략으로 취지가 달라질 수 있다."
        out.append(Finding.create(
            type=finding_type,
            status=check.status,
            severity=Severity.CRITICAL if critical else Severity.MEDIUM,
            evidence_grade=EvidenceGrade.A,
            title=("직접인용이 원문과 일치하지 않는다" if critical
                   else "생략된 직접인용이다. 취지 변경 여부 확인이 필요하다"),
            detail=detail,
            confidence=0.9 if critical else 0.6,
            document_id=document_id, page=page, span=check.span, engine=ENGINE_NAME,
            evidence=[Evidence.create(
                description=f"공식 원문 대조({check.source_label or '원문'})",
                grade=EvidenceGrade.A, excerpt=check.source_excerpt,
            )],
            tags=["quotation"],
        ))
    return out


# --- 단서·예외 누락 ------------------------------------------------------------
PROVISO_MARKERS = ("다만,", "다만 ", "그러하지 아니하다", "그러하지 않다", "예외로 한다",
                   "이 경우에는", "단, ")


def check_proviso_omission(quoted: str, source_text: str, citing_text: str,
                           *, lookahead: int = 200) -> Optional[str]:
    """인용은 정확하지만 뒤따르는 단서를 빠뜨렸는지 본다.

    문장 자체를 그대로 옮겼더라도 바로 뒤의 단서를 가리면 조문의 요건이
    달라진다. 인용 불일치(QUOTE_MISMATCH)와는 다른 결함이므로 따로 본다.
    반환값은 누락된 단서 원문이며, 없으면 None이다.
    """
    needle = normalize_for_compare(quoted)
    haystack = normalize_for_compare(source_text)
    if not needle or needle not in haystack:
        return None
    # 정규화 문자열의 위치를 원문 위치로 되돌릴 수 없으므로, 원문에서 인용
    # 끝부분의 마지막 몇 글자를 찾아 그 뒤를 본다.
    tail = re.sub(r"\s+", "", quoted)[-8:]
    index = -1
    for offset in range(len(source_text)):
        if not re.sub(r"\s+", "", source_text[offset:offset + 40]).startswith(tail):
            continue
        # 공백을 뺀 글자수로 tail만큼 전진해야 원문에서의 끝 위치가 나온다.
        consumed, cursor = 0, offset
        while cursor < len(source_text) and consumed < len(tail):
            if not source_text[cursor].isspace():
                consumed += 1
            cursor += 1
        index = cursor
        break
    following = source_text[index:index + lookahead] if index >= 0 else ""
    if not following:
        position = haystack.find(needle) + len(needle)
        following = source_text[position:position + lookahead]
    if not any(marker in following for marker in PROVISO_MARKERS):
        return None
    normalized_citing = normalize_for_compare(citing_text)
    proviso = following.lstrip(" .,·\u3002").strip()
    # 인용 문서가 단서를 어딘가에서 언급했다면 누락이 아니다.
    key = normalize_for_compare(proviso[:20])
    if key and key in normalized_citing:
        return None
    return proviso


def proviso_finding(proviso: str, *, source_label: str = "",
                    document_id: Optional[str] = None,
                    page: Optional[int] = None) -> Finding:
    """제1.2장 STATUTE_TEXT_MISMATCH(단서·예외 누락)."""
    return Finding.create(
        type=FindingType.STATUTE_TEXT_MISMATCH,
        status=VerificationStatus.PARTIALLY_VERIFIED,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.A,
        title=f"본문만 인용하고 단서를 빠뜨렸다{f': {source_label}' if source_label else ''}",
        detail=(f"원문에는 뒤이어 단서가 있다: “{proviso[:200]}”. "
                f"단서를 함께 보지 않으면 요건이 달라진다."),
        confidence=0.85,
        document_id=document_id, page=page, engine=ENGINE_NAME,
        evidence=[Evidence.create(description=f"원문 단서({source_label or '원문'})",
                                  grade=EvidenceGrade.A, excerpt=proviso[:300])],
        tags=["quotation", "proviso"],
    )
