"""호증 표기 전용 파서(v3 D6).

"갑 제5호증의 1 내지 3 각 진술서"처럼 가지번호 범위와 '각'이 붙은 표기를 일반 목록 규칙으로 자르면
자료명이 '내지 3각 진술서'가 된다. 당사자(갑·을·병·증), 번호, 가지번호(단일·범위), 자료명을 따로 읽는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

EXHIBIT_LABEL_RE = re.compile(
    r"(?P<party>갑|을|병|증)\s*(?:제\s*)?(?P<number>\d{1,3})\s*호\s*증"
    r"(?:\s*의\s*(?P<from>\d{1,3})(?:\s*(?:내지|~|∼|-|부터)\s*(?:의\s*)?(?P<to>\d{1,3})(?:\s*까지)?)?)?"
)
LEAD_RE = re.compile(r"^[\s:.)\]\-]*(?:각\s+|각(?=[가-힣]))?")
SPACES = str.maketrans({" ": " ", " ": " ", " ": " ", "　": " "})


def parse_exhibit_label(text: str) -> Optional[Dict[str, Any]]:
    """문자열 첫 호증 표기를 읽는다. {party, number, branch_from, branch_to, branches, label, name}"""
    clean = (text or "").translate(SPACES)
    match = EXHIBIT_LABEL_RE.search(clean)
    if not match:
        return None
    start = int(match.group("from")) if match.group("from") else None
    end = int(match.group("to")) if match.group("to") else start
    rest = LEAD_RE.sub("", clean[match.end():], count=1).strip()
    return {"party": match.group("party"), "number": int(match.group("number")),
            "branch_from": start, "branch_to": end,
            "branches": list(range(start, end + 1)) if start is not None and end is not None and end >= start else [],
            "label": " ".join(match.group(0).split()), "name": " ".join(rest.split()),
            "span": match.span()}

