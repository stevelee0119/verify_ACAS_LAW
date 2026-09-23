"""제8장 개인정보 탐지 및 비식별화.

사건번호·판례번호·법령번호와 같이 법률 검증에 필요한 식별자를 오탐하지 않도록
도메인 규칙(Guard)을 둔다.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 법률 식별자 Guard — 이 패턴에 걸리는 구간은 PII로 마스킹하지 않는다
# ---------------------------------------------------------------------------
LEGAL_IDENTIFIER_PATTERNS = [
    re.compile(r"\d{4}\s*[가-힣]{1,3}\s*\d{1,6}"),          # 사건번호 2023도12345, 2026가합1234
    re.compile(r"\d{4}\s*헌[가-힣]\s*\d{1,4}"),              # 헌재 사건번호
    re.compile(r"제\s*\d+\s*조(\s*의\s*\d+)?"),               # 법령 조문
    re.compile(r"제\s*\d+\s*[항호]"),
    re.compile(r"법률\s*제\s*\d+\s*호"),
    re.compile(r"대통령령\s*제\s*\d+\s*호"),
    re.compile(r"등기\s*번호|등록\s*번호\s*제"),
    re.compile(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?"),          # 선고일자
    re.compile(r"\b(19|20)\d{2}\b"),                            # 연도
]

# 법인등록번호·사업자등록번호는 사건 검증에 쓰이므로 기본 마스킹 대상에서 제외한다
BUSINESS_NO_RE = re.compile(r"\b\d{3}-\d{2}-\d{5}\b")
CORP_NO_RE = re.compile(r"\b\d{6}-\d{7}\b")


@dataclass
class PIIMatch:
    kind: str
    text: str
    start: int
    end: int
    block_id: Optional[str] = None
    page: Optional[int] = None
    confidence: float = 1.0
    context_note: str = ""


# ---------------------------------------------------------------------------
# 규칙 기반 탐지기
# ---------------------------------------------------------------------------
# OCR 본문은 '800101 - 1234567'처럼 하이픈 앞뒤에 공백이 붙는다. 한 글자만 허용하면
# 이런 번호가 가려지지 않은 채 외부 모델로 나갔고, 모델이 정돈해 되돌려 준 번호 때문에
# 응답이 출력 검사에서 격리됐다. 줄바꿈은 넘지 않는다.
RRN_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})[ \t]*[-–]?[ \t]*([1-8])(\d{6})(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{2,3}[-\s]\d{2,6}[-\s]\d{2,6}(?:[-\s]\d{1,6})?(?!\d)")
MILITARY_ID_RE = re.compile(r"(?<![0-9A-Za-z])\d{2}[-\s]?\d{8}(?![0-9])|(?<![A-Za-z])[가-힣]?\d{7,8}(?=\s*군번)")
PASSPORT_RE = re.compile(r"\b[MSRODmsrod]\d{8}\b")
DOB_RE = re.compile(r"(19|20)\d{2}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*[일]?\s*(생|출생)")
ADDRESS_RE = re.compile(
    r"(?:[가-힣]+(?:특별시|광역시|특별자치시|도|특별자치도)\s*)?"
    r"[가-힣]+(?:시|군|구)\s+[가-힣0-9]+(?:읍|면|동|가|로|길)\s*[\d\-]*(?:번지|호)?"
)
# 이름 뒤에 붙는 조사를 이름으로 오인하지 않도록 조사 목록을 두고 non-greedy로 잡는다.
JOSA = r"(?:은|는|이|가|을|를|과|와|의|에게서|에게|에서|에|도|만|께서|께|으로|로|라고|이라고)"
NAME_RE = re.compile(
    r"(?<![가-힣])(?:원고|피고인|피고|참고인|피의자|증인|고소인|고발인|신청인|피신청인|채권자|채무자|망|소외)\s*"
    r"([가-힣]{2,4}?)" + JOSA + r"?(?![가-힣])"
)
# 법인 표기. 조사·부사로 끝나는 앞말을 상호로 오인하지 않도록 stopword를 둔다.
COMPANY_SUFFIX_RE = re.compile(r"(?<![가-힣])([가-힣A-Za-z0-9]{2,10})\s*(?:주식회사|㈜|유한회사|합자회사)")
COMPANY_PREFIX_RE = re.compile(r"(?:주식회사|유한회사|합자회사)\s+([가-힣A-Za-z0-9]{1,20})|㈜\s*([가-힣A-Za-z0-9]{1,20})")
COMPANY_STOPWORDS = {
    "따라", "대하여", "관하여", "위하여", "의하여", "그리고", "그러나", "다만", "또한",
    "상대로", "대한", "관한", "위한", "의한", "있는", "없는", "같은", "해당", "본건",
}

NAME_TITLE_RE = re.compile(
    r"(?<![가-힣])([가-힣]{2,4})\s*(?:씨|군|양|변호사|검사|판사|사무관|대위|중위|소령|중령|대령|병장|상병|일병|이병)(?![가-힣])"
)

DETECTORS: List[Tuple[str, re.Pattern[str], float]] = [
    ("RRN", RRN_RE, 1.0),
    ("EMAIL", EMAIL_RE, 1.0),
    ("PHONE", PHONE_RE, 0.95),
    ("PASSPORT", PASSPORT_RE, 0.8),
    ("MILITARY_ID", MILITARY_ID_RE, 0.7),
    ("ACCOUNT", ACCOUNT_RE, 0.6),
    ("DOB", DOB_RE, 0.9),
    ("ADDRESS", ADDRESS_RE, 0.8),
]

RRN_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]


def validate_rrn(digits: str) -> bool:
    """주민등록번호 검증부호 확인. 오탐을 줄이되 실패해도 탐지는 유지한다."""
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:12], RRN_WEIGHTS))
    return (11 - (total % 11)) % 10 == int(digits[12])


def legal_identifier_spans(text: str) -> List[Tuple[int, int]]:
    """법률 식별자 구간을 한 번만 찾아 병합해 둔다.

    종전에는 탐지 결과 하나마다 본문 전체를 다시 훑었다. 본문이 길고 숫자가
    많을수록 비용이 제곱으로 늘어, 수백 KB짜리 검증 결과에서는 한 번의 호출이
    수십 초에서 수 분까지 걸렸다. 구간을 미리 구해 두면 같은 판정을 선형
    시간에 내릴 수 있다.
    """
    spans: List[Tuple[int, int]] = []
    for pattern in LEGAL_IDENTIFIER_PATTERNS:
        spans.extend(m.span() for m in pattern.finditer(text))
    if not spans:
        return []
    spans.sort()
    merged: List[Tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # 겹치거나 맞닿으면 합친다
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def _covered_by_span(spans: List[Tuple[int, int]], start: int, end: int) -> bool:
    """[start, end)가 어느 식별자 구간 안에 온전히 들어가는지 본다."""
    if not spans:
        return False
    index = bisect_right(spans, (start, float("inf"))) - 1
    if index < 0:
        return False
    span_start, span_end = spans[index]
    return span_start <= start and end <= span_end


def _in_legal_identifier(text: str, start: int, end: int) -> bool:
    """단건 조회용 호환 함수. 반복 호출에는 legal_identifier_spans를 쓴다."""
    return _covered_by_span(legal_identifier_spans(text), start, end)


def detect(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> List[PIIMatch]:
    """텍스트에서 개인정보 후보를 찾는다."""
    matches: List[PIIMatch] = []
    if not text:
        return matches

    guard_spans = legal_identifier_spans(text)
    for kind, pattern, base_confidence in DETECTORS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _covered_by_span(guard_spans, start, end):
                continue
            raw = m.group(0)
            confidence = base_confidence
            note = ""
            if kind == "RRN":
                digits = re.sub(r"\D", "", raw)
                if validate_rrn(digits):
                    confidence = 1.0
                    note = "검증부호 일치"
                else:
                    confidence = 0.7
                    note = "형식 일치, 검증부호 불일치"
            if kind == "ACCOUNT":
                if BUSINESS_NO_RE.fullmatch(raw.strip()):
                    continue  # 사업자등록번호는 법인 식별에 필요
                if CORP_NO_RE.fullmatch(raw.strip()):
                    continue  # 법인등록번호
            matches.append(PIIMatch(kind, raw, start, end, block_id, page, confidence, note))

    for pattern, kind in ((NAME_RE, "PERSON"), (NAME_TITLE_RE, "PERSON")):
        for m in pattern.finditer(text):
            name = m.group(1)
            start, end = m.start(1), m.end(1)
            if _covered_by_span(guard_spans, start, end):
                continue
            matches.append(PIIMatch(kind, name, start, end, block_id, page, 0.75, "직함·당사자 표기 문맥"))

    for pattern in (COMPANY_SUFFIX_RE, COMPANY_PREFIX_RE):
        for m in pattern.finditer(text):
            # 선택지가 여럿인 패턴에서는 실제로 매치된 그룹의 위치를 써야 한다.
            # 무조건 group(1)의 위치를 쓰면 "㈜라마바"처럼 뒤쪽 선택지가 매치된
            # 경우 위치가 (-1, -1)로 남아 마스킹이 엉뚱한 곳을 가린다.
            index = next((i for i in range(1, (m.re.groups or 0) + 1) if m.group(i) is not None), None)
            if index is None:
                continue
            name = (m.group(index) or "").strip()
            if not name or name in COMPANY_STOPWORDS:
                continue
            matches.append(PIIMatch("COMPANY", name, m.start(index), m.end(index),
                                    block_id, page, 0.8, "법인 표기"))

    # 중복 span 정리 (긴 매치 우선).
    # start 오름차순이므로 앞선 항목의 start는 모두 현재 start 이하다. 따라서
    # "감싸는 항목이 있는가"는 지금까지 본 end의 최댓값 하나로 판정된다.
    # 매번 전체를 다시 훑으면 탐지 결과가 많을 때 비용이 제곱으로 늘어난다.
    matches.sort(key=lambda x: (x.start, -(x.end - x.start)))
    deduped: List[PIIMatch] = []
    covered_until = float("-inf")
    for match in matches:
        if match.end <= covered_until:
            continue
        deduped.append(match)
        covered_until = max(covered_until, match.end)
    return deduped
