"""Clause-scoped review candidates for unsupported exclusion of statutory rules.

This recognizes the writer's argument, not the legal validity of an exception.
An identified exception with an asserted application and authority is left to
the existing legal verification flow rather than treated as a categorical claim.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache

from packages.document_engine.reading_text import QUOTE_SPAN_RE

from .legal_rules import _REQUIREMENT_CLAUSE_END_RE
from .polarity import (ASSERTED, polarity, CLAUSE_BREAK_RE, NEGATION_RE, OPPONENT_REPORT_RE,
                       REPORT_VERB_RE, COURT_SUBJECT_RE, CASE_CITE_RE, CONDITIONAL_LEAD_RE, CONDITIONAL_TAIL_RE)


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


class _Matches:
    """One full-text scan; range queries do not rescan prefixes or suffixes."""
    def __init__(self, regex, text, *, enabled=True):
        self.regex, self.text = regex, text
        self.matches = list(regex.finditer(text)) if enabled else []
        self.starts = [match.start() for match in self.matches]
        self.ends = [match.end() for match in self.matches]

    def first(self, start=0, end=None):
        index = bisect_left(self.starts, start)
        if index > 0 and self.ends[index - 1] > start:
            overlap = self.regex.search(self.text, start, self.ends[index - 1] if end is None else min(end, self.ends[index - 1]))
            if overlap:
                return overlap
        if index < len(self.matches) and (end is None or self.ends[index] <= end):
            return self.matches[index]
        return None

    def last(self, start, end):
        index = bisect_right(self.ends, end) - 1
        if index >= 0 and self.starts[index] >= start:
            return self.matches[index]
        return None

    def count(self, start, end):
        return max(0, bisect_right(self.ends, end) - bisect_left(self.starts, start))


class _PolarityIndex:
    def __init__(self, text, previous=""):
        self.previous_cited = bool(CASE_CITE_RE.search(previous))
        self.breaks = _Matches(CLAUSE_BREAK_RE, text)
        self.negations = _Matches(NEGATION_RE, text)
        self.opponent = _Matches(OPPONENT_REPORT_RE, text)
        self.report = _Matches(REPORT_VERB_RE, text)
        self.court = _Matches(COURT_SUBJECT_RE, text, enabled=bool(self.report.matches))
        self.citation = _Matches(CASE_CITE_RE, text, enabled=bool(self.report.matches))
        self.lead = _Matches(CONDITIONAL_LEAD_RE, text)
        self.tail = _Matches(CONDITIONAL_TAIL_RE, text + " ")
        self.length = len(text)

    def asserted(self, start, end, *, left=0, right=None, previous=""):
        right = self.length if right is None else right
        stop = self.breaks.first(end, right)
        clause_end = stop.start() if stop else right
        if self.negations.count(end, clause_end) % 2:
            return False
        if self.opponent.first(end, right):
            return False
        if (self.report.first(end, right)
                and (self.court.first(left, start) or self.court.first(end, right))
                and (self.citation.first(left, right) or self.previous_cited)):
            return False
        if self.lead.first(left, start) and self.tail.first(end, clause_end + 1):
            return False
        return True


@lru_cache(maxsize=256)
def _exclusion_clauses_cached(sentence: str, previous: str = "", cited: bool = False):
    """Compute sentence features once and query each causal conclusion by position."""
    if not TARGET_RE.search(sentence) or not EXCLUSION_RE.search(sentence):
        return []
    clauses = list(_clauses(sentence))
    quote_view = sentence.translate(str.maketrans({"‘": "“", "’": "”", "'": '"'})) if any(char in sentence for char in ("‘", "’", "'")) else sentence
    quotes = _Matches(QUOTE_SPAN_RE, quote_view)
    predicates = _Matches(EXCLUSION_RE, sentence)
    polarities = _PolarityIndex(sentence, previous)
    reports = _Matches(REPORT_RE, sentence)
    conditions = _Matches(CONDITION_RE, sentence)
    grounds = _Matches(GROUND_RE, sentence)
    exceptions = _Matches(EXCEPTION_RE, sentence)
    fulfilments = _Matches(FULFILMENT_RE, sentence)
    arguments = list(ARGUMENT_RE.finditer(sentence))
    other_arguments = [match.start() for match in arguments if match.group()[:-1] != "적용"]
    targets = []
    for target in TARGET_RE.finditer(sentence):
        role = TARGET_ROLE_RE.match(sentence, target.end())
        if role:
            targets.append((target, role.end()))
    target_ends = [role_end for _target, role_end in targets]
    target_starts = [target.start() for target, _role_end in targets]
    previous_condition = bool(CONDITION_RE.search(previous))
    previous_ground = list(GROUND_RE.finditer(previous))
    previous_exception = EXCEPTION_RE.search(previous)
    previous_fulfilment = FULFILMENT_RE.search(previous)
    previous_exception_asserted = bool(previous_fulfilment and polarity(previous, previous_fulfilment.span()) == ASSERTED)
    out = []
    unit_start = 0
    for index, (start, end) in enumerate(clauses):
        if index == 0 or not LINK_RE.search(sentence[clauses[index - 1][0]:start]):
            unit_start = start
        predicate = predicates.first(start, end)
        if not predicate:
            continue
        quote_index = bisect_right(quotes.starts, predicate.start()) - 1
        if quote_index >= 0 and predicate.start() < quotes.ends[quote_index]:
            continue
        if not polarities.asserted(predicate.start(), predicate.end(), previous=previous):
            continue
        if reports.first(predicate.end(), end):
            continue
        if previous_condition or conditions.first(unit_start, predicate.end()):
            continue
        target_index = bisect_right(target_starts, predicate.end()) - 1
        if target_index < 0:
            continue
        target, role_end = targets[target_index]
        if target.start() < unit_start or target.end() > predicate.end():
            continue
        argument_index = bisect_left(other_arguments, predicate.start()) - 1
        if argument_index >= 0 and other_arguments[argument_index] >= max(unit_start, role_end):
            continue
        ground = grounds.last(unit_start, predicate.end())
        if ground is None and previous_ground:
            ground = previous_ground[-1]
        if ground is None:
            continue
        exception = previous_exception or exceptions.first(unit_start, predicate.end())
        fulfilled = previous_fulfilment or fulfilments.first(unit_start, predicate.end())
        if cited and exception and fulfilled:
            if previous_fulfilment:
                # Previous is normally one linked sentence; inspect it once.
                exception_asserted = previous_exception_asserted
            else:
                exception_asserted = polarities.asserted(fulfilled.start(), fulfilled.end(),
                                                         left=unit_start, right=predicate.end(), previous=previous)
            if exception_asserted and ("시효" not in exception.group() or "시효" in target.group()):
                continue
        trimmed_start = start
        while trimmed_start < end and sentence[trimmed_start].isspace():
            trimmed_start += 1
        out.append(ExclusionClause(min(trimmed_start, target.start()), end, target.group(), ground.lastgroup))
    return out


def exclusion_clauses(sentence: str, previous: str = "", *, cited: bool = False):
    """Return a fresh result list while caching repeated deterministic inputs."""
    return list(_exclusion_clauses_cached(sentence, previous, cited))
