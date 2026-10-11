"""Bounded, source-grounded aspect senses independent of legal vocabulary.

These senses describe the predicate, not legal sufficiency or truth of a fact.
Aspect labels and frames are application mappings, not NIKL categories.
An observed accusative frame can exclude an intransitive sense. It cannot
choose between multiple transitive senses by recognizing a legal noun.
"""
from __future__ import annotations

import re
from urllib.parse import quote

VERSION = "krdict-aspect-1"
_SOURCE = "https://krdict.korean.go.kr/m/kor/searchResult?mainSearchWord="

# Independent public source records. Composite source-sense keys identify
# lemma/homonym/sense; they are not invented official numeric entry IDs.
_SOURCE_SENSES = (
    ("완료하다", 0, "完了", 1, "완전히 끝마치다."),
    ("완수하다", 0, "完遂", 1, "하고자 하는 것이나 해야 하는 것을 다 이루거나 해내다."),
    ("완결하다", 0, "完結", 1, "완전하게 끝을 맺다."),
    ("끝마치다", 0, "", 1, "일이나 말을 끝내다."),
    ("마치다", 0, "", 1, "하던 일이나 과정이 끝나다. 또는 그렇게 하다."),
    ("끝내다", 0, "", 1, "일을 마지막까지 이루다."),
    ("끝내다", 0, "", 2, "정해진 기간을 모두 보내다."),
    ("끝내다", 0, "", 3, "관계를 끊다."),
    ("이행하다", 2, "履行", 1, "약속이나 계약 등을 실제로 행하다."),
    ("이행하다", 1, "移行", 1, "사회나 현상 등이 다른 상태로 변해 가다."),
    ("수행하다", 2, "遂行", 1, "일을 생각하거나 계획한 대로 해내다."),
    ("수행하다", 1, "修行", 1, "몸과 마음을 바르게 갈고 닦다."),
    ("수행하다", 1, "修行", 2, "불교에서, 부처의 가르침을 실천하고 도를 닦다."),
    ("수행하다", 3, "隨行", 1, "일정한 임무를 띠고 높은 지위를 가진 사람을 따라다니다."),
    ("수행하다", 3, "隨行", 2, "다른 사람의 뜻이나 지시에 따라서 행동하다."),
    ("실행하다", 0, "實行", 1, "실제로 행하다."),
    ("실행하다", 0, "實行", 2, "컴퓨터 프로그램을 작동시키다."),
    ("중단하다", 0, "中斷", 1, "어떤 일을 중간에 멈추거나 그만두다."),
    ("포기하다", 0, "抛棄", 1, "하려던 일이나 생각을 중간에 그만두다."),
    ("포기하다", 0, "抛棄", 2, "자기의 권리나 자격, 소유한 물건 등을 버리다."),
    ("그만두다", 0, "", 1, "하던 일을 중간에 그치고 하지 않다."),
    ("그만두다", 0, "", 2, "앞으로 할 일이나 하려고 하던 일을 하지 않다."),
    ("연기하다", 1, "延期", 1, "정해진 시기를 뒤로 미루다."),
    ("연기하다", 2, "演技", 1, "배우가 맡은 역할에 따라 인물, 성격, 행동 등을 표현해 내다."),
    ("유예하다", 0, "猶豫", 1, "일을 실행하지 못하고 망설이다."),
    ("유예하다", 0, "猶豫", 2, "일을 실행하는 데 날짜나 시간을 미루다."),
    ("유예하다", 0, "猶豫", 3, "소송을 하거나 소송의 효력을 발생시키기 위해 일정한 기간을 두다."),
    ("계획하다", 0, "計劃/計畫", 1, "앞으로의 일을 자세히 생각하여 정하다."),
    ("준비하다", 0, "準備", 1, "미리 마련하여 갖추다."),
    ("착수하다", 0, "着手", 1, "새로운 일을 시작하다."),
    ("시작하다", 0, "始作", 1, "어떤 일이나 행동의 처음 단계를 이루거나 이루게 하다."),
    ("시작하다", 0, "始作", 2, "어떤 일이나 행동이 어떤 사건이나 장소에서 처음으로 생기다. 또는 생기게 하다."),
)
# Application mappings, explicitly separate from NIKL's definitions/classes.
# Keys are stable composites of the source's lemma, homonym and sense number.
SOURCE_SENSES = tuple({"lemma": lemma, "homonym_number": homonym,
                      "hanja": hanja, "sense_number": number, "definition": definition,
                      "source_sense_key": f"{lemma}:{homonym}:{number}",
                      "source": _SOURCE + quote(lemma), "retrieved_on": "2026-10-11"}
                     for lemma, homonym, hanja, number, definition in _SOURCE_SENSES)
