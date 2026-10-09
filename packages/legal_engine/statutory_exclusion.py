"""Clause-scoped review candidates for unsupported exclusion of statutory rules.

This recognizes the writer's argument, not the legal validity of an exception.
An identified exception with an asserted application and authority is left to
the existing legal verification flow rather than treated as a categorical claim.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache

from packages.document_engine.reading_text import QUOTE_SPAN_RE

from .legal_rules import _REQUIREMENT_CLAUSE_END_RE
from .polarity import ASSERTED, polarity


TARGET_RE = re.compile(
    r"소멸\s*시효|제척\s*기간|제소\s*기간|불변\s*기간|법정\s*기간|"
    r"(?:법률상|법률이\s*정한|법정)\s*(?:성립\s*)?요건|"
    r"(?:면책|책임\s*한도|한도)\s*규정"
)
TARGET_ROLE_RE = re.compile(
    r"\s*(?:규정|제도)?\s*(?:의\s*적용)?\s*[이가은는을를](?=\s|$)"
)
ARGUMENT_RE = re.compile(r"(?<![가-힣])[가-힣]+[이가은는을를](?=\s|$)")
GROUND_RE = re.compile(
    r"(?P<equity>정의|형평|자연법|인도주의)(?:적|의)?"
    r"(?:\s*(?:정의|형평|원칙|이념|정신|실현))?\s*(?:에|을|를)|"
    r"(?P<analogy>유추|준용|준하)|(?P<higher>상위\s*규범|헌법)(?:상|의|적|에)?"
)
EXCLUSION_RE = re.compile(
    r"적용(?:이|은|도)?\s*(?:"
    r"되지\s*(?:않(?:아야|는다|습니다|는|을)?|아니하(?:여야|는|다)?)|"
    r"될\s*수\s*없(?:다|습니다|는)?|"
    r"(?:되어서는|해서는)\s*안\s*된(?:다|다는)?|불가(?:하다|합니다)?)|"
    r"배제(?:되어야|된다|됩니다|되었다|되는|하여야|해야|한다|합니다|하라|"
    r"하여\s*(?:달라|주시기|주십시오)|하여)"
)
LINK_RE = re.compile(r"(?:으므로|므로|기에|하여|어서|따라|비추어|준하여)\s*[,;]?\s*$")
CONDITION_RE = re.compile(
    r"(?:되|하|있|없|않)(?:면|다면)(?=\s|[,;]|$)|"
    r"(?:다면|라면)(?=\s|[,;]|$)|(?:한|는|인|할)\s*(?:경우|때)(?=\s|[,;]|$)"
)
EXCEPTION_RE = re.compile(
    r"시효(?:의)?\s*(?:중단|정지)|기간(?:의)?\s*(?:연장|유예)|"
    r"(?:법정|법률상|법률이\s*정한)\s*(?:예외|특례|배제\s*사유)|위헌\s*결정"
)
FULFILMENT_RE = re.compile(
    r"(?:사유|요건|예외|특례)(?:에|을|를|이|가)?\s*(?:해당|충족|성립|인정)|"
    r"(?:중단|정지|연장|유예)(?:되었|됐다|되므로|된다|됩니다)|"
    r"위헌\s*결정(?:을|이)?\s*(?:받았|있|선고)"
)
REPORT_RE = re.compile(
    r"(?:라고|다고|라는|다는|고)\s*(?:[가-힣]+(?:의|측의)?\s+)?(?:주장|항변|견해|설명)"
)


@dataclass(frozen=True)
class ExclusionClause:
    start: int
    end: int
    target: str
    ground: str


def _clauses(sentence: str):
    start = 0
    predicates = [m.span() for m in EXCLUSION_RE.finditer(sentence)]
    predicate_index = 0
    for boundary in _REQUIREMENT_CLAUSE_END_RE.finditer(sentence):
        while predicate_index < len(predicates) and predicates[predicate_index][1] <= boundary.end():
            predicate_index += 1
        if (predicate_index < len(predicates)
                and predicates[predicate_index][0] < boundary.end()):
            continue  # Keep a modal/request predicate together, including -하여 달라.
        if not sentence[start:boundary.end()].strip(" \t\r\n,;.!?"):
            continue
        yield start, boundary.end()
        start = boundary.end()
    if start < len(sentence):
        yield start, len(sentence)


@lru_cache(maxsize=256)
def _exclusion_clauses_cached(sentence: str, previous: str = "", cited: bool = False):
    """Find conclusion spans whose statutory target and rationale are linked.

    Only causal/instrumental predecessor clauses carry a target or rationale
    forward. A previous sentence must already have been linked by the caller.
    Negation/reporting is tested after the entire exclusion proposition, so an
    application prohibition is not mistaken for a denial of that prohibition.
    """
    if not TARGET_RE.search(sentence) or not EXCLUSION_RE.search(sentence):
        return []
    clauses = list(_clauses(sentence))
    quote_view = sentence.translate(str.maketrans({"‘": "“", "’": "”", "'": '"'}))
    quotes = [q.span() for q in QUOTE_SPAN_RE.finditer(quote_view)]
    out = []
    for index, (start, end) in enumerate(clauses):
        clause = sentence[start:end]
        predicate = EXCLUSION_RE.search(clause)
        if not predicate:
            continue
        predicate_span = (start + predicate.start(), start + predicate.end())
        if any(left <= predicate_span[0] < right for left, right in quotes):
            continue
        if polarity(sentence, predicate_span, previous=previous) != ASSERTED:
            continue
        if REPORT_RE.search(sentence[predicate_span[1]:end]):
            continue
        unit_start = start
        for left, right in reversed(clauses[:index]):
            if not LINK_RE.search(sentence[left:right]):
                break
            unit_start = left
        unit = sentence[unit_start:predicate_span[1]]
        context = previous + " " + unit if previous else unit
        if CONDITION_RE.search(context):
            continue
        targets = []
        # ARGUMENT_RE used to be scanned from every target to the end of a
        # long clause.  A long synthetic sentence with repeated targets made
        # that quadratic.  Build the argument positions once and answer each
        # target's suffix query with a binary search; the rule and spans stay
        # unchanged.
        argument_matches = list(ARGUMENT_RE.finditer(unit))
        argument_starts = [match.start() for match in argument_matches]
        end_limit = len(unit) - len(predicate.group())
        usable_arguments = [match for match in argument_matches if match.start() < end_limit]
        suffix_has_other = [False] * (len(usable_arguments) + 1)
        for argument_index in range(len(usable_arguments) - 1, -1, -1):
            suffix_has_other[argument_index] = (
                suffix_has_other[argument_index + 1]
                or usable_arguments[argument_index].group()[:-1] != "적용"
            )
        for target in TARGET_RE.finditer(unit):
            role = TARGET_ROLE_RE.match(unit, target.end())
            if not role:
                continue
            argument_index = bisect_left(argument_starts, role.end())
            if argument_index < len(usable_arguments) and suffix_has_other[argument_index]:
                continue
            targets.append(target)
        grounds = list(GROUND_RE.finditer(context))
        if not targets or not grounds:
            continue
        # An exception name or citation alone cannot establish its application.
        exception = EXCEPTION_RE.search(context)
        fulfilled = FULFILMENT_RE.search(context)
        if (cited and exception and fulfilled
                and polarity(context, fulfilled.span()) == ASSERTED):
            # Prescription interruptions cannot justify a different time limit.
            if "시효" not in exception.group() or "시효" in targets[-1].group():
                continue
        ground = grounds[-1]
        # Include an inherited grammatical subject in the evidence span, rather
        # than emitting only the subjectless final clause ("its application...").
        trimmed = len(clause) - len(clause.lstrip())
        excerpt_start = min(start + trimmed, unit_start + targets[-1].start())
        out.append(ExclusionClause(excerpt_start, end, targets[-1].group(), ground.lastgroup))
    return out


def exclusion_clauses(sentence: str, previous: str = "", *, cited: bool = False):
    """Return a fresh result list while caching repeated deterministic inputs."""
    return list(_exclusion_clauses_cached(sentence, previous, cited))
