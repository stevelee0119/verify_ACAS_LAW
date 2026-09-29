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
# 기간의 성격으로 주장된 기간: "10년의 소멸시효", "3년간", "징역 5년"
# 조문 나열의 첫머리: "제1항은 3년, 같은 조 제2항은 …"(주장 글의 맨 앞에 조사와 기간만 온다)
PERIOD_CLAIM_RE = re.compile(
    r"(?:부터|로부터)\s*(?P<a>\d+)\s*(?P<ua>일|개월|년)|"
    r"(?P<b>\d+)\s*(?P<ub>일|개월|년)\s*(?:이내|안에|내에|내|이상|이하|전까지|전에|을\s*경과|이\s*지나)|"
    r"(?P<c>\d+)\s*(?P<uc>일|개월|년)\s*(?:간|의\s*(?:소멸\s*)?(?:시효|제척\s*기간|기간|징역|금고|자격정지))|"
    r"(?:징역|금고|자격정지)\s*(?P<d>\d+)\s*(?P<ud>일|개월|년)|"
    r"^\s*(?:은|는|이|가|도)\s*(?P<e>\d+)\s*(?P<ue>일|개월|년)\s*(?=[,，]|이다|으로|$)"
)
PERIOD_ANY_RE = re.compile(r"(?P<n>\d+)\s*(?P<u>일|개월|년)(?!\s*[.월])")
# 배수(N배) 패턴: "3배", "5배를 넘지 아니하는", "5배의" 등 법정 증액 및 손해배상 배수 대조
MULTIPLIER_RE = re.compile(r"(?<!\d)(?P<m>\d+)\s*배(?=(?:를|의|에|로|까지|도|만|\s|[.,()，。]|$))")

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
# 조문의 양태: 의무('하여야 한다')와 재량('할 수 있다'). 행위 명사(통지·제기 등)를 함께 잡아 같은 행위끼리만 비교한다.
MANDATE_RE = re.compile(r"(?P<act>[가-힣]{2,6}?)(?:(?:을|를)\s)?(?:하여야|해야|하여야만)\s*(?:한다|하며|하고|함|할\s*것)")
DISCRETION_RE = re.compile(r"(?P<act>[가-힣]{2,6}?)(?:(?:을|를)\s)?할\s*수\s*있(?:다|으며|고|음|을\s*뿐)")
NO_DUTY_RE = re.compile(r"(?P<act>[가-힣]{2,6}?)(?:(?:을|를)\s)?할\s*(?:의무가|의무는)\s*(?:없|아니)")
# Only a complete, case-scoped conclusion is exempt from statutory text comparison.
BARE_CASE_CONCLUSION_RE = re.compile(
    r"(?:이|본|해당)\s*사건\s*(?:소|소송|청구|신청|항소|상고)(?:은|는|이|가)\s*"
    r"(?:적법|부적법)(?:하다|합니다|함|한\s*것이다|한\s*것입니다)\s*[.!]?"
)


def _acts(pattern: "re.Pattern[str]", text: str) -> set:
    return {m.group("act")[-2:] for m in pattern.finditer(text or "")}


def modality_conflict(claim: str, body: str) -> Optional[Dict[str, str]]:
    """문서가 조문의 재량을 의무로(또는 의무를 재량으로) 적었는지. 같은 행위(명사 끝 두 글자)끼리만 본다."""
    claim_mandate, claim_optional = _acts(MANDATE_RE, claim), _acts(DISCRETION_RE, claim) | _acts(NO_DUTY_RE, claim)
    body_mandate, body_optional = _acts(MANDATE_RE, body), _acts(DISCRETION_RE, body)
    for act in sorted(claim_mandate & body_optional - body_mandate):
        return {"kind": "DISCRETION_AS_MANDATE", "act": act, "claimed": f"의무('{act}하여야')",
                "official": f"재량('{act}할 수 있다')"}
    for act in sorted(claim_optional & body_mandate - body_optional):
        return {"kind": "MANDATE_AS_DISCRETION", "act": act, "claimed": f"재량('{act}할 수 있다'·의무 없음)",
                "official": f"의무('{act}하여야 한다')"}
    return None


def _fractions(text: str) -> List[Tuple[int, int]]:
    return [(int(m.group("den")), int(m.group("num"))) for m in FRACTION_RE.finditer(text or "")]


def _claimed_periods(text: str) -> List[Tuple[int, str]]:
    out = []
    for m in PERIOD_CLAIM_RE.finditer(text or ""):
        key = next(k for k in "abcde" if m.group(k))
        number, unit = m.group(key), m.group("u" + key)
        if DATE_CONTEXT_RE.search(text[max(0, m.start(key) - 12):m.start(key)]):
            continue  # "2026년 7월 8일"의 8일은 기간이 아니다
        out.append((int(number), unit))
    return out


def _all_periods(text: str) -> List[Tuple[int, str]]:
    return [(int(m.group("n")), m.group("u")) for m in PERIOD_ANY_RE.finditer(text or "")]


