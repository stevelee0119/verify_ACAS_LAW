"""호증 표기 문법과 파서(v3 D6, v5 3-1).

서면의 증거 표기는 형식이 여러 가지다. 한 가지 형식만 읽으면 목록에 있는 증거를 '결번'·'목록 누락'으로 잘못 판정한다.

문법(공백은 어디에나 올 수 있다. 전각 숫자도 읽는다):

    참조     := 당사자 번호묶음 ('호증' | '호'*) 가지번호? (구분자 '제'? 번호묶음 '호증' 가지번호?)*
    당사자   := 갑 | 을 | 병 | 정 | (갑|을|병) 가·나·다… (공동당사자, 예: 을가) | 증 | 피고인 증 | 검 증 | 검
    번호묶음 := '제'? 번호 (구분자 '제'? 번호)*  |  '제'? 번호 범위어 '제'? 번호
    가지번호 := '의' 번호 ((구분자 | 범위어) '의'? 번호)*
    구분자   := , · ㆍ ・ 및 와 과        범위어 := 내지 ~ ∼ - 부터…까지
    * '호'(증 없이)는 형사 증거 당사자(증·피고인 증·검 증·검)에만 허용한다(법령의 '제2호'와 구별).

예: 갑 제5호증의 1 내지 3 / 갑 제4호증의 1, 2 / 갑 제2, 3호증 / 갑 제2 내지 4호증 / 갑 제2호증, 제3호증 /
    을가 제1호증 / 증 제7호 / 피고인 증 제2호증의 1 / "갑 제5호증의 1 내지 3 각 진술서"의 '각'.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

SPACES = str.maketrans({" ": " ", " ": " ", " ": " ", "　": " ",
                        **{chr(0xFF10 + i): str(i) for i in range(10)}})
_SUB_PARTY = "가나다라마바사아자차카타파하"
# 갑·병·'피고인 증'은 조사로 쓰이지 않고 뒤에 '호증'이 반드시 오므로, 두 단 목록이 붙어 읽힌 '차용증갑 제2호증'처럼 앞에 한글이 있어도
# 읽는다. 을(목적격 조사)·증·검은 앞 글자가 한글이 아닐 때만 당사자로 본다('보증 제2호', '사실을 제3호' 구별).
PARTY_RE = re.compile(r"(?P<party>피고인\s*증|(?:갑|병)(?:\s?[" + _SUB_PARTY + r"](?=\s*(?:제\s*)?\d))?"
                      r"|(?<![가-힣])(?:검\s*증|을(?:\s?[" + _SUB_PARTY + r"](?=\s*(?:제\s*)?\d))?|정|증|검))"
                      r"(?=\s*(?:제\s*)?\d)")
NUM = r"\d{1,3}"
SEP = r"(?:\s*(?:,|·|ㆍ|・|및|와|과)\s*)"
RANGE = r"(?:\s*(?:내지|~|∼|〜|～|-|－)\s*)"
NUMBER_GROUP_RE = re.compile(rf"\s*(?:제\s*)?(?P<first>{NUM})(?P<more>(?:(?:{SEP}|{RANGE})(?:제\s*)?{NUM})*)\s*")
SUFFIX_RE = re.compile(r"호\s*증|호")
BRANCH_RE = re.compile(rf"\s*의\s*(?P<first>{NUM})(?P<more>(?:(?:{SEP}|{RANGE})(?:의\s*)?{NUM}(?:\s*까지)?)*)")
CONTINUE_RE = re.compile(rf"{SEP}(?=제\s*{NUM}\s*호)")
LEAD_RE = re.compile(r"^[\s:.)\]\-]*(?:각\s+|각(?=[가-힣]))?")
CRIMINAL_PARTIES = {"증", "피고인증", "검증", "검"}


def _numbers(first: str, more: str) -> List[int]:
    """'2', ', 3 내지 5' → [2, 3, 4, 5]. 범위어 뒤 번호는 앞 번호부터 이어진다."""
    values = [int(first)]
    for sep, value in re.findall(rf"({SEP}|{RANGE})(?:제\s*|의\s*)?({NUM})", more):
        value = int(value)
        if re.fullmatch(RANGE, sep) and value >= values[-1]:
            values.extend(range(values[-1] + 1, value + 1))
        else:
            values.append(value)
    return values


def _party(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def parse_exhibits(text: str) -> List[Dict[str, Any]]:
    """문자열의 모든 호증 참조. 번호마다 {party, number, branches, label, span} 하나씩(가지번호는 그 번호에 붙는다)."""
    clean = (text or "").translate(SPACES)
    out: List[Dict[str, Any]] = []
    for party_match in PARTY_RE.finditer(clean):
        party = _party(party_match.group("party"))
        pos = party_match.end()
        start = party_match.start()
        while True:
            group = NUMBER_GROUP_RE.match(clean, pos)
            if not group:
                break
            suffix = SUFFIX_RE.match(clean, group.end())
            if not suffix or (suffix.group(0) == "호" and party not in CRIMINAL_PARTIES):
                break
            numbers = _numbers(group.group("first"), group.group("more"))
            end = suffix.end()
            branches: List[int] = []
            branch = BRANCH_RE.match(clean, end)
            if branch:
                branches = _numbers(branch.group("first"), branch.group("more"))
                end = branch.end()
            for index, number in enumerate(numbers):
                out.append({"party": party, "number": number,
                            "branches": branches if index == len(numbers) - 1 else [],
                            "label": " ".join(clean[start:end].split()), "span": (start, end)})
            follow = CONTINUE_RE.match(clean, end)
            if not follow:
                break
            pos = follow.end()
    return out


def exhibit_keys(text: str) -> set:
    """본문이 언급한 (당사자, 번호) 집합."""
    return {(ref["party"], ref["number"]) for ref in parse_exhibits(text)}


def parse_exhibit_label(text: str) -> Optional[Dict[str, Any]]:
    """문자열 첫 호증 참조(쉼표로 묶인 번호 포함)를 읽는다. {party, number, numbers, branch_from, branch_to, branches,
    label, name, span}. name은 참조 뒤의 자료명('각' 제외)."""
    refs = parse_exhibits(text)
    if not refs:
        return None
    first = refs[0]
    same = [r for r in refs if r["span"] == first["span"]]
    clean = (text or "").translate(SPACES)
    rest = LEAD_RE.sub("", clean[first["span"][1]:], count=1).strip()
    branches = same[-1]["branches"]
    return {"party": first["party"], "number": first["number"], "numbers": [r["number"] for r in same],
            "branch_from": branches[0] if branches else None, "branch_to": branches[-1] if branches else None,
            "branches": branches, "label": first["label"], "name": " ".join(rest.split()), "span": first["span"]}


def split_items(text: str) -> List[Tuple[Dict[str, Any], str]]:
    """목록 한 줄에 증거가 여러 개 이어진 경우(두 단 목록이 한 줄로 읽힘) 참조마다 (참조, 자료명)으로 나눈다."""
    clean = (text or "").translate(SPACES)
    refs = parse_exhibits(clean)
    spans = sorted({r["span"] for r in refs})
    out: List[Tuple[Dict[str, Any], str]] = []
    for index, span in enumerate(spans):
        end = spans[index + 1][0] if index + 1 < len(spans) else len(clean)
        name = " ".join(LEAD_RE.sub("", clean[span[1]:end], count=1).split())
        for ref in (r for r in refs if r["span"] == span):
            out.append((ref, name))
    return out


# --- 시험용 조합기: 구조 → 여러 표기 → 다시 읽어 같은 구조인지 확인(속성 기반 시험) -------------------
def canonical(refs: List[Dict[str, Any]]) -> List[Tuple[str, int, Tuple[int, ...]]]:
    merged: Dict[Tuple[str, int], set] = {}
    for ref in refs:
        merged.setdefault((ref["party"], ref["number"]), set()).update(ref.get("branches") or [])
    return sorted((party, number, tuple(sorted(branches))) for (party, number), branches in merged.items())


def render(party: str, number: int, branches: List[int], style: Dict[str, Any]) -> str:
    """한 증거의 표기를 style에 따라 만든다. style: space(갑 제 사이 공백), je(제 유무), range_word, sep, branch_space."""
    sp = " " if style.get("space", True) else ""
    je = "제" if style.get("je", True) else ""
    shown = {"피고인증": "피고인 증", "검증": "검 증"}.get(party, party)
    suffix = "호" if style.get("bare_ho") and party in CRIMINAL_PARTIES else "호증"
    text = f"{shown}{sp}{je}{number}{suffix}"
    if branches:
        bs = " " if style.get("branch_space", True) else ""
        contiguous = branches == list(range(branches[0], branches[-1] + 1))
        if contiguous and len(branches) >= 3 and style.get("use_range", True):
            body = f"{branches[0]}{bs}{style.get('range_word', '내지')}{bs}{branches[-1]}"
        else:
            body = style.get("sep", ", ").join(str(b) for b in branches)
        text += f"의{bs}{body}"
    return text
