"""TK-69: FT 목 인용 가운뎃점·복수 목(열거·범위) 인식 및 정규식 공백 모호성 제거 시험.

문서·문장·조문 내용은 모두 시험용 가상 합성 데이터이다 (은퇴 세트 및 실제 서면 문구·고유값을 일절 포함하지 않음).
"""
from __future__ import annotations

import time
import pytest

from types import SimpleNamespace
from packages.legal_engine.temporal_review import (
    ITEM_SUBITEM_RE,
    extract_subitem_info,
    extract_subitems_info,
    version_outcomes,
)


def _cit(raw_text: str, item: str | None = None, claim_text: str | None = None):
    attrs = {"claim_text": claim_text} if claim_text else {}
    return SimpleNamespace(raw_text=raw_text, item=item, paragraph=None, attributes=attrs)


# ======================================================================================
# 1. 정규식 시간 성능 시험 (반복 입력 0.1초 이내 단언)
# ======================================================================================

def test_tk69_item_subitem_regex_timing_polynomial_growth_eliminated():
    """[합성 성능] 공백 4,000자 반복 입력에서도 지연 없이 0.1초 이내에 종료된다 (TK-69 공백 모호성 제거)."""
    # 불일치 패턴 (1호 + 공백 4,000개 + 비매칭 문자)
    bad_input_mismatch = "1호" + " " * 4000 + "x"
    t0 = time.perf_counter()
    res = ITEM_SUBITEM_RE.search(bad_input_mismatch)
    elapsed = time.perf_counter() - t0
    assert res is None
    assert elapsed < 0.1, f"정규식 백트래킹 지연 발생: {elapsed:.4f}초 (한도: 0.1초)"

    # 일치 패턴 (제1호 + 공백 4,000개 + 가목)
    input_match = "제1호" + " " * 4000 + "가목"
    t0 = time.perf_counter()
    res2 = ITEM_SUBITEM_RE.search(input_match)
    elapsed2 = time.perf_counter() - t0
    assert res2 is not None
    assert res2.group("item") == "1"
    assert res2.group("subitem") == "가"
    assert elapsed2 < 0.1, f"정규식 매칭 지연 발생: {elapsed2:.4f}초 (한도: 0.1초)"


# ======================================================================================
# 2. 복수 목 추출 양성 시험 (가운뎃점, 접속사 '및', 범위 표기 '부터~까지')
# ======================================================================================

def test_positive_extract_subitems_middle_dots():
    """[합성 양성 1] 가운뎃점류(·, ㆍ, ・)로 연결된 목 표기를 모두 추출한다."""
    c1 = _cit("제1호 가목·나목에 따라")
    item1, subitems1 = extract_subitems_info(c1)
    assert item1 == "1"
    assert subitems1 == ["가", "나"]

    c2 = _cit("제2호 가목ㆍ나목ㆍ다목")
    item2, subitems2 = extract_subitems_info(c2)
    assert item2 == "2"
    assert subitems2 == ["가", "나", "다"]

    c3 = _cit("제3호 가목・라목")
    item3, subitems3 = extract_subitems_info(c3)
    assert item3 == "3"
    assert subitems3 == ["가", "라"]


def test_positive_extract_subitems_conjunctions():
    """[합성 양성 2] '및', '와', '과', 쉼표로 연결된 목 표기를 모두 추출한다."""
    c1 = _cit("제1호 가목 및 나목의 규정에 의하여")
    item1, subitems1 = extract_subitems_info(c1)
    assert item1 == "1"
    assert subitems1 == ["가", "나"]

    c2 = _cit("제5호 가목, 나목, 다목")
    item2, subitems2 = extract_subitems_info(c2)
    assert item2 == "5"
    assert subitems2 == ["가", "나", "다"]

    c3 = _cit("제7호 가목과 나목")
    item3, subitems3 = extract_subitems_info(c3)
    assert item3 == "7"
    assert subitems3 == ["가", "나"]


