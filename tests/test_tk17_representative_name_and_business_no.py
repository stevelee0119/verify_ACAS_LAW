"""TK-17: 대표이사 띄어쓴 성명 및 사업자등록번호 PII 탐지 규칙 시험.

규칙:
- 사건 고유 값 하드코딩 없이 합성 예시로 검증한다.
- 한국어 주석 포함.
- 양성 3건 이상 (라벨·띄어쓰기·성씨 변경), 대조군 3건 이상 (일반 명사구, 법령 조문, 전화/계좌).
"""
from __future__ import annotations

import pytest
from packages.pii_engine.detector import detect
from packages.pii_engine.engine import PIIEngine
from packages.pii_engine.pseudonym import PseudonymStore


@pytest.fixture
def pii_engine(tmp_path):
    store = PseudonymStore(project_id="test_tk17", root=tmp_path / "vault")
    return PIIEngine(store)


# ==============================================================================
# 양성 시험군 (Positive Controls, 3건 이상)
# ==============================================================================


def test_positive_representative_spaced_name_variation_1(pii_engine):
    """양성 1: '대표이사' 직책 라벨 뒤 띄어쓴 3음절 성명 (박 준 서) 마스킹 검증."""
    text = "피고 주식회사 한국상사 대표이사 박 준 서 (1980. 3. 15.생)"
    res = pii_engine.mask_text(text)
    # 대표이사 직책 뒤 띄어쓴 성명이 PERSON으로 마스킹되어야 함
    assert "박 준 서" not in res.masked_text
    assert "박준서" not in res.masked_text
    person_matches = [m for m in res.matches if m.kind == "PERSON" and m.text == "박준서"]
    assert len(person_matches) >= 1


def test_positive_representative_spaced_name_variation_2(pii_engine):
    """양성 2: '원장' 지위 라벨 뒤 띄어쓴 2음절 성명 (이 영) 마스킹 검증."""
    text = "의료법인 한빛의료재단 원장 이 영 (소재지: 서울 종로구)"
    res = pii_engine.mask_text(text)
    assert "이 영" not in res.masked_text
    assert "이영" not in res.masked_text
    person_matches = [m for m in res.matches if m.kind == "PERSON" and m.text == "이영"]
    assert len(person_matches) >= 1


def test_positive_representative_spaced_name_variation_3(pii_engine):
    """양성 3: '대표자' 라벨 및 콜론 뒤 띄어쓴 성명 (강 태 민) 마스킹 검증."""
    text = "계약상대자 대표자: 강 태 민\n주소: 경기도 성남시 분당구"
    res = pii_engine.mask_text(text)
    assert "강 태 민" not in res.masked_text
    assert "강태민" not in res.masked_text
    person_matches = [m for m in res.matches if m.kind == "PERSON" and m.text == "강태민"]
    assert len(person_matches) >= 1


def test_positive_business_registration_number_labelled(pii_engine):
    """양성 4: '사업자등록번호' 라벨 문맥의 NNN-NN-NNNNN 번호 마스킹 검증."""
    text = "상호: 에이비씨테크 | 사업자등록번호: 214-85-12345 | 대표자: 홍길동"
    res = pii_engine.mask_text(text)
    assert "214-85-12345" not in res.masked_text
    assert "12345" not in res.masked_text
    biz_matches = [m for m in res.matches if m.kind == "BUSINESS_REGISTRATION"]
    assert len(biz_matches) == 1
    assert biz_matches[0].text == "214-85-12345"


def test_positive_business_registration_number_standalone(pii_engine):
    """양성 5: 라벨 없는 본문 속 3-2-5 형식 사업자등록번호 마스킹 검증."""
    text = "당사는 사업자등록 501-23-78901에 의하여 적법하게 사업을 영위하고 있습니다."
    res = pii_engine.mask_text(text)
    assert "501-23-78901" not in res.masked_text
    biz_matches = [m for m in res.matches if m.kind == "BUSINESS_REGISTRATION"]
    assert len(biz_matches) == 1


# ==============================================================================
# 대조군 시험군 (Negative Controls, 3건 이상)
# ==============================================================================


def test_negative_corporate_action_phrases_not_masked_as_person(pii_engine):
    """대조군 1: '대표이사 선임 결의', '이사회' 등 직책 관련 일반 명사구는 PERSON으로 오탐 마스킹되지 않아야 함."""
    text = "임시주주총회에서 대표이사 선임 결의가 이루어졌으며, 이사회 개최를 통지합니다."
    res = pii_engine.mask_text(text)
    # 일반 명사구인 '선임', '결의', '이사회'는 마스킹되지 않고 원문에 유지되어야 함
    assert "대표이사 선임 결의" in res.masked_text or "선임 결의" in res.masked_text
    assert "이사회" in res.masked_text
    person_texts = [m.text for m in res.matches if m.kind == "PERSON"]
    assert "선임" not in person_texts
    assert "결의" not in person_texts
    assert "이사회" not in person_texts


def test_negative_statutory_provisions_not_masked(pii_engine):
    """대조군 2: 상법 등 법령 조문 속의 '이사', '감사', '대표이사' 관련 규정은 PII로 오탐되지 않아야 함."""
    text = "상법 제382조에 따라 이사의 선임은 주주총회의 결의로써 하고, 제389조는 대표이사를 정한다."
    res = pii_engine.mask_text(text)
    assert "상법 제382조" in res.masked_text
    assert "이사의 선임" in res.masked_text
    assert "대표이사를 정한다" in res.masked_text


def test_negative_phone_and_account_not_confused_with_business_no(pii_engine):
    """대조군 3: 전화번호(031-928-3741) 및 계좌번호(110-345-678901)는 사업자등록번호(3-2-5)와 혼동되지 않아야 함."""
    text = "연락처: 031-928-3741, 환불 계좌: 신한은행 110-345-678901 입니다."
    res = pii_engine.mask_text(text)
    # 전화번호는 PHONE, 계좌번호는 ACCOUNT로 정확히 분류되고 BUSINESS_REGISTRATION이 없어야 함
    kinds = {m.kind for m in res.matches}
    assert "BUSINESS_REGISTRATION" not in kinds
    assert "PHONE" in kinds
    assert "ACCOUNT" in kinds
