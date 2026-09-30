"""TK-08 exhibit_facts 범용 사실관계 대조 단위 테스트.

- 활력징후/혈압 대조기: 양성 3건, 대조군 3건 (오탐 재현: 지분/분수 30/100 대조군 포함)
- 과실 기여도 대조기: 양성 3건, 대조군 3건
- 기기/소프트웨어 역할 대조기: 양성 3건, 대조군 3건
- 금액 산정 대조기: 양성 3건, 대조군 3건 (오탐 재현: 임금대장 양식 안내 대조군 포함)
- 소극적 부존재 사실 대조기: 양성 3건, 대조군 3건
"""
import pytest
from packages.rag_engine.exhibit_facts import (
    _check_vital_measurements,
    _check_percentage_attribution,
    _check_classification_roles,
    _check_monetary_discrepancies,
    _check_negation_contradictions,
    check_exhibit_facts_generic,
)


# ==============================================================================
# 1. 활력징후/혈압 대조기 (양성 3건, 대조군 3건)
# ==============================================================================
def test_vital_measurements_positive():
    """혈압 측정치가 서면과 서증 간에 유의미하게 불일치하는 경우 탐지 (양성 3건)."""
    # 양성 1: 표준 혈압 표기 불일치
    doc1 = "원고의 내원 당시 혈압은 190/110 mmHg로 응급 상태였습니다."
    src1 = "초진 기록: 환자의 혈압 125/80 mmHg로 측정됨."
    obs1 = _check_vital_measurements(doc1, src1, "R1")
    assert obs1 is not None
    assert obs1["relationship"] == "CONTRADICTS"
    assert "확인 필요" in obs1["explanation"]

    # 양성 2: mmHg 없이 '혈압' 문맥 동반
    doc2 = "당시 측정한 혈압 180/105 상태에서 즉시 처치가 필요했습니다."
    src2 = "간호기록지: 혈압 수치 120/75 기록됨."
    obs2 = _check_vital_measurements(doc2, src2, "R2")
    assert obs2 is not None
    assert obs2["relationship"] == "CONTRADICTS"

    # 양성 3: 수축기/이완기 문맥 동반
    doc3 = "수축기/이완기 측정 혈압은 200/120에 달하였습니다."
    src3 = "응급실 의무기록: 내원 시 혈압 130/85 확인."
    obs3 = _check_vital_measurements(doc3, src3, "R3")
    assert obs3 is not None
    assert obs3["relationship"] == "CONTRADICTS"


def test_vital_measurements_negative_control():
    """혈압 문맥이 없는 지분/분수 또는 일치하는 혈압은 불일치로 탐지하지 않음 (대조군 3건)."""
    # 대조군 1 (오탐 재현 케이스): 부동산 공유 지분 표기 (혈압 아님)
    doc1 = "원고는 이 사건 부동산 중 공유지분이 30/100이라고 주장합니다."
    src1 = "등기사항전부증명서: 공유자 지분 50/100 기재."
    obs1 = _check_vital_measurements(doc1, src1, "R1")
    assert obs1 is None, "지분 분수 표기가 혈압으로 오탐됨"

    # 대조군 2: 일반 비율 분수 표기
    doc2 = "해당 설문 참여자 중 20/50 비율만이 찬성하였습니다."
    src2 = "조사 보고서 통계: 찬성률 35/50 집계."
    obs2 = _check_vital_measurements(doc2, src2, "R2")
    assert obs2 is None

    # 대조군 3: 혈압 수치가 서면과 서증 간에 일치하는 경우
    doc3 = "당시 환자의 혈압은 135/85 mmHg로 측정되었습니다."
    src3 = "의무기록: 내원 시 혈압 135/85 mmHg 확인."
    obs3 = _check_vital_measurements(doc3, src3, "R3")
    assert obs3 is None


# ==============================================================================
# 2. 과실 기여도 대조기 (양성 3건, 대조군 3건)
# ==============================================================================
def test_percentage_attribution_positive():
    """100% 전적인 원인 주장 vs 제한적 기여도 서증 불일치 탐지 (양성 3건)."""
    # 양성 1
    doc1 = "피고의 과실이 사고 발생의 100% 직접적이고 유일한 원인입니다."
    src1 = "사고조사 감정서: 본 건 피고의 과실 기여도는 30% 내지 40% 수준으로 평가함."
    obs1 = _check_percentage_attribution(doc1, src1, "R1")
    assert obs1 is not None
    assert obs1["relationship"] == "CONTRADICTS"

    # 양성 2
    doc2 = "상대방의 전적인 과실 100%로 인하여 피해가 발생하였습니다."
    src2 = "의료감정 회신: 기왕증 복합 작용으로 의료과실 기여율은 20%~30% 범위로 판단됨."
    obs2 = _check_percentage_attribution(doc2, src2, "R2")
    assert obs2 is not None

    # 양성 3
    doc3 = "원고는 상대방 운전자의 100% 유일한 원인에 의한 추돌이라고 주장합니다."
    src3 = "교통사고 분석서: 도로 사정 감안 시 책임 제한 비율은 50% - 60% 상당임."
    obs3 = _check_percentage_attribution(doc3, src3, "R3")
    assert obs3 is not None


