"""v0.8.8 개선 과제 종합 단위 및 회귀 테스트.

1. 호증 파서: 접두어(갑·을·병·정·증·피고인 증·검사 증), 복수 호증, 가지번호(범위, 열거, 단일).
2. 법리 규칙 부정 표현: 아니다·않는다·대상이 아니라고 처리 시 오탐 방지.
3. 통화 및 금액 표기: ₩, 금 …원정 파싱 및 병기 불일치 검증.
4. 합계 검산 중복·부분 판정 제거: 단일 포괄 finding 채택 검증.
5. 정답지 제외 및 입력 거부 검증.
6. 대조군(정상) 문서에서 CONTRADICTED 0건 회귀 테스트.
"""
from __future__ import annotations

import re
from decimal import Decimal
import pytest

from packages.claim_engine.exhibits import parse_exhibit_label
from packages.claim_engine.korean_amount import parse_korean_amount, words_digits_mismatches
from packages.claim_engine.calculation import parse_amounts, CalculationEngine
from packages.common.schemas import Block, Finding, NormalizedDocument, Page
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.legal_engine.legal_rules import review_legal_rules
from packages.verification_engine.ground_truth_filter import (
    is_ground_truth_filename,
    is_ground_truth_content,
    check_and_reject_ground_truth,
)


def test_exhibit_parser_extended():
    """과제 3 & 5: 다양한 호증 서식 파싱 테스트."""
    # 1. 범위 가지번호
    p1 = parse_exhibit_label("갑 제5호증의 1 내지 3 각 진술서")
    assert p1 is not None
    assert p1["party"] == "갑"
    assert p1["number"] == 5
    assert p1["branches"] == [1, 2, 3]
    assert p1["name"] == "진술서"

    # 2. 쉼표 나열 가지번호
    p2 = parse_exhibit_label("갑 제2호증의 1, 2 영수증")
    assert p2 is not None
    assert p2["party"] == "갑"
    assert p2["number"] == 2
    assert p2["branches"] == [1, 2]
    assert p2["name"] == "영수증"

    # 3. 복수 호증 번호
    p3 = parse_exhibit_label("갑 제1, 2호증 각 계약서")
    assert p3 is not None
    assert p3["party"] == "갑"
    assert p3["numbers"] == [1, 2]
    assert p3["number"] == 1
    assert p3["name"] == "계약서"

    # 4. 형사 증거 및 피고인 증
    p4 = parse_exhibit_label("증 제3호증 압수조서")
    assert p4 is not None
    assert p4["party"] == "증"
    assert p4["number"] == 3
    assert p4["name"] == "압수조서"

    p5 = parse_exhibit_label("피고인 증 제1호증 사실확인서")
    assert p5 is not None
    # 피고인 증 표기 정규화(공백 제거/유지) 호환성 검증
    assert p5["party"] in ("피고인 증", "피고인증")
    assert p5["number"] == 1
    assert p5["name"] == "사실확인서"

    # 5. 을 제N호증의 N
    p6 = parse_exhibit_label("을 제4호증의 2 진단서")
    assert p6 is not None
    assert p6["party"] == "을"
    assert p6["number"] == 4
    assert p6["branches"] == [2]
    assert p6["name"] == "진단서"


def test_ground_truth_filter():
    """과제 2: 정답지 파일명 및 본문 제외/거부 테스트."""
    assert is_ground_truth_filename("00_GroundTruth.pdf")
    assert is_ground_truth_filename("ground_truth.pdf")
    assert is_ground_truth_filename("사건_정답지.pdf")
    assert not is_ground_truth_filename("소장.pdf")
    assert not is_ground_truth_filename("준비서면.pdf")

    assert is_ground_truth_content("이 문서는 정답지입니다. 판정 기준 목록...")
    assert is_ground_truth_content("Ground Truth Verification Document")
    assert not is_ground_truth_content("원고는 피고에게 금전을 청구합니다.")

    with pytest.raises(ValueError, match="정답지"):
        check_and_reject_ground_truth("00_GroundTruth.pdf")


def test_amount_formats_with_currency_and_wonjung():
    """과제 5: ₩ 및 금 …원정 통화 서식 지원 테스트."""
    # ₩ 기호 금액 파싱
    parsed = parse_amounts("청구금액은 ₩ 30,000,000 입니다.")
    assert len(parsed) == 1
    assert parsed[0].value == Decimal("30000000")

    # 금 …원정 금액 파싱
    parsed2 = parse_amounts("금 15,500,000원정을 지급하라.")
    assert len(parsed2) == 1
    assert parsed2[0].value == Decimal("15500000")

    # 한글·숫자 병기 파싱
    v1 = parse_korean_amount("금 일억오천만원정")
    assert v1 == Decimal("150000000")

    v2 = parse_korean_amount("₩ 30,000,000")
    # korean_amount는 한글 금액 해석기이므로 숫자만 있는 경우 None
    assert v2 is None


