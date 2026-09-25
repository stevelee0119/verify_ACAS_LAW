"""호증 표기 전용 파서(v3 D6, 과제 3 및 5 확장).

호증 접두어(갑·을·병·정·증·피고인 증·검사 증), 호증 번호(단일 및 '갑 제1, 2호증' 등 복수),
가지번호(단일 '의 2', 범위 '의 1 내지 3', 열거 '의 1, 2'), 자료명을 정확히 파싱한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# 호증 접두어: 복합 접두어(피고인 증, 검사 증) 우선 매칭
PARTY_RE_STR = r"(?P<party>피고인\s*증|검사\s*증|갑|을|병|정|증)"

# 호증 번호부: 단일 또는 쉼표 나열된 복수 호증 (예: '1', '1, 2', '1, 2, 3')
NUMBERS_RE_STR = r"(?P<numbers>\d{1,4}(?:\s*,\s*\d{1,4})*)"

# 전체 호증 정규식
EXHIBIT_LABEL_RE = re.compile(
    rf"{PARTY_RE_STR}\s*(?:제\s*)?{NUMBERS_RE_STR}\s*호\s*증"
    r"(?:\s*의\s*(?P<branch_str>\d{1,4}(?:\s*(?:내지|~|∼|-|부터)\s*(?:의\s*)?\d{1,4}(?:\s*까지)?|(?:\s*,\s*\d{1,4})+)?))?"
)

# 가지번호 범위 패턴: '1 내지 3', '1 ~ 3'
BRANCH_RANGE_RE = re.compile(
    r"^(?P<from>\d{1,4})\s*(?:내지|~|∼|-|부터)\s*(?:의\s*)?(?P<to>\d{1,4})(?:\s*까지)?$"
)

# 자료명 앞의 '각 ', 콜론, 괄호 등 정리
LEAD_RE = re.compile(r"^[\s:.)\]\-]*(?:각\s+|각(?=[가-힣]))?")
SPACES = str.maketrans({" ": " ", " ": " ", " ": " ", "　": " "})


def parse_branches(branch_str: Optional[str]) -> Tuple[Optional[int], Optional[int], List[int]]:
    """가지번호 문자열('1 내지 3', '1, 2', '4' 등)을 파싱하여 (start, end, branches_list)를 반환한다."""
    if not branch_str:
        return None, None, []
    b_clean = branch_str.strip()

    # 1. 범위 표기 ('1 내지 3')
    range_match = BRANCH_RANGE_RE.match(b_clean)
    if range_match:
        b_from = int(range_match.group("from"))
        b_to = int(range_match.group("to"))
        branches = list(range(b_from, b_to + 1)) if b_to >= b_from else [b_from]
        return b_from, b_to, branches

    # 2. 쉼표 나열 표기 ('1, 2' 또는 '1, 2, 3')
    if "," in b_clean:
        branches = [int(p.strip()) for p in b_clean.split(",") if p.strip().isdigit()]
        b_from = branches[0] if branches else None
        b_to = branches[-1] if branches else None
        return b_from, b_to, branches

    # 3. 단일 가지번호 ('1', '2' 등)
    if b_clean.isdigit():
        val = int(b_clean)
        return val, val, [val]

    return None, None, []


def parse_exhibit_label(text: str) -> Optional[Dict[str, Any]]:
    """문자열 첫 호증 표기를 읽는다.
    
    반환 딕셔너리 구조:
    {
        "party": "갑",
        "number": 1,
        "numbers": [1, 2],
        "branch_from": 1,
        "branch_to": 3,
        "branches": [1, 2, 3],
        "label": "갑 제1호증의 1 내지 3",
        "name": "진술서",
        "span": (0, 16)
    }
    """
    clean = (text or "").translate(SPACES)
    match = EXHIBIT_LABEL_RE.search(clean)
    if not match:
        return None

    party_raw = match.group("party")
    party = " ".join(party_raw.split())  # '피고인  증' -> '피고인 증'

    # 호증 번호 파싱 (복수 호증 대응: '1, 2' -> numbers=[1, 2], number=1)
    numbers_str = match.group("numbers")
    numbers = [int(n.strip()) for n in numbers_str.split(",") if n.strip().isdigit()]
    primary_number = numbers[0] if numbers else 0

    # 가지번호 파싱
    branch_str = match.group("branch_str")
    start, end, branches = parse_branches(branch_str)

    rest = LEAD_RE.sub("", clean[match.end():], count=1).strip()
    return {
        "party": party,
        "number": primary_number,
        "numbers": numbers,
        "branch_from": start,
        "branch_to": end,
        "branches": branches,
        "label": " ".join(match.group(0).split()),
        "name": " ".join(rest.split()),
        "span": match.span(),
    }
