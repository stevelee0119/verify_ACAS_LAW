"""TK-19 2절: 활력징후 측정 시점 군(timing_groups) 기반 대조 단위 테스트 (Q2).

- 같은 시점 군(INITIAL_VISIT: 초진·내원·도착 등) 또는 한쪽에만 라벨이 있는 경우는 불일치(CONTRADICTS) 탐지
- 서로 다른 시점 군(TRANSPORT vs INITIAL_VISIT, SURGERY vs DISCHARGE 등) 또는 일반 정의 문장은 배제
"""

import pytest
from packages.rag_engine.exhibit_facts import _check_vital_measurements


# 양성 예시 5건: 같은 시점 군 또는 한쪽만 라벨 -> 불일치 관찰 생성
POSITIVE_CASES = [
    (
        "same-group-initial-visit",
        "원고의 내원 당시 혈압은 190/110 mmHg로 위급한 상태였습니다.",
        "초진 기록: 환자의 혈압 125/80 mmHg로 안정적임.",
    ),
    (
        "same-group-arrival-initial",
        "응급실 도착 당시 혈압은 200/120 mmHg로 측정되었습니다.",
        "초진시 활력징후: 혈압 130/80 mmHg 유지 중.",
    ),
    (
        "one-sided-label",
        "환자의 혈압은 210/120 mmHg였습니다.",
        "내원시 간호기록: 혈압 135/85 mmHg로 측정됨.",
    ),
    (
        "same-group-surgery-anesthesia",
        "수술중 혈압이 70/40 mmHg로 급격히 저하되었습니다.",
        "마취 기록지: 수축기/이완기 혈압 120/80 mmHg 유지됨.",
    ),
    (
        "same-group-transport",
        "119 구급차 이송중 혈압은 80/50 mmHg였습니다.",
        "후송 당시 구급일지: 혈압 130/85 mmHg로 양호하였음.",
    ),
]

# 대조군 3건: 서로 다른 시점 군 또는 일반 정의 문장 -> 관찰 생성 배제
CONTROL_CASES = [
    (
        "different-groups-surgery-vs-discharge",
        "수술중 혈압은 180/100 mmHg로 상승하였습니다.",
        "퇴원시 혈압 기록: 120/80 mmHg로 정상 회복됨.",
    ),
    (
        "different-groups-transport-vs-arrival",
        "이송도중 혈압은 90/60 mmHg였습니다.",
        "병원 도착후 혈압: 140/90 mmHg로 측정됨.",
    ),
    (
        "general-medical-definition",
        "수축기 혈압 140/90 mmHg 이상인 경우를 고혈압이라 정의한다.",
        "초진 혈압 120/80 mmHg 정상.",
    ),
]


@pytest.mark.parametrize("case_id, doc_text, src_text", POSITIVE_CASES)
def test_vital_measurements_same_group_contradiction_detected(case_id, doc_text, src_text):
    """같은 시점 군 내의 수치 불일치나 한쪽만 라벨이 있는 경우 모순이 정상 적발되는지 검증한다."""
    obs = _check_vital_measurements(doc_text, src_text, "R1")
    assert obs is not None, f"[{case_id}] 불일치 관찰이 생성되지 않았습니다."
    assert obs["relationship"] == "CONTRADICTS"


@pytest.mark.parametrize("case_id, doc_text, src_text", CONTROL_CASES)
def test_vital_measurements_different_groups_or_definition_excluded(case_id, doc_text, src_text):
    """서로 다른 시점 군이거나 일반 정의 문장인 경우 오탐 없이 정상 배제되는지 검증한다."""
    obs = _check_vital_measurements(doc_text, src_text, "R1")
    assert obs is None, f"[{case_id}] 서로 다른 시점 또는 정의 문장에서 오탐이 발생했습니다: {obs}"
