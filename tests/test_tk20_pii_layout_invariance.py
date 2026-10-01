"""TK-20 1절: 개인정보 배치 불변(Layout Invariance) 일반화 시험.

주소 동·호·층의 구조적 결합(영문자 동, 층, 호, 건물명, 쉼표/공백) 및
소송대리인·법원 주소의 블록/줄바꿈 경계 초월 보존,
담당변호사 성명의 동일 줄/줄바꿈 배치 불변 탐지를 검증한다.
"""
from __future__ import annotations

import pytest

from packages.pii_engine.detector import detect
from packages.pii_engine.engine import PIIEngine
from packages.pii_engine.pseudonym import PseudonymStore
from packages.common.schemas import NormalizedDocument, Page, Block


# -------------------------------------------------------------------------
# 1. 주소 동·호·층 구조적 결합 양성 시험 (배치 및 표기 다양화 6건)
# -------------------------------------------------------------------------
@pytest.mark.parametrize("addr_text, expected_tokens", [
    ("서울 강남구 테헤란로 152, A동 1203호", ["A동", "1203호"]),
    ("부산 해운대구 센텀중앙로 79 B동 502호", ["B동", "502호"]),
    ("경기 성남시 분당구 판교역로 166, 101동 B1호", ["101동", "B1호"]),
    ("인천 연수구 송도과학로 32, 가동 3층 301호", ["가동", "3층", "301호"]),
    ("대구 수성구 달구벌대로 2450, 타워빌딩 12층", ["타워빌딩", "12층"]),
    ("광주 서구 상무중앙로 80, 행복아파트 C동 704호", ["행복아파트", "C동", "704호"]),
])
def test_address_layout_and_unit_invariance_positive(addr_text, expected_tokens):
    """영문 동, 층, 호, 건물명 등이 쉼표 또는 공백으로 결합되어도 전체 주소가 온전히 탐지되는지 확인."""
    matches = detect(addr_text)
    addr_matches = [m for m in matches if m.kind == "ADDRESS"]
    assert len(addr_matches) >= 1, f"주소 미탐지: {addr_text}"
    matched_text = addr_matches[0].text
    for token in expected_tokens:
        assert token in matched_text, f"주소 꼬리 토큰 '{token}' 누락: {matched_text}"


# -------------------------------------------------------------------------
# 2. 담당변호사 성명 배치 불변 양성 시험 (동일 줄/줄바꿈/띄어쓰기 6건)
# -------------------------------------------------------------------------
@pytest.mark.parametrize("lawyer_line, expected_name", [
    ("소송대리인 법무법인 태평양 담당변호사 김 민 수", "김민수"),
    ("소송대리인 법무법인 세종 담당변호사 이진우", "이진우"),
    ("소송대리인 변호사 박 영 희", "박영희"),
    ("법무법인 화우\n담당변호사 최 동 욱", "최동욱"),
    ("소송대리인 법률사무소 정진 담당변호사 정 혜 린 (인)", "정혜린"),
    ("대리인변호사 강 건 우", "강건우"),
])
def test_lawyer_name_layout_invariance_positive(lawyer_line, expected_name):
    """담당변호사 라벨이 법인명과 같은 줄에 있거나 별도 줄에 있어도 성명이 정상 탐지되는지 확인."""
    matches = detect(lawyer_line)
    person_names = {m.text for m in matches if m.kind == "PERSON"}
    assert expected_name in person_names, f"변호사 성명 '{expected_name}' 미탐지: {matches}"


# -------------------------------------------------------------------------
# 3. 소송대리인·법원 주소 블록 분리 보존 및 오탐 방지 대조군 (3건)
# -------------------------------------------------------------------------
def test_lawyer_address_in_separate_block_preserved_control(tmp_path):
    """소송대리인 표기와 주소가 서로 다른 블록으로 나뉘어 있어도 마스킹되지 않고 보존되는지 검증."""
    engine = PIIEngine(PseudonymStore("prj_control_lawyer", root=tmp_path))
    doc = NormalizedDocument(
        document_id="doc_control_lawyer_addr",
        filename="control.txt",
        mime_type="text/plain",
        sha256="abc123",
        pages=[
            Page(
                page_number=1,
                blocks=[
                    Block(block_id="b1", page=1, text="소송대리인 법무법인 넥서스 담당변호사 정 현 우", source_layer="visible_text"),
                    Block(block_id="b2", page=1, text="서울 서초구 반포대로 100, 15층", source_layer="visible_text"),
                    Block(block_id="b3", page=1, text="피고 대한민국", source_layer="visible_text"),
                ]
            )
        ]
    )
    masked = engine.mask_document(doc)
    # 블록 2의 소송대리인 주소는 원문이 그대로 보존되어야 함
    b2_text = next(b["text"] for b in masked.blocks if b["block_id"] == "b2")
    assert "반포대로 100" in b2_text, f"소송대리인 주소가 잘못 마스킹됨: {b2_text}"
    assert "[ADDRESS" not in b2_text


def test_general_legal_terms_not_masked_as_person_control():
    """일반 법률 용어나 행정 명사가 PERSON으로 오탐되지 않는지 검증."""
    text = "원고의 청구는 변호인 선임권 침해를 이유로 한 것이 아니며 담당자의 정당한 재량권 행사에 불과하다."
    matches = detect(text)
    person_matches = [m for m in matches if m.kind == "PERSON"]
    assert len(person_matches) == 0, f"일반 법률 용어가 PERSON으로 오탐됨: {person_matches}"


def test_statutory_articles_not_masked_as_address_or_person_control():
    """법령 조문 및 행정 명칭이 ADDRESS나 PERSON으로 오탐되지 않는지 검증."""
    text = "「행정소송법」 제8조 제2항, 「민사소송법」 제422조에 의하여 원고의 주장을 기각한다."
    matches = detect(text)
    invalid_matches = [m for m in matches if m.kind in ("ADDRESS", "PERSON")]
    assert len(invalid_matches) == 0, f"법령 조문이 오탐됨: {invalid_matches}"
