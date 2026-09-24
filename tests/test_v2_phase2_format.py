"""v2 Phase 2: 공식 DB와 무관하게 형식상 성립할 수 없는 인용을 확정 판정한다."""
from __future__ import annotations

from datetime import date

import pytest

from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.citation_format import format_violations

TODAY = date(2026, 9, 24)


def rules(text, **kwargs):
    [citation] = [c for c in extract_from_text(text) if c.case_number or c.decision_date]
    return [v["rule_id"] for v in format_violations(citation, today=TODAY, **kwargs)]


@pytest.mark.parametrize("text", [
    "대법원 2019. 2. 30. 선고 2018두47215 판결",        # 2월 30일
    "대법원 2023. 2. 29. 선고 2022두1 판결",            # 평년 2월 29일
    "헌법재판소 2021. 11. 31. 2020헌마1127 결정",        # 11월 31일
    "국방부 법무관리관실 2025. 4. 31.자 유권해석",        # 해석례·공문 날짜
])
def test_dates_not_on_the_calendar_are_invalid(text):
    assert rules(text) == ["FMT.DATE_NOT_ON_CALENDAR"]


def test_leap_day_in_a_leap_year_is_valid():
    assert rules("대법원 2020. 2. 29. 선고 2019두1 판결") == []


def test_decision_before_filing_year_and_future_dates():
    assert rules("대법원 2016. 5. 12. 선고 2017두11111 판결") == ["FMT.DECIDED_BEFORE_FILED"]
    assert rules("대법원 2027. 1. 5. 선고 2027두1 판결") == ["FMT.FUTURE_DATE", "FMT.FUTURE_CASE_YEAR"]


def test_plausible_but_unfound_case_is_not_a_format_error():
    # 조회되지 않을 뿐 형식상 성립 가능한 인용은 NOT_FOUND로 남아야 한다(INVALID가 아니다).
    assert rules("대법원 2022. 9. 29. 선고 2021두62148 판결") == []
    assert rules("대법원 1995. 7. 11. 선고 94누4615 전원합의체 판결") == []


def test_clock_rules_yield_to_a_confirming_official_record():
    record = {"case_number": "2027두1", "decision_date": "2027-01-05"}
    assert rules("대법원 2027. 1. 5. 선고 2027두1 판결", official_record=record) == []
    assert rules("대법원 2019. 2. 30. 선고 2018두47215 판결",
                 official_record={"decision_date": "2019-02-28"}) == ["FMT.DATE_NOT_ON_CALENDAR"]


def test_split_case_number_is_normalized():
    [citation] = extract_from_text("대법원 2019. 2. 28. 선고 2018두 47215 판결")
    assert citation.canonical_case_number == "2018두47215"