def test_percentage_attribution_negative_control():
    """기여도 왜곡이 없거나 양측 주장이 부합하는 경우 (대조군 3건)."""
    # 대조군 1: 서면에서도 제한된 비율 주장
    doc1 = "원고는 피고의 과실 기여도가 약 40%에 달한다고 주장합니다."
    src1 = "감정서: 피고 과실 기여도는 30% 내지 40% 수준임."
    obs1 = _check_percentage_attribution(doc1, src1, "R1")
    assert obs1 is None

    # 대조군 2: 100% 언급이 없는 일반 주장
    doc2 = "피고의 주의의무 위반으로 사고가 유발되었습니다."
    src2 = "감정서: 기여도 40%~50% 인정."
    obs2 = _check_percentage_attribution(doc2, src2, "R2")
    assert obs2 is None

    # 대조군 3: 서증에서도 전적 과실(100%)을 인정하는 경우
    doc3 = "피고의 100% 유일한 원인에 의한 사고입니다."
    src3 = "감정서: 피고의 전적인 일방 과실 100%로 확인됨."
    obs3 = _check_percentage_attribution(doc3, src3, "R3")
    assert obs3 is None


# ==============================================================================
# 3. 기기/소프트웨어 역할 대조기 (양성 3건, 대조군 3건)
# ==============================================================================
def test_classification_roles_positive():
    """단독/독립 진단 주장 vs 진단 보조 용도 서증 불일치 탐지 (양성 3건)."""
    # 양성 1
    doc1 = "해당 소프트웨어는 독자적으로 병변을 판정하는 독립 진단기기입니다."
    src1 = "식약처 허가서: 본 제품은 의료기기 제3등급 진단보조소프트웨어입니다."
    obs1 = _check_classification_roles(doc1, src1, "R1")
    assert obs1 is not None
    assert obs1["relationship"] == "CONTRADICTS"

    # 양성 2
    doc2 = "의사의 판단을 전면 대체하여 단독 진단을 수행하는 시스템입니다."
    src2 = "제품설명서: 의료영상 분석을 통해 의사의 판단을 보조하는 용도에 한함."
    obs2 = _check_classification_roles(doc2, src2, "R2")
    assert obs2 is not None

    # 양성 3
    doc3 = "본 기기는 의료진 개입 없이 단독 진단용으로 인가되었습니다."
    src3 = "사용목적: 최종 책임은 담당 의사에게 귀속되며 진단을 보조하는 소프트웨어임."
    obs3 = _check_classification_roles(doc3, src3, "R3")
    assert obs3 is not None


def test_classification_roles_negative_control():
    """역할 왜곡이 없는 서면 및 서증 (대조군 3건)."""
    # 대조군 1: 서면도 진단보조로 정확히 기술
    doc1 = "해당 소프트웨어는 의료진의 판독을 돕는 진단 보조 도구로 사용되었습니다."
    src1 = "허가서: 의료기기 제3등급 진단보조소프트웨어."
    obs1 = _check_classification_roles(doc1, src1, "R1")
    assert obs1 is None

    # 대조군 2: 일반 의료기기 기재
    doc2 = "피고 병원은 정기 점검을 필한 초음파 기기를 사용하였습니다."
    src2 = "점검표: 제2등급 의료기기 정기 안전점검 적합."
    obs2 = _check_classification_roles(doc2, src2, "R2")
    assert obs2 is None

    # 대조군 3: 단독 진단 언급이 없는 서면
    doc3 = "영상 판독 결과에 기초하여 수술 계획을 수립하였습니다."
    src3 = "설명서: 최종 책임은 담당 의사에게 귀속됨."
    obs3 = _check_classification_roles(doc3, src3, "R3")
    assert obs3 is None


# ==============================================================================
# 4. 금액 산정 대조기 (양성 3건, 대조군 3건)
# ==============================================================================
def test_monetary_discrepancies_positive():
    """서면 주장 금액과 판정서 최종 인정 금액 불일치 탐지 (양성 3건)."""
    # 양성 1
    doc1 = "원고의 미지급 임금 상당액 1억 4,800만원을 전액 지급하여야 합니다."
    src1 = "주문: 피신청인은 신청인에게 최종 인정액 금 42,500,000원을 지급하라."
    obs1 = _check_monetary_discrepancies(doc1, src1, "R1", "지방노동위원회 구제신청 판정서")
    assert obs1 is not None
    assert obs1["relationship"] == "CONTRADICTS"

    # 양성 2
    doc2 = "판정서에 따른 손해배상액 금 80,000,000원을 청구합니다."
    src2 = "합계 (최종 인정액) 금 25,000,000원."
    obs2 = _check_monetary_discrepancies(doc2, src2, "R2", "중앙노동위원회 재심판정서")
    assert obs2 is not None

    # 양성 3
    doc3 = "미지급 임금으로 금 50,000,000원이 확정 산정되었습니다."
    src3 = "정산 내역: 최종 인정액 12,000,000원."
    obs3 = _check_monetary_discrepancies(doc3, src3, "R3", "노동위원회 결정서")
    assert obs3 is not None


