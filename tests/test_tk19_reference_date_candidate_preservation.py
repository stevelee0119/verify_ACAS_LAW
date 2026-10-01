"""TK-19 1절: 기준일 후보 보존 및 일반 낱말 오인 방지 단위 테스트 (Q1).

날짜 뒤에 위치한 일반 낱말('횡령', '방법', '위법', '명령', '정직하게' 등)로 인해
행위일·처분일 후보가 누락되거나 과잉 수집되지 않는지 검증한다.
- 양성 5건: 날짜 뒤 일반 행위/처분 서술이 오는 경우 기준일 후보 정상 보존
- 대조군 3건: 실제 법령 개정/시행 표지 또는 형용사/부사 용법 시 오탐 배제
"""

import pytest
from packages.legal_engine.temporal_review import reference_candidates


POSITIVE_CASES = [
    ("breach-of-trust", "피고인은 2022. 3. 15. 업무상 배임하였다.", "2022-03-15", "OFFENSE"),
    ("fraud-deceit", "피고인은 2020. 11. 20. 피해자를 기망하여 금원을 편취하였다.", "2020-11-20", "OFFENSE"),
    ("assault-injury", "피고인은 2023. 8. 5. 피해자에게 폭행을 가하였다.", "2023-08-05", "OFFENSE"),
    ("dismissal-disposition", "피고는 2024. 4. 12. 소청인에 대하여 해임처분을 의결하였다.", "2024-04-12", "DISPOSITION"),
    ("suspension-disposition", "임명권자는 2023. 10. 1. 대상자에게 정직 1월의 처분을 내렸다.", "2023-10-01", "DISPOSITION"),
]

CONTROL_CASES = [
    ("law-amendment-decree", "2025. 9. 1. 대통령령 제36120호로 개정된 규정에 따른다.", "2025-09-01"),
    ("law-enforcement-statute", "2024. 1. 1.부터 시행된 관련 법률 제19000호에 의한다.", "2024-01-01"),
    ("honest-adverb-statement", "당사자는 2021. 5. 10. 정직하게 소명서를 제출하였을 뿐이다.", "2021-05-10"),
]


@pytest.mark.parametrize("case_id, text, expected_date, expected_kind", POSITIVE_CASES)
def test_reference_candidate_preserved_for_normal_words(case_id, text, expected_date, expected_kind):
    """일반 행위 및 처분 서술의 날짜가 기준일 후보로 정상 보존되는지 검증한다."""
    cands = reference_candidates(text)
    matched = [c for c in cands if c["date"] == expected_date and c["kind"] == expected_kind]
    assert len(matched) >= 1, (
        f"[{case_id}] 날짜 '{expected_date}' (종류: {expected_kind})가 후보에서 누락되었습니다: {cands}"
    )


@pytest.mark.parametrize("case_id, text, target_date", CONTROL_CASES)
def test_law_dates_and_adverbs_not_falsely_collected_as_reference_events(case_id, text, target_date):
    """법령 개정/시행 날짜나 '정직하게' 부사는 사건 기준일(OFFENSE/DISPOSITION)로 오수집되지 않는지 검증한다."""
    cands = reference_candidates(text)
    event_cands = [c for c in cands if c["date"] == target_date and c["kind"] in ("OFFENSE", "DISPOSITION")]
    assert len(event_cands) == 0, (
        f"[{case_id}] 날짜 '{target_date}'가 사건 기준일로 오수집되었습니다: {event_cands}"
    )
