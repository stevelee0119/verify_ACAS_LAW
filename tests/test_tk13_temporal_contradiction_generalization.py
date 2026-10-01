"""TK-13 P5-b 시점(처분시법·계약시법) 모순 일반화 단위 테스트.

양성 5건(표현·서식·어순이 다른 처분시법 및 계약시법 소급적용 모순),
대조군 3건(처분 전 개정 법령 원용, 행위 당시 구법 원용, 계약 당시 법령 변론)을 검증한다.
"""
from __future__ import annotations

import pytest

from packages.legal_engine.temporal_review import (
    document_reference_date,
    review_declared_amendments,
)
from packages.common.enums import FindingType, VerificationStatus


# --- 양성 예시 (5건) ---
POSITIVE_CASES = [
    (
        "enforced-wording",
        "피고는 2024. 5. 3. 원고에 대하여 해임처분을 하였다.\n"
        "2025. 9. 1. 대통령령 제36120호로 개정·시행된 「군인징계령」 제9조 제2항 단서에 따라 자진 변제한 경우 "
        "반드시 감경하여야 하므로, 피고는 위 개정 규정을 적용하여야 함에도 이를 배제한 채 해임하였으므로 위법하다.\n",
        "개정·시행 표현 및 처분 후 시행 조항 소급적용 주장",
    ),
    (
        "no-decree-number",
        "피고는 2024. 5. 3. 원고에 대하여 해임처분을 하였다.\n"
        "2025. 9. 1. 개정된 「군인징계령」 제9조 제2항 단서의 감경 규정을 적용하여야 하는데도 피고는 이를 적용하지 않았다.\n",
        "호수 없는 개정 법령 소급적용 주장",
    ),
    (
        "reordered-sentence",
        "피고는 2024. 5. 3. 원고에 대하여 해임처분을 하였다.\n"
        "피고는 해임처분을 하면서, 2025년 9월 1일 시행된 「군인징계령」 제9조 제2항 단서(자진 변제 시 감경)를 적용하지 않았다. "
        "이는 신법 우선 원칙 위반이다.\n",
        "어순 바뀐 문장의 개정 법령 소급적용 주장",
    ),
    (
        "disposition-date-label",
        "해임처분일: 2024년 5월 3일\n"
        "2025. 9. 1. 개정·공포된 「군인징계령」 제9조 제2항 단서를 적용해야 한다.\n",
        "처분일 라벨 표기 및 처분 후 공포 법령 소급적용 주장",
    ),
    (
        "contract-delay-amendment",
        "원고는 2023년 5월 30일 피고와 조달계약(납기일: 2023년 12월 31일)을 체결하였습니다.\n"
        "2025년 1월 1일 기획재정부령 제990호로 개정 시행된 「국가를 당사자로 하는 계약에 관한 법률 시행규칙」 제75조 제2항 "
        "단서에 따라 소급 감면이 이루어져야 합니다.\n",
        "계약체결 및 납기일 이후 개정된 시행규칙 소급적용 주장",
    ),
]

# --- 대조군 예시 (3건) ---
CONTROL_CASES = [
    (
        "amendment-before-disposition",
        "피고는 2025. 9. 1. 원고에 대하여 해임처분을 하였다.\n"
        "2024. 3. 1. 개정·공포된 「군인징계령」 제9조 제2항 단서에 따라 감경 여부를 검토하여야 한다.\n",
        "처분 전 개정된 법령의 정상 적용 변론",
    ),
    (
        "old-law-defence",
        "피고는 2024. 5. 3. 원고에 대하여 해임처분을 하였다.\n"
        "원고의 비위는 행위 당시의 법령에 의하여 판단하여야 하므로 개정 전 「군인징계령」 제9조가 적용된다고 본다.\n",
        "행위시법·구법 적용 원용 정상 변론",
    ),
    (
        "contract-prior-law-defence",
        "원고는 2023년 5월 30일 조달계약을 체결하였습니다.\n"
        "계약 체결 당시 유효한 법령에 따라 당사자의 의무를 이행하여야 합니다.\n",
        "계약 당시 법령 준수 정상 변론",
    ),
]


@pytest.mark.parametrize("case_id, text, desc", POSITIVE_CASES)
def test_positive_temporal_contradictions(case_id, text, desc):
    """시점 모순(기준일 이후 개정 법령 소급적용)이 정상적으로 탐지되어야 한다."""
    ref = document_reference_date(text, criminal=False)
    assert ref.get("date") is not None, f"[{case_id}] {desc}: 기준일 추출 실패: {ref}"
    findings = review_declared_amendments(text, ref, criminal=False)
    assert len(findings) >= 1, f"[{case_id}] {desc}: 시점 모순 finding 미생성"
    assert findings[0].type == FindingType.TEMPORAL_LAW_MISMATCH
    assert findings[0].status in (VerificationStatus.SUSPICIOUS, VerificationStatus.CONTRADICTED)


@pytest.mark.parametrize("case_id, text, desc", CONTROL_CASES)
def test_control_temporal_cases_no_false_positive(case_id, text, desc):
    """정상 시점 변론 및 구법 적용 주장은 시점 모순으로 오탐되지 않아야 한다."""
    ref = document_reference_date(text, criminal=False)
    findings = review_declared_amendments(text, ref, criminal=False)
    assert len(findings) == 0, f"[{case_id}] {desc}: 오탐 finding 생성: {findings}"