ASPECT_MAPPINGS = {
    '완료하다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '완수하다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '완결하다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '끝마치다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '마치다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '끝내다:0:1': {'category': 'COMPLETION', 'frame': 'EVENT_OBJECT'},
    '끝내다:0:2': {'category': 'DURATION_END', 'frame': 'DURATION_OBJECT'},
    '끝내다:0:3': {'category': 'RELATION_END', 'frame': 'RELATION_OBJECT'},
    '이행하다:2:1': {'category': 'REALIZATION', 'frame': 'EVENT_OBJECT'},
    '이행하다:1:1': {'category': 'TRANSITION', 'frame': 'STATE_SUBJECT'},
    '수행하다:2:1': {'category': 'REALIZATION', 'frame': 'EVENT_OBJECT'},
    '수행하다:1:1': {'category': 'PRACTICE', 'frame': 'PRACTICE_FRAME'},
    '수행하다:1:2': {'category': 'PRACTICE', 'frame': 'PRACTICE_FRAME'},
    '수행하다:3:1': {'category': 'ACCOMPANIMENT', 'frame': 'PERSON_OBJECT'},
    '수행하다:3:2': {'category': 'COMPLIANCE', 'frame': 'DIRECTIVE_FRAME'},
    '실행하다:0:1': {'category': 'REALIZATION', 'frame': 'EVENT_OBJECT'},
    '실행하다:0:2': {'category': 'COMPUTATION', 'frame': 'PROGRAM_OBJECT'},
    '중단하다:0:1': {'category': 'INTERRUPTION', 'frame': 'EVENT_OBJECT'},
    '포기하다:0:1': {'category': 'ABANDONMENT', 'frame': 'EVENT_OBJECT'},
    '포기하다:0:2': {'category': 'RELINQUISHMENT', 'frame': 'RIGHT_OBJECT'},
    '그만두다:0:1': {'category': 'INTERRUPTION', 'frame': 'EVENT_OBJECT'},
    '그만두다:0:2': {'category': 'ABANDONMENT', 'frame': 'EVENT_OBJECT'},
    '연기하다:1:1': {'category': 'DEFERMENT', 'frame': 'EVENT_OBJECT'},
    '연기하다:2:1': {'category': 'ACTING', 'frame': 'ROLE_FRAME'},
    '유예하다:0:1': {'category': 'HESITATION', 'frame': 'EVENT_OBJECT'},
    '유예하다:0:2': {'category': 'DEFERMENT', 'frame': 'EVENT_OBJECT'},
    '유예하다:0:3': {'category': 'DEFERMENT', 'frame': 'PROCEDURAL_FRAME'},
    '계획하다:0:1': {'category': 'PROSPECTIVE', 'frame': 'EVENT_OBJECT'},
    '준비하다:0:1': {'category': 'PREPARATION', 'frame': 'EVENT_OBJECT'},
    '착수하다:0:1': {'category': 'INCEPTION', 'frame': 'EVENT_OBJECT'},
    '시작하다:0:1': {'category': 'INCEPTION', 'frame': 'EVENT_OBJECT'},
    '시작하다:0:2': {'category': 'INCEPTION', 'frame': 'EVENT_SUBJECT'},
}