def test_positive_extract_subitems_ranges():
    """[합성 양성 3] '부터~까지', '내지' 범위 표기 목을 순서대로 모두 확장하여 추출한다."""
    c1 = _cit("제1호 가목부터 다목까지에 규정된")
    item1, subitems1 = extract_subitems_info(c1)
    assert item1 == "1"
    assert subitems1 == ["가", "나", "다"]

    c2 = _cit("제2호 나목 내지 라목")
    item2, subitems2 = extract_subitems_info(c2)
    assert item2 == "2"
    assert subitems2 == ["나", "다", "라"]


# ======================================================================================
# 3. 대조군 시험 ('다목적', '항목/품목', 호 없는 목 표기)
# ======================================================================================

def test_control_word_damokjeok_not_matched():
    """[합성 대조 1] '다목적'처럼 목 뒤에 일반 명사 어근이 이어지는 경우 목으로 오인하지 않는다."""
    c = _cit("제3호 다목적 시설을 설치한다")
    item, subitems = extract_subitems_info(c)
    assert item is None
    assert subitems == []


def test_control_words_hangmok_pummok_not_matched():
    """[합성 대조 2] '항목', '품목' 등 일반 명사는 목으로 오인하지 않는다."""
    c1 = _cit("제2호 항목을 신설한다")
    item1, subitems1 = extract_subitems_info(c1)
    assert item1 is None
    assert subitems1 == []

    c2 = _cit("제4호 품목에 해당하는 물품")
    item2, subitems2 = extract_subitems_info(c2)
    assert item2 is None
    assert subitems2 == []


def test_control_bare_subitem_without_item_not_matched():
    """[합성 대조 3] 호 표기가 선행하지 않고 '가목'만 단독으로 나타난 경우 목으로 추출하지 않는다."""
    c = _cit("가목 및 나목에 따라 청구한다")
    item, subitems = extract_subitems_info(c)
    assert item is None
    assert subitems == []


# ======================================================================================
# 4. 복수 목 합친 본문 대조 및 TK-62 원칙 검증
# ======================================================================================

def test_multiple_subitems_combined_text_verified():
    """[합성 대조 4] '가목 및 나목' 인용 시 두 목의 본문을 합친 범위를 대상으로 청구 문언을 검증한다."""
    citation = _cit(
        raw_text="제1호 가목 및 나목",
        claim_text="신고서 제출 및 수수료 3만원 납부",
    )
    versions = [
        {
            "effective_from": "2026-01-01",
            "effective_to": None,
            "text": "제10조\n1. 다음 각 목의 사항\n가. 신고서 제출\n나. 수수료 3만원 납부\n",
        }
    ]
    outcomes = version_outcomes(citation, versions)
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"]["status"] == "VERIFIED"


def test_tk62_regression_rule_preserved():
    """[TK-62 회귀 유지] 어느 판본에서도 목 단위 VERIFIED가 확인되지 않으면 CONTRADICTED 대신 기본 결과를 유지한다."""
    citation = _cit(
        raw_text="제1호 가목·나목",
        claim_text="관할청의 사전 인가",
    )
    versions = [
        {
            "effective_from": "2024-01-01",
            "effective_to": "2025-12-31",
            "text": "제10조\n1. 운영 기준\n가. 사전 등록\n",
        },
        {
            "effective_from": "2026-01-01",
            "effective_to": None,
            "text": "제10조\n1. 운영 기준\n가. 사전 등록\n나. 정기 보고\n",
        },
    ]
    outcomes = version_outcomes(citation, versions)
    # 어느 판본에서도 목 단위 VERIFIED가 없으므로 SUBITEM_NOT_EXIST에 의한 CONTRADICTED 강제가 발생하지 않음
    assert all(o["outcome"].get("basis") != "SUBITEM_NOT_EXIST" for o in outcomes)

