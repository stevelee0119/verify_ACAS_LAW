"""제8장 개인정보 탐지 및 비식별화.

사건번호·판례번호·법령번호와 같이 법률 검증에 필요한 식별자를 오탐하지 않도록
도메인 규칙(Guard)을 둔다.
"""
from __future__ import annotations

import re
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
RRN_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})[-\s]?([1-8])(\d{6})(?!\d)")
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


def _in_legal_identifier(text: str, start: int, end: int) -> bool:
    for pattern in LEGAL_IDENTIFIER_PATTERNS:
        for m in pattern.finditer(text):
            if m.start() <= start and end <= m.end():
                return True
    return False


def detect(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> List[PIIMatch]:
    """텍스트에서 개인정보 후보를 찾는다."""
    matches: List[PIIMatch] = []
    if not text:
        return matches

    for kind, pattern, base_confidence in DETECTORS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _in_legal_identifier(text, start, end):
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
            if _in_legal_identifier(text, start, end):
                continue
            matches.append(PIIMatch(kind, name, start, end, block_id, page, 0.75, "직함·당사자 표기 문맥"))

    for pattern in (COMPANY_SUFFIX_RE, COMPANY_PREFIX_RE):
        for m in pattern.finditer(text):
            name = (m.group(1) or (m.lastindex and m.group(m.lastindex)) or "").strip()
            if not name or name in COMPANY_STOPWORDS:
                continue
            matches.append(PIIMatch("COMPANY", name, m.start(1), m.end(1), block_id, page, 0.8, "법인 표기"))

    # 중복 span 정리 (긴 매치 우선)
    matches.sort(key=lambda x: (x.start, -(x.end - x.start)))
    deduped: List[PIIMatch] = []
    for match in matches:
        if any(d.start <= match.start and match.end <= d.end for d in deduped):
            continue
        deduped.append(match)
    return deduped
