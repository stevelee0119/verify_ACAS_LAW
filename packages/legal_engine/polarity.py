"""법리 주장 문장의 극성 판별: 작성자 자신의 단정인가, 부정·전달·가정인가(v5 3-2).

법리 규칙은 '작성자가 이런 명제를 주장한다'를 전제로 판정한다. 같은 명제라도 다음 경우는 작성자의 주장이 아니므로
그 규칙으로 판정하지 않는다.

- 부정(NEGATED): 명제 바로 뒤 같은 절에서 부정한다. '위헌심사의 대상이 아니라고', '언제나 무효인 것은 아니다',
  '적용되지 않는다고 볼 수 없다'(부정 두 번은 긍정으로 되돌린다).
- 전달(REPORTED): 명제를 판례·결정이나 상대방의 말로 옮긴다.
  · 판례·결정: 법원·헌법재판소 등이 그렇게 '보았다/판시하였다'는 서술. 이때는 판례를 특정하는 인용(사건번호·선고)이
    이 문장이나 앞 문장에 있어야 전달로 본다. 특정한 판례가 없으면 '법원이 그렇게 본다'는 작성자의 주장이다.
  · 상대방 주장: '~라고 주장하나(하지만·하였으나)', '~라는 피고의 주장은 이유 없다'처럼 반박하려고 옮긴 경우.
- 가정(CONDITIONAL): '설령·가사·만약 ~라 하더라도/라면'처럼 가정으로 든 경우.

판별은 규칙이 맞힌 부분(trigger) 뒤의 글만 본다. 규칙 문형 안의 부정('적용되지 않는다' 자체)은 명제의 일부다.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

ASSERTED, NEGATED, REPORTED, CONDITIONAL = "ASSERTED", "NEGATED", "REPORTED", "CONDITIONAL"

# 같은 절의 끝: 연결 어미·쉼표. '라고/다고'는 절을 끊지 않는다(전달·부정이 그 뒤에 온다).
CLAUSE_BREAK_RE = re.compile(r"(?:으므로|므로|기\s*때문|으며|며(?=\s)|지만|는데|어서|아서|,|;|\.|\n)")
NEGATION_RE = re.compile(
    r"아니(?:다|라|며|고|므로|어서|었|기|한다|하다|하고|하였|함|오|며|지|에요)|아닙|아님|아닐|"
    r"(?:지|하지|되지|치|하지는|되지는|지는)\s*(?:않|아니하|못하)|"
    r"(?:할|볼|될|인정할|인정될|단정할|말할|해석할|이해할)\s*수\s*(?:는|도)?\s*없|"
    r"(?:불가(?:능)?(?:하|라|이))|(?:부정(?:하였|했|된|되|한다|하는))|(?:결코|전혀)\s")
COURT_SUBJECT_RE = re.compile(r"(?:대법원|헌법재판소|헌재|법원|원심|판례|다수의견|반대의견|별개의견|전원합의체|결정례|학설|통설|판결)")
REPORT_VERB_RE = re.compile(
    r"(?:라고|다고|라는|다는|는|고)\s*(?:취지로|취지를)?\s*(?:판시|보았|보고|본다|판단하였|판단했|판단한|설시|밝혔|밝히|결정하였|"
    r"결정했|해석하였|해석했|설명하였|설명했)|판시(?:하였|했|한\s*바|한다|하고)|취지로\s*판단")
CASE_CITE_RE = re.compile(r"(?:19|20)?\d{2}\s*(?:헌[가-힣]|[가-힣]{1,3})\s*\d{2,6}|선고|결정\s*\(|판결\s*\(")
OPPONENT_REPORT_RE = re.compile(
    r"(?:라고|다고|라는|다는|는|고)\s*(?:취지로\s*)?(?:주장|항변|다투)(?:하나|하지만|하였으나|하였지만|하는데|하고\s*있으나|"
    r"합니다만|하였는바|하는바|하나,)|"
    r"(?:라는|다는)\s*(?:[가-힣]+(?:의|측의)\s*)?(?:주장|항변)(?:은|는)\s*(?:이유\s*없|받아들일\s*수\s*없|부당|失当|잘못|근거\s*없)")
CONDITIONAL_LEAD_RE = re.compile(r"(?:설령|설사|가사|가령|만약|만일|혹시)\s")
CONDITIONAL_TAIL_RE = re.compile(r"(?:하더라도|더라도|이라도|라도|라면|이라면|다면|한다면|된다면|하면)(?:\s|,|$)")


def _clause_after(sentence: str, end: int) -> str:
    rest = sentence[end:]
    stop = CLAUSE_BREAK_RE.search(rest)
    return rest[:stop.start()] if stop else rest


def polarity(sentence: str, span: Tuple[int, int], *, previous: str = "") -> str:
    """sentence에서 span(규칙이 맞힌 부분)이 작성자의 단정인지 판별한다."""
    start, end = span
    clause = _clause_after(sentence, end)
    negations = len(NEGATION_RE.findall(clause))
    if negations % 2 == 1:
        return NEGATED
    rest = sentence[end:]
    if OPPONENT_REPORT_RE.search(rest):
        return REPORTED
    if REPORT_VERB_RE.search(rest) and COURT_SUBJECT_RE.search(sentence[:start] + " " + rest) and (
            CASE_CITE_RE.search(sentence) or CASE_CITE_RE.search(previous or "")):
        return REPORTED
    if CONDITIONAL_LEAD_RE.search(sentence[:start]) and CONDITIONAL_TAIL_RE.search(clause + " "):
        return CONDITIONAL
    return ASSERTED


def _shortest(pattern: "re.Pattern[str]") -> "re.Pattern[str]":
    """범위 수량자({m,n})를 최소 일치로 바꾼 같은 문형. 규칙 문형이 쉼표 너머 뒤 절까지 삼켜('…라고 주장하나, 하자는
    중대하고 명백') 전달 표현을 명제 안으로 넣는 것을 막는다. 일치 여부는 원래 문형으로 이미 정했다."""
    return re.compile(re.sub(r"(\{\d*,\d*\})(?!\?)", r"\1?", pattern.pattern), pattern.flags)


def asserted(sentence: str, pattern: "re.Pattern[str]", *, previous: str = "", after: Optional[re.Pattern] = None) -> bool:
    """pattern이 맞힌 명제를 작성자가 단정했는가. after가 있으면 pattern 뒤 after 맞힘 끝까지를 명제로 본다."""
    match = _shortest(pattern).search(sentence) or pattern.search(sentence)
    if not match:
        return False
    end = match.end()
    if after is not None:
        tail = after.search(sentence, match.start())
        if tail:
            end = max(end, tail.end())
    return polarity(sentence, (match.start(), end), previous=previous) == ASSERTED