def test_monetary_discrepancies_negative_control():
    """양식 안내 문서 배제 및 금액 일치 시 불일치 미탐지 (대조군 3건)."""
    # 대조군 1 (오탐 재현 케이스): '양식 안내' 참고자료는 판정이 아니므로 배제
    doc1 = "원고는 미지급 임금 상당액 3,000,000원을 청구합니다."
    src1 = "예시 서식: 기본급 및 제수당 합계 (최종 인정액) 1,000,000원."
    obs1 = _check_monetary_discrepancies(doc1, src1, "R1", "임금대장 양식 안내")
    assert obs1 is None, "양식 안내 문서가 본안 판정서 금액 불일치로 오탐됨"

    # 대조군 2: 샘플 서식 배제
    doc2 = "손해배상금 10,000,000원의 지급을 구합니다."
    src2 = "샘플: 합계 5,000,000원."
    obs2 = _check_monetary_discrepancies(doc2, src2, "R2", "구제신청서 작성요령 및 서식")
    assert obs2 is None

    # 대조군 3: 금액이 일치하는 경우
    doc3 = "지노위에서 확정된 미지급 임금 상당액 금 42,500,000원의 지급을 명합니다."
    src3 = "주문: 피신청인은 신청인에게 최종 인정액 금 42,500,000원을 지급하라."
    obs3 = _check_monetary_discrepancies(doc3, src3, "R3", "지방노동위원회 판정서")
    assert obs3 is None


# ==============================================================================
# 5. 소극적 부존재 사실 대조기 (양성 3건, 대조군 3건)
# ==============================================================================
def test_negation_contradictions_positive():
    """서증에 없는 강제 규정이나 미확인 조사 결과를 서면이 확정 주장한 경우 탐지 (양성 3건)."""
    # 양성 1: 규정상 부존재 강제조치 주장
    doc1 = "사규에 가해자 즉시 징계해고 규정이 명시되어 있습니다."
    src1 = "조항 검토: 즉시 해고 등 강제 규정은 본 복무규정에 존재하지 아니함."
    obs1 = _check_negation_contradictions(doc1, src1, "R1", "회사 취업규칙")
    assert len(obs1) > 0

    # 양성 2: 사내 조사보고서상 증거 부존재 vs 확정 주장
    doc2 = "인사위원회 조사 결과 대표이사가 부당행위를 주도·공모한 사실이 명백히 확정되었습니다."
    src2 = "조사결과: 대표이사가 지시·공모한 객관적 증거는 전혀 발견되지 아니함."
    obs2 = _check_negation_contradictions(doc2, src2, "R2", "인사위원회 조사보고서")
    assert len(obs2) > 0

    # 양성 3: 파면 규정 부존재 vs 규정 명시 주장
    doc3 = "취업규칙상 당연 파면 사유로 명시되어 있다고 주장합니다."
    src3 = "확인사항: 당연 퇴직 및 파면에 관한 해당 조항 없음."
    obs3 = _check_negation_contradictions(doc3, src3, "R3", "인사규정 전문")
    assert len(obs3) > 0


def test_negation_contradictions_negative_control():
    """양식 안내문 배제 및 정상 서면 대조 (대조군 3건)."""
    # 대조군 1: 취업규칙 서식 예시문
    doc1 = "사규에 즉시 징계해고가 규정되어 있습니다."
    src1 = "해당 조항 없음."
    obs1 = _check_negation_contradictions(doc1, src1, "R1", "표준 취업규칙 양식 안내")
    assert len(obs1) == 0

    # 대조군 2: 서면이 객관적 증거 부존재를 인정하고 있는 경우
    doc2 = "조사 과정에서 직접적 지시 증거는 확인되지 않았으나 정황상 의심됩니다."
    src2 = "지시·공모한 객관적 증거는 전혀 발견되지 아니함."
    obs2 = _check_negation_contradictions(doc2, src2, "R2", "고충처리 조사보고서")
    assert len(obs2) == 0

    # 대조군 3: 규정 내용이 서증 원문과 일치하는 경우
    doc3 = "취업규칙 제25조에 경고 처분이 명시되어 있습니다."
    src3 = "제25조(징계의 종류) 징계는 경고, 견책, 감봉으로 구분한다."
    obs3 = _check_negation_contradictions(doc3, src3, "R3", "복무규정")
    assert len(obs3) == 0
