"""법령 조문 본문 대조: 문서가 그 조문에 대해 주장한 내용과 공식 조문 본문을 비교한다.

직접 인용문이 없어도 서면은 "행정소송법 제20조 제1항에 따르면 … 60일 이내에 제기하여야"처럼 조문의 내용을
풀어 쓴다. 조문 본문을 확보하고도 이 내용을 비교하지 않으면 실존 조문의 수치 오기를 놓치고, 대조가 끝나지
않았으니 실존 인용도 끝내 '확인됨'이 되지 못한다(v2 R5).

판단 규칙(보수적):
- 수치는 '규칙으로 주장된 수치'만 비교한다. 분수(3분의 1), 기한(N일 이내·안에·내에, …부터 N일,
  N일 전까지)이다. 처분의 실제 기간(정직 2개월)처럼 사안의 사실인 수치는 비교하지 않는다.
- 주장한 수치가 조문 본문의 같은 단위 수치 어디에도 없고, 조문에 같은 단위의 수치가 있으면 불일치다.
- 수치가 모두 조문에 있으면 일치다. 수치가 없으면 핵심어 겹침이 충분할 때만 일치로 본다.
- 겹침이 부족하면 '판단 보류'다. 의미 차이를 불일치로 단정하지 않는다.
- 조문에 대해 아무 내용도 주장하지 않았으면(근거 조문 표시만) 대조할 주장이 없다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

FRACTION_RE = re.compile(r"(?P<den>\d+)\s*분\s*의\s*(?P<num>\d+)")
# 기한으로 주장된 기간: "90일 이내", "30일 안에", "7일 전까지", "(…날부터 30일)"
PERIOD_CLAIM_RE = re.compile(
    r"(?:부터|로부터)\s*(?P<a>\d+)\s*(?P<ua>일|개월|년)|"
    r"(?P<b>\d+)\s*(?P<ub>일|개월|년)\s*(?:이내|안에|내에|내|이상|이하|전까지|전에|을\s*경과|이\s*지나)"
)
PERIOD_ANY_RE = re.compile(r"(?P<n>\d+)\s*(?P<u>일|개월|년)(?!\s*[.월])")
# 날짜 속 숫자("2026년 7월 8일")는 기간이 아니다.
DATE_CONTEXT_RE = re.compile(r"\d+\s*[년월.]\s*$")
TERM_RE = re.compile(r"[가-힣]{2,}")
JOSA_TAILS = ("에서는", "으로서", "에게서", "이라도", "에서", "에게", "으로", "부터", "까지", "라도", "하여",
              "하고", "하는", "한다", "하며", "되는", "된다", "에는", "와", "과", "의", "를", "을", "이", "가",
              "은", "는", "에", "로", "도", "만")
STOP_TERMS = {"따르면", "따라", "의하면", "규정", "규정하고", "정하고", "정한", "있습니다", "합니다", "하여야",
              "경우", "그리고", "또한", "이는", "원고", "피고", "원고는", "피고는", "이러한", "해당"}
MIN_TERMS = 3
TERM_OVERLAP = 0.6


def _fractions(text: str) -> List[Tuple[int, int]]:
    return [(int(m.group("den")), int(m.group("num"))) for m in FRACTION_RE.finditer(text or "")]


def _claimed_periods(text: str) -> List[Tuple[int, str]]:
    out = []
    for m in PERIOD_CLAIM_RE.finditer(text or ""):
        key = "a" if m.group("a") else "b"
        number, unit = m.group(key), m.group("u" + key)
        if DATE_CONTEXT_RE.search(text[max(0, m.start(key) - 12):m.start(key)]):
            continue  # "2026년 7월 8일"의 8일은 기간이 아니다
        out.append((int(number), unit))
    return out


def _all_periods(text: str) -> List[Tuple[int, str]]:
    return [(int(m.group("n")), m.group("u")) for m in PERIOD_ANY_RE.finditer(text or "")]


def _terms(text: str) -> List[str]:
    out = []
    for token in TERM_RE.findall(text or ""):
        for tail in JOSA_TAILS:
            if len(token) > len(tail) + 1 and token.endswith(tail):
                token = token[: -len(tail)]
                break
        if len(token) >= 2 and token not in STOP_TERMS:
            out.append(token)
    return out


def compare_claim_to_provision(claim: Optional[str], provision_text: str, *, numbers_only: bool = False) -> Dict[str, Any]:
    """문서의 주장(claim)과 조문 본문을 비교한다.

    numbers_only: 괄호 안 근거 표시처럼 앞 절이 조문 내용이 아니라 사안에 대한 결론일 수 있을 때는
    규칙 수치만 비교하고, 핵심어 겹침으로는 판단하지 않는다.

    반환 status: VERIFIED(일치) · CONTRADICTED(규칙 수치 불일치) · UNVERIFIED(판단 보류) · NOT_ASSERTED(주장 없음)
    """
    claim = " ".join((claim or "").split())
    body = " ".join((provision_text or "").split())
    if not body:
        return {"status": "UNVERIFIED", "reason": "조문 본문 없음"}
    claimed_fractions = _fractions(claim)
    claimed_periods = _claimed_periods(claim)
    body_fractions = set(_fractions(body))
    body_periods = set(_all_periods(body))
    mismatches: List[Dict[str, str]] = []
    matched: List[str] = []
    for fraction in claimed_fractions:
        label = f"{fraction[0]}분의 {fraction[1]}"
        if fraction in body_fractions:
            matched.append(label)
        elif body_fractions:
            mismatches.append({"claimed": label,
                               "official": ", ".join(f"{d}분의 {n}" for d, n in sorted(body_fractions))})
    for number, unit in claimed_periods:
        label = f"{number}{unit}"
        same_unit = sorted(n for n, u in body_periods if u == unit)
        if number in same_unit:
            matched.append(label)
        elif same_unit:
            mismatches.append({"claimed": label, "official": ", ".join(f"{n}{unit}" for n in same_unit)})
    if mismatches:
        return {"status": "CONTRADICTED", "basis": "NUMERIC", "mismatches": mismatches, "matched": matched}
    if matched:
        return {"status": "VERIFIED", "basis": "NUMERIC", "matched": matched}
    terms = list(dict.fromkeys(_terms(claim)))
    if numbers_only or not terms:
        return {"status": "NOT_ASSERTED", "reason": "문서가 조문 내용을 주장하지 않고 근거로만 표시했다"}
    compact_body = body.replace(" ", "")
    found = [t for t in terms if t in compact_body]
    ratio = len(found) / len(terms)
    if len(terms) >= MIN_TERMS and ratio >= TERM_OVERLAP:
        return {"status": "VERIFIED", "basis": "TERMS", "overlap": round(ratio, 2), "terms": found[:10]}
    if len(terms) < MIN_TERMS:
        return {"status": "NOT_ASSERTED", "reason": "조문 내용에 관한 주장이 짧아 대조할 내용이 없다",
                "terms": terms}
    return {"status": "UNVERIFIED", "basis": "TERMS", "overlap": round(ratio, 2),
            "reason": "주장과 조문 본문의 핵심어 겹침이 부족해 자동으로 판단하지 않았다(사람 확인)"}