def test_legal_rules_negation():
    """과제 4: 법리 규칙 부정 표현(아니다, 않는다, 대상이 아니라고) 오탐 배제 테스트."""
    # 부정 표현이 포함된 정상적 항변 서면 텍스트
    text = (
        "청 구 취 지\n1. 피고는 원고에게 1,000,000원을 지급하라.\n\n"
        "청 구 원 인\n"
        "피고는 공무원 개인의 경과실에 기한 손해배상책임이 인정되지 않는다고 주장한다. "
        "또한 형사처벌을 구하는 것은 본 행정소송의 대상이 아니라고 판단된다."
    )
    from packages.common.schemas import Page
    doc = NormalizedDocument(
        document_id="TEST_NEG",
        filename="test_neg.pdf",
        mime_type="application/pdf",
        sha256="testsha256",
        pages=[Page(page_number=1, width=595.0, height=842.0, blocks=[Block(block_id="b1", page=1, text=text, source_layer="visible_text", visible=True)])],
        metadata={},
    )
    findings = review_legal_rules(doc)
    # 부정된 표현이므로 법리 위반으로 지적되지 않아야 함
    rule_ids = [f.confidence_features.get("rule_id") for f in findings if f.confidence_features]
    assert "TORT.OFFICIAL_LIGHT_NEGLIGENCE" not in rule_ids
    assert "ADMIN.RELIEF_CRIMINAL_PUNISHMENT" not in rule_ids


def test_deduplicate_totals():
    """과제 7: 합계 검산 중복·부분 판정 제거 테스트."""
    engine = CalculationEngine()
    f1 = Finding.create(
        type=FindingType.ARITHMETIC_MISMATCH,
        status=VerificationStatus.CONTRADICTED,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.A,
        title="합계가 세부 금액 합산값과 다르다 (차이 10,000원)",
        page=1,
        confidence_features={"stated": "100000", "item_count": 5, "rows_used": ["행1", "행2", "행3", "행4", "행5"]},
    )
    # 동일한 stated에 대해 일부 행만으로 산출된 부분 판정
    f2 = Finding.create(
        type=FindingType.ARITHMETIC_MISMATCH,
        status=VerificationStatus.CONTRADICTED,
        severity=Severity.MEDIUM,
        evidence_grade=EvidenceGrade.A,
        title="합계가 세부 금액 합산값과 다르다 (차이 50,000원)",
        page=1,
        confidence_features={"stated": "100000", "item_count": 2, "rows_used": ["행1", "행2"]},
    )
    deduped = engine._deduplicate_totals([f1, f2])
    assert len(deduped) == 1
    # 더 많은 세부항목(item_count=5)을 가진 f1만 채택
    assert deduped[0].confidence_features["item_count"] == 5


def test_control_document_zero_contradicted():
    """과제 3: 정상 대조군 문서에서 CONTRADICTED가 0건이어야 하는 회귀 테스트."""
    # 정상적으로 작성된 대조군 서면
    valid_text = (
        "사건 2026가합1001 손해배상(기)\n"
        "원고 김철수\n피고 박영희\n\n"
        "청 구 취 지\n"
        "1. 피고는 원고에게 금 10,000,000원 및 이에 대한 지연손해금을 지급하라.\n\n"
        "청 구 원 인\n"
        "1. 2026. 1. 10. 사고가 발생하였습니다.\n"
        "2. 원고는 치료비로 다음과 같이 지출하였습니다.\n"
        "진료비 6,000,000원\n"
        "약제비 4,000,000원\n"
        "합계 10,000,000원\n\n"
        "입 증 방 법\n"
        "갑 제1호증의 1 내지 3 각 진료기록\n"
        "갑 제2호증 영수증\n\n"
        "2026. 2. 1.\n"
        "원고 대리인 (인)\n"
    )
    from packages.common.schemas import Page
    doc = NormalizedDocument(
        document_id="CONTROL_DOC",
        filename="control.pdf",
        mime_type="application/pdf",
        sha256="controlsha256",
        pages=[Page(page_number=1, width=595.0, height=842.0, blocks=[Block(block_id="b1", page=1, text=valid_text, source_layer="visible_text", visible=True)])],
        metadata={},
    )
    calc_engine = CalculationEngine()
    findings = calc_engine.verify_document(doc)
    contradicted = [f for f in findings if f.status == VerificationStatus.CONTRADICTED]
    assert len(contradicted) == 0, f"대조군 문서에서 CONTRADICTED finding이 발생함: {contradicted}"
