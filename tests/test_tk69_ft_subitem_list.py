"""TK-69: FT 목 인용 가운뎃점·복수 목(열거·범위) 인식 및 정규식 공백 모호성 제거 시험.

문서·문장·조문 내용은 모두 시험용 가상 합성 데이터이다 (은퇴 세트 및 실제 서면 문구·고유값을 일절 포함하지 않음).
"""
from __future__ import annotations

import time
import pytest

from types import SimpleNamespace
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.citation_extractor import extract_citations
from packages.legal_engine.temporal_review import (
    ITEM_SUBITEM_RE,
    NEXT_SUBITEM_RE,
    extract_subitem_info,
    extract_subitems_info,
    parse_subitem_sequence,
    version_outcomes,
)


def _cit(raw_text: str, item: str | None = None, claim_text: str | None = None):
    attrs = {"claim_text": claim_text} if claim_text else {}
    return SimpleNamespace(raw_text=raw_text, item=item, paragraph=None, attributes=attrs)


def _make_synth_doc(text: str) -> NormalizedDocument:
    """합성 텍스트로 NormalizedDocument를 생성한다."""
    return NormalizedDocument(
        document_id="synth_doc",
        filename="synth_doc.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        pages=[Page(page_number=1, blocks=[Block(block_id="b1", text=text, page=1)])],
    )


# ======================================================================================
# 1. 정규식 및 함수 시간 성능 시험 (반복 입력 0.1초 이내 단언 - TK-66 및 TK-69 개정 1)
# ======================================================================================

def test_tk69_item_subitem_regex_timing_polynomial_growth_eliminated():
    """[합성 성능 1] ITEM_SUBITEM_RE: 공백 4,000자 반복 입력에서도 0.1초 이내 종료 (공백 모호성 제거)."""
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


def test_tk69_next_subitem_trailing_spaces_timing_quadratic_eliminated():
    """[합성 성능 2] NEXT_SUBITEM_RE 및 parse_subitem_sequence: 후행 공백 20,000자 반복 입력에서 0.1초 이내 종료."""
    # 평가 측 측정 재현: 목 표기 뒤 공백 2만 개 + 'x' 입력 시 0.1초 이내 처리 (평가 측 기준 2.26초 다항식 증가 해소)
    trailing_spaces_input = " " * 20000 + "x"

    # 1) NEXT_SUBITEM_RE 자체의 단일 매칭 속도 검증
    t0 = time.perf_counter()
    res_re = NEXT_SUBITEM_RE.match(trailing_spaces_input)
    elapsed_re = time.perf_counter() - t0
    assert res_re is None
    assert elapsed_re < 0.1, f"NEXT_SUBITEM_RE 백트래킹 지연 발생: {elapsed_re:.4f}초 (한도: 0.1초)"

    # 2) parse_subitem_sequence 유한 창 상한 및 지연 없는 처리 검증
    t0 = time.perf_counter()
    subitems, consumed = parse_subitem_sequence(trailing_spaces_input, "가")
    elapsed_parse = time.perf_counter() - t0
    assert subitems == ["가"]
    assert consumed == 0
    assert elapsed_parse < 0.1, f"parse_subitem_sequence 지연 발생: {elapsed_parse:.4f}초 (한도: 0.1초)"

    # 3) extract_subitems_info 함수 전체 경로의 속도 검증
    cit_large = _cit("제1호 가목" + trailing_spaces_input)
    t0 = time.perf_counter()
    item, extracted = extract_subitems_info(cit_large)
    elapsed_func = time.perf_counter() - t0
    assert item == "1"
    assert extracted == ["가"]
    assert elapsed_func < 0.1, f"extract_subitems_info 지연 발생: {elapsed_func:.4f}초 (한도: 0.1초)"


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


# ======================================================================================
# 5. 파이프라인 경로 시험 (합성 서면 → extract_citations → version_outcomes)
# ======================================================================================

def test_pipeline_path_multiple_subitems_extraction_and_outcomes():
    """[합성 파이프라인 1] 합성 서면에서 extract_citations를 거쳐 version_outcomes까지 세 형태가 여러 목으로 대조된다.

    세 형태:
    1) '가목·나목' (가운뎃점)
    2) '가목 및 나목' (접속사)
    3) '가목부터 다목까지' (범위)
    """
    sample_versions = [
        {
            "effective_from": "2025-01-01",
            "effective_to": None,
            "version_id": "v1",
            "text": (
                "제2조(배상책임) ① 국가나 지방자치단체는 배상 책임을 진다.\n"
                "1. 다음 각 목의 기준에 해당하는 경우\n"
                "가. 공무원의 직무상 불법행위로 타인에게 손해를 입힌 경우\n"
                "나. 피해자의 중대한 과실이 부존재함을 입증한 경우\n"
                "다. 법정 배상금 산정 기준 5000만원 한도를 초과하지 않는 경우\n"
            ),
        }
    ]

    # 케이스 1: 가목·나목
    doc1 = _make_synth_doc("국가배상법 제2조 제1항 제1호 가목·나목에 따라 피해자의 중대한 과실이 부존재함을 주장한다.")
    cits1 = extract_citations(doc1)
    assert len(cits1) == 1
    cit1 = cits1[0]
    assert "가목·나목" in cit1.raw_text
    assert cit1.attributes.get("subitems") == ["가", "나"]

    # 나목 문언으로 대조 시, 가목 단독 대조라면 불일치지만 복수 목(가·나 결합) 대조이므로 VERIFIED
    outcomes1 = version_outcomes(cit1, sample_versions)
    assert len(outcomes1) == 1
    assert outcomes1[0]["outcome"]["status"] == "VERIFIED"

    # 케이스 2: 가목 및 나목
    doc2 = _make_synth_doc("국가배상법 제2조 제1항 제1호 가목 및 나목에 의하여 피해자의 중대한 과실이 부존재함을 주장한다.")
    cits2 = extract_citations(doc2)
    assert len(cits2) == 1
    cit2 = cits2[0]
    assert "가목 및 나목" in cit2.raw_text
    assert cit2.attributes.get("subitems") == ["가", "나"]

    outcomes2 = version_outcomes(cit2, sample_versions)
    assert len(outcomes2) == 1
    assert outcomes2[0]["outcome"]["status"] == "VERIFIED"

    # 케이스 3: 가목부터 다목까지
    doc3 = _make_synth_doc("국가배상법 제2조 제1항 제1호 가목부터 다목까지에 규정된 법정 배상금 산정 기준 5000만원 한도를 적용한다.")
    cits3 = extract_citations(doc3)
    assert len(cits3) == 1
    cit3 = cits3[0]
    assert "가목부터 다목까지" in cit3.raw_text
    assert cit3.attributes.get("subitems") == ["가", "나", "다"]

    # 다목 문언으로 대조 시, 가목 단독 대조라면 불일치지만 3개 목 결합 대조이므로 VERIFIED
    outcomes3 = version_outcomes(cit3, sample_versions)
    assert len(outcomes3) == 1
    assert outcomes3[0]["outcome"]["status"] == "VERIFIED"