# Degree/partitive scope is another public semantic distinction, not a list
# of legal exceptions. Matching its exact nominal/adverbial forms only blocks
# whole-requirement inference; it never declares a factual denial.
_SCOPE_ROWS = (
    ("일부", 0, "一部", 1, "한 부분. 또는 전체 중에서 얼마.", "일부"),
    ("일부분", 0, "一部分", 1, "한 부분. 또는 전체 중에서 얼마.", "일부"),
    ("부분", 0, "部分", 1, "전체를 이루고 있는 작은 범위. 또는 전체를 여러 개로 나눈 것 가운데 하나.", "부분"),
    ("부분적", 1, "部分的", 1, "전체 중 한 부분에만 관련되는 것.", "부분"),
    ("부분적", 2, "部分的", 1, "전체 중 한 부분에만 관련되는.", "부분"),
    ("절반", 0, "折半", 1, "하나를 반으로 나눔. 또는 그렇게 나눈 반.", "절반"),
    ("조금", 1, "", 1, "적은 분량이나 적은 정도.", "조금"),
    ("조금", 1, "", 2, "짧은 시간 동안.", "조금"),
    ("조금", 2, "", 1, "분량이나 정도가 적게.", "조금"),
    ("조금", 2, "", 2, "시간이 짧게.", "조금"),
)
SCOPE_SENSES = tuple({"lemma": lemma, "homonym_number": homonym, "hanja": hanja,
                     "sense_number": number, "definition": definition,
                     "source_sense_key": f"{lemma}:{homonym}:{number}",
                     "source": _SOURCE + quote(query), "retrieved_on": "2026-10-11"}
                    for lemma, homonym, hanja, number, definition, query in _SCOPE_ROWS)
_SCOPE_PATTERN = re.compile(
    r"(?<![가-힣])(?:" + "|".join(sorted({re.escape(row['lemma']) for row in SCOPE_SENSES}, key=len, reverse=True))
    + r")(?P<suffix>만|씩|을|를|이|가|으로|으로만)?(?=\s|$)"
)


def assertion_extent_evidence(text: str) -> list[dict]:
    rows = []
    for match in _SCOPE_PATTERN.finditer(text):
        lemma = match.group()[:-len(match.group('suffix'))] if match.group('suffix') else match.group()
        rows.append({"span": list(match.span()), "category": "PARTITIVE_OR_DEGREE",
                     "source_senses": [row for row in SCOPE_SENSES if row['lemma'] == lemma],
                     "mapping_authority": "APPLICATION_NOT_NIKL_CLASSIFICATION",
                     "whole_requirement_supported": False})
    return rows

_FULFILLING = {"COMPLETION", "REALIZATION"}
_PAST_ENDING = r"(?:으므로|므로|기에|습니다|다|고|으나|지만|는데)"


def _past_stems(lemma: str) -> tuple[str, ...]:
    """Regular past contractions for the attested resource's conjugations."""
    stem = lemma[:-1]
    if stem.endswith("하"):
        return stem[:-1] + "하였", stem[:-1] + "했"
    last = ord(stem[-1]) - 0xAC00
    initial, vowel, final = last // 588, (last % 588) // 28, last % 28
    forms = [stem + ("았" if vowel in {0, 8} else "었")]
    contraction = {20: 6, 13: 14, 1: 1}  # ㅣ+ㅓ→ㅕ, ㅜ+ㅓ→ㅝ, ㅐ+ㅓ→ㅐ.
    if not final and vowel in contraction:
        forms.append(stem[:-1] + chr(0xAC00 + initial * 588 + contraction[vowel] * 28 + 20))
    return tuple(forms)


_LEMMA_PATTERNS = {
    lemma: re.compile("(?:" + "|".join(map(re.escape, _past_stems(lemma))) + ")" + _PAST_ENDING)
    for lemma, *_ in _SOURCE_SENSES
}


def sense_evidence(lemma: str, *, event_object: bool = False) -> dict:
    senses = [{**source, **ASPECT_MAPPINGS[source['source_sense_key']]}
              for source in SOURCE_SENSES if source['lemma'] == lemma]
    selected = ([sense for sense in senses if sense['frame'] not in {'STATE_SUBJECT', 'EVENT_SUBJECT'}]
                if event_object else senses)
    categories = {sense['category'] for sense in selected}
    return {"version": VERSION, "lemma": lemma, "senses": senses,
            "selected_senses": selected, "observed_direct_object": event_object,
            "sense_resolved": len(selected) == 1,
            "supports_asserted_fulfillment": bool(event_object and categories and categories <= _FULFILLING),
            "mapping_authority": "APPLICATION_NOT_NIKL_CLASSIFICATION",
            "total_completion_asserted": bool(event_object and categories == {'COMPLETION'}),
            "underlying_facts_verified": False, "legal_sufficiency_verified": False}


def past_predicate_evidence(token: str, *, event_object: bool = False) -> dict | None:
    """Exact finite past tokens only; nominal mentions/plans are not assertions."""
    for lemma, pattern in _LEMMA_PATTERNS.items():
        if pattern.fullmatch(token):
            return {**sense_evidence(lemma, event_object=event_object), "tense": "PAST"}
    return None