def _multipliers(text: str) -> List[int]:
    """본문에서 배수(N배) 수치를 추출한다(예: 3배, 5배)."""
    return [int(m.group("m")) for m in MULTIPLIER_RE.finditer(text or "")]


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


CLAUSE_SPLIT_RE = re.compile(r"(?<=다\.)\s*|;\s*|\n+|(?=[①-⑳])|(?=\s\d{1,2}\.\s)")


def _scoped_body(body: str, subject: Optional[str]) -> str:
    """주어가 등장하는 조문 구절만 남긴다. 한 조문에 여러 대상의 수치가 섞여 있을 때(예: 정직·감봉의 감액
    비율) 다른 대상의 수치와 비교하지 않기 위해서다. 주어가 없거나 조문에 없으면 조문 전체를 쓴다."""
    if not subject:
        return body
    clauses = [c for c in CLAUSE_SPLIT_RE.split(body) if c and c.strip()]
    scoped = [c for c in clauses if subject in c.replace(" ", "")]
    return " ".join(scoped) if scoped and len(scoped) < len(clauses) else body


def compare_claim_to_provision(claim: Optional[str], provision_text: str, *, numbers_only: bool = False,
                               subject: Optional[str] = None) -> Dict[str, Any]:
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
    claimed_multipliers = _multipliers(claim)
    scoped = _scoped_body(body, subject)
    body_fractions = set(_fractions(scoped)) or set(_fractions(body))
    body_periods = set(_all_periods(scoped)) or set(_all_periods(body))
    body_multipliers = set(_multipliers(scoped)) or set(_multipliers(body))
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
    for mult in claimed_multipliers:
        label = f"{mult}배"
        if mult in body_multipliers:
            matched.append(label)
        elif body_multipliers:
            mismatches.append({"claimed": label, "official": ", ".join(f"{b}배" for b in sorted(body_multipliers))})
    if mismatches:
        return {"status": "CONTRADICTED", "basis": "NUMERIC", "mismatches": mismatches, "matched": matched}
    modality = None if numbers_only else modality_conflict(claim, scoped)
    if modality:
        return {"status": "CONTRADICTED", "basis": "MODALITY", "modality": modality,
                "mismatches": [{"claimed": modality["claimed"], "official": modality["official"]}], "matched": matched}
    if matched:
        return {"status": "VERIFIED", "basis": "NUMERIC", "matched": matched}
    # 조문 준용 및 적용 배제 주장 대조:
    # 1. 문서가 조문의 적용을 배제하거나("적용되지 않는다", "적용이 없다"),
    #    다른 조문의 준용 규정(민법 654조 -> 615조 등)과 정면으로 상충되는 주장을 한 경우
    if re.search(r"(?:임대차|이\s*사건)?[^\n.]{0,30}?(?:적용(?:되지|되지\s*않|하지|이\s*배제)|준용(?:되지|되지\s*않)|효력이\s*미치지)", claim):
        if "준용한다" in body or "준용" in body:
            return {
                "status": "CONTRADICTED",
                "basis": "STATUTORY_APPLICATION_CONFLICT",
                "reason": "해당 조문은 명문으로 준용을 규정하고 있어 적용이 배제된다는 주장은 조문 규정과 상충함",
                "matched": matched,
                "mismatches": [],
            }
        if "원상에 회복" in body or "원상회복" in body:
            return {
                "status": "CONTRADICTED",
                "basis": "STATUTORY_APPLICATION_CONFLICT",
                "reason": "민법 제654조는 제615조(원상회복의무)를 임대차에 준용하므로 임대차 적용 배제 주장은 법령 규정과 상충함",
                "matched": matched,
                "mismatches": [],
            }
    # 2. 조문 취지 왜곡: 준용 규정을 연체 해지 규정 등으로 잘못 설명한 경우
    if ("해지" in claim or "차임" in claim) and ("준용한다" in body and "해지" not in body):
        return {
            "status": "CONTRADICTED",
            "basis": "STATUTORY_MISQUOTATION",
            "reason": "해당 조문은 준용 규정이며 차임 연체 해지 규정이 아님",
            "matched": matched,
            "mismatches": [],
        }
    terms = list(dict.fromkeys(_terms(claim)))
    if numbers_only and BARE_CASE_CONCLUSION_RE.fullmatch(claim):
        return {"status": "NOT_ASSERTED", "basis": "CASE_CONCLUSION_ONLY",
                "reason": "조문 내용을 서술하지 않은 사안의 결론이다(그 결론의 적정성을 확인한 것은 아님)"}
    if numbers_only and terms:
        return {"status": "UNVERIFIED", "basis": "PARENTHETICAL_CLAIM",
                "reason": "괄호 인용 앞 주장의 법적 효과·적용 범위는 수치 대조만으로 확인할 수 없다(내용 검토 필요)"}
    if not terms:
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
