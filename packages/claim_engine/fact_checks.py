"""기간·일수 재계산(추가지시 G5).

- 날짜 구간 표기("A ~ B (N일간)", "A부터 B까지 N일간")의 일수를 초일 산입(B−A+1)과 불산입(B−A) 두 방식으로 계산해
  둘 다 N과 다를 때만 판정한다.
- 기간 경과 주장("X부터 N년이 경과한 Y", "X부터 Y까지 N년이 경과")은 만료일을 계산해 Y가 가장 이른 만료일(초일 산입)
  이전이면 판정한다. 만료일은 민법 제160조(역에 의한 계산)처럼 연·월 단위로 더하고, 해당 일이 없는 달은 말일로 한다.
  Y 바로 뒤에 소멸·만료·완성 같은 말이 붙어 Y를 만료일로 적었는데 계산한 만료일(초일 불산입)보다 늦어도 판정한다.
- '약', '여', '가량' 같은 어림 표현은 보지 않는다. Y 뒤에 '현재·이후·무렵'이 붙으면 만료일 주장이 아니므로 늦은 쪽은 보지 않는다.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import List, Optional

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text

ENGINE_NAME = "claim_engine.fact_checks"
DATE = r"(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?"
BRIDGE = r"(?:[가-힣]{1,6}(?:인|일)\s+|[가-힣\s]{0,12}?)"
RANGE_RE = re.compile(
    rf"(?P<a>{DATE})\s*(?:~|∼|－|-|부터)\s*{BRIDGE}(?P<b>{DATE})\s*(?:까지)?\s*[,(（]?\s*(?:총\s*)?"
    rf"(?P<approx>약\s*|대략\s*)?(?P<n>\d{{1,4}})\s*(?P<unit>일|개월|년)(?P<tail>\s*(?:간|이|가)?\s*(?:경과|지나|도과)?)")
ELAPSED_RE = re.compile(
    rf"(?P<a>{DATE})\s*(?:로)?부터\s*(?P<approx>약\s*)?(?P<n>\d{{1,3}})\s*(?P<unit>년|개월|일)\s*(?:이|가)?\s*"
    rf"(?:경과한|지난|도과한)\s*{BRIDGE}(?P<b>{DATE})")

# Y를 만료일로 적었다는 표지(바로 뒤)와, 만료일이 아니라 시점만 가리키는 표지
EXPIRY_CLAIM_RE = re.compile(r"^\s*(?:에|로써|자로)?\s*(?:[가-힣]{1,10}\s+){0,2}(?:소멸|만료|완성|도과|종료|끝난)(?![가-힣]{0,6}\s*않)")
NOT_EXPIRY_RE = re.compile(r"^\s*(?:현재|이후|무렵|경|쯤|당시|에\s*이르기까지|까지는)")


def _date(text: str) -> Optional[date]:
    y, m, d = (int(x) for x in re.findall(r"\d+", text)[:3])
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _k(value: date) -> str:
    return f"{value.year}. {value.month}. {value.day}."


def add_period(start: date, n: int, unit: str) -> date:
    """start에 n년·n개월·n일을 더한 날. 그 달에 해당 일이 없으면 말일."""
    if unit == "일":
        return start + timedelta(days=n)
    months = n * 12 if unit == "년" else n
    y, m = divmod(start.month - 1 + months, 12)
    year, month = start.year + y, m + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _span(a: date, b: date) -> str:
    months = (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)
    years, rest = divmod(max(months, 0), 12)
    return (f"{years}년 " if years else "") + (f"{rest}개월" if rest or not years else "").strip()


def _finding(doc: NormalizedDocument, title: str, detail: str, excerpt: str, features) -> Finding:
    return Finding.create(
        type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.A, title=title, detail=detail + " 달력으로 다시 계산한 결정론적 결과이다.",
        confidence=0.9, confidence_features={"deterministic_rule": True, "arithmetic_proof": True, **features},
        document_id=doc.document_id, engine=ENGINE_NAME, tags=["CALCULATION", "PERIOD"],
        evidence=[Evidence.create(description="문서의 기간 기재", grade=EvidenceGrade.A, document_id=doc.document_id,
                                  excerpt=excerpt[:300])])


def check_periods(doc: NormalizedDocument) -> List[Finding]:
    text = build_reading_text(doc).text
    out: List[Finding] = []
    seen = set()
    for m in RANGE_RE.finditer(text):
        a, b = _date(m.group("a")), _date(m.group("b"))
        if not a or not b or b < a or m.group("approx"):
            continue
        n, unit, excerpt = int(m.group("n")), m.group("unit"), " ".join(m.group(0).split())
        if unit == "일":
            inclusive, exclusive = (b - a).days + 1, (b - a).days
            if n not in (inclusive, exclusive):
                seen.add(m.start())
                out.append(_finding(
                    doc, f"기간 일수가 날짜와 맞지 않는다: {excerpt}",
                    f"{_k(a)}부터 {_k(b)}까지는 초일을 넣으면 {inclusive}일, 빼면 {exclusive}일이다. 문서는 {n}일로 적었다.",
                    excerpt, {"rule_id": "CALC.DATE_RANGE_DAYS", "stated_days": n, "inclusive": inclusive,
                              "exclusive": exclusive}))
            continue
        earliest = add_period(a, n, unit) - timedelta(days=1)  # 초일 산입 시 만료일
        if b < earliest:
            seen.add(m.start())
            out.append(_finding(
                doc, f"주장한 기간이 날짜 사이의 실제 기간보다 길다: {excerpt}",
                f"{_k(a)}부터 {_k(b)}까지는 {_span(a, b)}이다. 문서가 적은 {n}{unit}에 이르려면 {_k(earliest)}"
                f"(초일 산입) 또는 {_k(earliest + timedelta(days=1))}(초일 불산입)까지 가야 한다.",
                excerpt, {"rule_id": "CALC.PERIOD_SPAN", "stated": f"{n}{unit}", "actual": _span(a, b)}))
    for m in ELAPSED_RE.finditer(text):
        if m.start() in seen or m.group("approx"):
            continue
        a, b = _date(m.group("a")), _date(m.group("b"))
        if not a or not b:
            continue
        n, unit, excerpt = int(m.group("n")), m.group("unit"), " ".join(m.group(0).split())
        expiry_excl = add_period(a, n, unit)            # 초일 불산입: 이 날의 종료로 만료
        expiry_incl = expiry_excl - timedelta(days=1)   # 초일 산입: 하루 앞선다
        if b <= expiry_incl:
            out.append(_finding(
                doc, f"기간 경과 주장과 만료일이 맞지 않는다: {excerpt}",
                f"{_k(a)}부터 {n}{unit}의 만료일은 {_k(expiry_incl)}(초일 산입) 또는 {_k(expiry_excl)}(초일 불산입, "
                f"민법 제157조)이다. {_k(b)}에는 아직 {n}{unit}이 경과하지 않았다.",
                excerpt, {"rule_id": "CALC.ELAPSED_EXPIRY", "expiry_inclusive": expiry_incl.isoformat(),
                          "expiry_exclusive": expiry_excl.isoformat(), "claimed_date": b.isoformat()}))
            continue
        after = text[m.end():m.end() + 30]
        if b > expiry_excl and EXPIRY_CLAIM_RE.search(after) and not NOT_EXPIRY_RE.search(after):
            out.append(_finding(
                doc, f"기간 만료일이 계산과 다르다: 문서 {_k(b)} / 계산 {_k(expiry_excl)} — {excerpt}",
                f"{_k(a)}부터 {n}{unit}의 만료일은 {_k(expiry_excl)}(초일 불산입, 민법 제157조·제160조) 또는 "
                f"{_k(expiry_incl)}(초일 산입)이다. 문서는 {_k(b)}를 만료(소멸·완성)일로 적었다.",
                excerpt, {"rule_id": "CALC.EXPIRY_DATE", "expiry_inclusive": expiry_incl.isoformat(),
                          "expiry_exclusive": expiry_excl.isoformat(), "claimed_date": b.isoformat()}))
    return out
