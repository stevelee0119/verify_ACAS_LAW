"""한글 금액 표기 해석과 한글·숫자 병기 대조(v4 P4, AMOUNT_WORDS_MISMATCH).

서면은 '금 칠백만원(7,500,000원)'처럼 한글과 숫자를 함께 적는다. 두 값이 다르면 어느 쪽이 맞는지 문서만으로는
알 수 없으므로 불일치만 보고한다(Evidence A: 같은 문장 안의 두 표기를 계산으로 대조).

해석 범위: 일·이·삼…구, 십·백·천, 만·억·조 단위와 숫자 혼용('3억 5천만', '1억2,000만'). '일금 …원정'의
'일금'·'정'은 표기 관습으로 보고 뺀다. 해석할 수 없는 글자가 섞이면 None을 돌려준다(추측하지 않는다).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import List, Optional

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text

ENGINE_NAME = "claim_engine.korean_amount"
DIGITS = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
SMALL = {"십": 10, "백": 100, "천": 1000}
LARGE = {"만": 10 ** 4, "억": 10 ** 8, "조": 10 ** 12}
WORD_CHARS = "영공일이삼사오육륙칠팔구십백천만억조"
# 한글 금액(숫자 섞임 허용) 뒤에 괄호 안 숫자 금액, 또는 그 반대
# 앞 글자가 한글이면(조사 '이' 등) 금액의 시작이 아니다. '금'·'일금' 바로 뒤는 허용한다.
KOREAN_AMOUNT = rf"(?:(?<=금)|(?<![가-힣\d]))(?:\d[\d,]*\s*)?[{WORD_CHARS}](?:[{WORD_CHARS}\d,\s]*[{WORD_CHARS}])?"
CURRENCY_PREFIX = r"(?:일금\s*|금\s*|[₩\\￥]\s*|KRW\s*)"
AMOUNT_SUFFIX = r"(?:\s*원정|\s*원|\s*정)"
NUMERIC_AMOUNT = r"\d{1,3}(?:,\d{3})+|\d+"

PAIR_RE = re.compile(
    rf"(?:{CURRENCY_PREFIX})?\s*(?P<words>{KOREAN_AMOUNT}){AMOUNT_SUFFIX}?\s*[(（]\s*(?:{CURRENCY_PREFIX})?(?P<digits>{NUMERIC_AMOUNT}){AMOUNT_SUFFIX}?\s*[)）]"
    rf"|(?:{CURRENCY_PREFIX})?(?P<digits2>{NUMERIC_AMOUNT}){AMOUNT_SUFFIX}?\s*[(（]\s*(?:{CURRENCY_PREFIX})?\s*(?P<words2>{KOREAN_AMOUNT}){AMOUNT_SUFFIX}?\s*[)）]"
)


def _small(text: str) -> Optional[int]:
    """만 미만 구간('칠백오십', '3천5백', '2,000')의 값."""
    if not text:
        return 0
    if re.fullmatch(r"[\d,]+", text):
        return int(text.replace(",", ""))
    total, pending = 0, None
    for ch in re.findall(r"\d+|[^\d]", text.replace(",", "")):
        if ch.isdigit():
            if pending is not None:
                return None
            pending = int(ch)
        elif ch in DIGITS:
            if pending is not None:
                return None
            pending = DIGITS[ch]
        elif ch in SMALL:
            total += (1 if pending is None else pending) * SMALL[ch]
            pending = None
        else:
            return None
    return total + (pending or 0)


def parse_korean_amount(text: str) -> Optional[Decimal]:
    """'이억오천만' → 250000000. 해석할 수 없으면 None."""
    body = re.sub(r"\s+", "", text or "")
    body = re.sub(r"^(?:일금|금|[₩\\￥]|KRW)+", "", body)
    body = re.sub(r"(?:원정|원|정)+$", "", body)
    if not body or not re.fullmatch(rf"[{WORD_CHARS}\d,]+", body):
        return None
    if not re.search(rf"[{WORD_CHARS}]", body):
        return None
    total = 0
    for part in re.split(r"(?<=[만억조])", body):
        if not part:
            continue
        unit = LARGE.get(part[-1])
        head = part[:-1] if unit else part
        value = _small(head)
        if value is None:
            return None
        if unit and value == 0 and head == "":
            value = 1  # '만원', '억원'
        total += value * (unit or 1)
    return Decimal(total)


def words_digits_mismatches(doc: NormalizedDocument) -> List[Finding]:
    text = build_reading_text(doc).text
    out: List[Finding] = []
    for m in PAIR_RE.finditer(text):
        words, digits = (m.group("words"), m.group("digits")) if m.group("words") else (m.group("words2"), m.group("digits2"))
        word_value = parse_korean_amount(words)
        if word_value is None:
            continue
        digit_value = Decimal(digits.replace(",", ""))
        if word_value == digit_value:
            continue
        excerpt = " ".join(m.group(0).split())
        features = {"deterministic_rule": True, "arithmetic_proof": True, "rule_id": "AMOUNT.WORDS_MISMATCH",
                    "defect_code": "AMOUNT_WORDS_MISMATCH", "words": words.strip(), "words_value": str(word_value),
                    "digits_value": str(digit_value), "difference": str(digit_value - word_value)}
        out.append(Finding.create(
            type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.A,
            title=f"한글 금액과 숫자 금액이 다르다(AMOUNT_WORDS_MISMATCH): '{words.strip()}'={word_value:,}원 / 숫자 {digit_value:,}원",
            detail=(f"같은 자리에 병기한 한글 금액 '{words.strip()}'은 {word_value:,}원이고 숫자 금액은 {digit_value:,}원이다"
                    f"(차이 {digit_value - word_value:,}원). 어느 쪽이 맞는지는 문서만으로 알 수 없으므로 원본을 확인해야 한다."),
            confidence=0.95, confidence_features=features, document_id=doc.document_id, engine=ENGINE_NAME,
            tags=["CALCULATION", "AMOUNT"],
            evidence=[Evidence.create(description="한글·숫자 병기", grade=EvidenceGrade.A, document_id=doc.document_id,
                                      excerpt=excerpt[:200])]))
    return out
