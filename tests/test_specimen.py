"""가상·예시 문서 식별 (제11장).

AI로 생성한 연습용 계약서를 실제 문서와 구별할 수 있어야 한다.
문체 통계가 아니라 문서 자체에서 결정론적으로 확인되는 신호만 다룬다.
"""
from __future__ import annotations

import pytest

from packages.common.enums import FindingType, Severity
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.forensic_engine.specimen import (
    is_placeholder_number,
    rrn_check_digit,
    rrn_is_valid,
    scan_specimen,
)


def _doc(lines, filename="lease.pdf") -> NormalizedDocument:
    doc = NormalizedDocument(document_id="D", filename=filename, mime_type="application/pdf", sha256="x")
    page = Page(page_number=1)
    for index, text in enumerate(lines):
        page.blocks.append(Block(block_id=f"B{index}", text=text, page=1, source_layer="visible_text"))
    doc.pages.append(page)
    return doc


def _valid_rrn(prefix: str = "800101123456") -> str:
    """검증부호만 맞춘 합성 번호. 실제 발급 여부와는 무관하다."""
    return prefix + str(rrn_check_digit(prefix))


# --- 주민등록번호 검증부호 ------------------------------------------------
@pytest.mark.parametrize("rrn", ["800101-1234567", "920512-2345678"])
def test_fabricated_rrn_fails_check_digit(rrn):
    """창작된 주민등록번호는 검증부호 규칙을 만족하지 못한다.

    실제 제출된 가상 임대차계약서에 기재된 번호들이다.
    """
    assert rrn_is_valid(rrn) is False


def test_check_digit_rule_accepts_its_own_output():
    """검증부호를 맞춘 번호는 유효로 판정되어야 한다(규칙 자체의 정합성)."""
    body = _valid_rrn()
    assert rrn_is_valid(f"{body[:6]}-{body[6:]}") is True


def test_short_number_is_not_judged():
    """자릿수가 모자라면 '무효'가 아니라 '판단하지 않음'이다."""
    assert rrn_is_valid("800101-123") is None


# --- 자리표시자 번호 ------------------------------------------------------
@pytest.mark.parametrize("digits,expected", [
    ("23456789", True),   # 순차
    ("98765432", True),   # 역순
    ("00000000", True),   # 반복
    ("38472951", False),  # 불규칙
    ("123", False),       # 너무 짧다
])
def test_placeholder_number_detection(digits, expected):
    assert is_placeholder_number(digits) is expected


# --- 문서 단위 판정 --------------------------------------------------------
SPECIMEN_LEASE = [
    "가상의 예시 문서입니다 · 실존 인물·부동산과 무관 · 법적 효력 없음",
    "부동산(주택) 임대차 계약서",
    "임대인 김민석과 임차인 박지현은 아래 표시 부동산에 관하여 임대차계약을 체결한다.",
    "주민등록번호 800101-1234567 (예시)",
    "전화 010-2345-6789",
    "주민등록번호 920512-2345678 (예시)",
    "※ 본 문서는 가상의 인물·주소·번호로 작성된 예시(연습용) 서식이며, 실제 법적 효력이 없습니다.",
]


def test_declared_specimen_is_detected():
    """문서가 스스로 밝힌 예시 고지를 놓치지 않는다."""
    findings = scan_specimen(_doc(SPECIMEN_LEASE))
    declared = [f for f in findings if f.type == FindingType.SPECIMEN_DOCUMENT_DECLARED]
    assert declared, "예시 고지가 탐지되어야 한다"
    assert declared[0].severity == Severity.HIGH


def test_invalid_rrn_is_reported_without_leaking_the_number():
    """무효 주민등록번호는 보고하되, 원문 전체를 증거에 남기지 않는다."""
    findings = scan_specimen(_doc(SPECIMEN_LEASE))
    invalid = [f for f in findings if f.type == FindingType.INVALID_IDENTIFIER]
    assert invalid, "검증부호 위반이 탐지되어야 한다"
    blob = invalid[0].detail + str(invalid[0].evidence[0].excerpt)
    assert "1234567" not in blob and "2345678" not in blob, "주민등록번호 뒷자리가 노출되면 안 된다"


def test_placeholder_identifiers_are_reported():
    findings = scan_specimen(_doc(SPECIMEN_LEASE))
    assert [f for f in findings if f.type == FindingType.PLACEHOLDER_IDENTIFIER]


REAL_LEASE = [
    "부동산(주택) 임대차 계약서",
    "임대인과 임차인은 아래 표시 부동산에 관하여 임대차계약을 체결한다.",
    "소재지 서울특별시 마포구 성산로 123, 한강뷰아파트 101동 502호",
    "보증금 금 삼억원整(₩300,000,000)",
    "제2조(존속기간) 임대차 기간은 인도일로부터 2028년 10월 31일까지(24개월)로 한다.",
    "제6조(계약의 종료) 임대차계약이 종료된 경우에 임차인은 위 부동산을 원상으로 회복하여 반환한다.",
    "본 계약을 증명하기 위하여 계약 당사자가 이의 없음을 확인하고 각각 서명·날인한다.",
    "전화 010-3847-2951",
]


def test_ordinary_contract_has_no_specimen_false_positive():
    """평범한 계약서를 예시 문서로 지목하면 안 된다."""
    body = _valid_rrn()
    lines = REAL_LEASE + [f"주민등록번호 {body[:6]}-{body[6:]}"]
    assert scan_specimen(_doc(lines)) == []


@pytest.mark.parametrize("line", [
    "제5조(채무불이행과 손해배상) 불이행이 있을 경우 서면으로 최고하고 계약을 해제할 수 있다.",
    "임차인은 임대인의 동의 없이 전대·임차권 양도를 하지 못한다.",
    "개업공인중개사는 계약 당사자 간 채무불이행에 대하여 책임을 지지 않는다.",
])
def test_standard_contract_clauses_are_not_flagged(line):
    """표준계약서의 통상 조항이 고지 문구로 오인되면 안 된다."""
    assert scan_specimen(_doc([line])) == []


def test_body_that_was_never_read_yields_nothing():
    """본문이 없으면 아무 판단도 하지 않는다(빈 문서에 근거 없는 결론 금지)."""
    assert scan_specimen(_doc([])) == []


# --- 한국어 OCR 출력 대응 -------------------------------------------------
OCR_LEASE = [
    # 실제 tesseract(kor) 출력. 글자 사이에 공백이 들어간다.
    "가 상 의 예시 문 서 입니다 ㆍ 실 존 인 물 ㆍ 부 동 산 과 무관 ㆍ 법적 효력 없음",
    "임대인 김 민 석 과 임차인 박 지 현 은 아래 표시 부 동 산 에 관하여",
    "800101-1234567( 예 시)",
    "010-2345-6789",
    "※ 본 문서는 가 상 의 인물ㆍ주소ㆍ번호로 작성된 예시( 연습용 ) 서식이며, 실제 법적 효력이 없습니다.",
]


def test_specimen_survives_korean_ocr_spacing():
    """한국어 OCR이 글자 사이에 넣는 공백 때문에 탐지를 놓치면 안 된다.

    실제 이미지 입력을 tesseract(kor)로 읽으면 "가 상 의 예시 문 서"처럼 나온다.
    원문 그대로 대조하면 고지 문구 6종 중 4종을 놓친다.
    """
    findings = scan_specimen(_doc(OCR_LEASE))
    types = {f.type for f in findings}
    assert FindingType.SPECIMEN_DOCUMENT_DECLARED in types, "공백이 섞인 고지 문구를 놓쳤다"
    assert FindingType.INVALID_IDENTIFIER in types


def test_declaration_spanning_two_lines_is_detected():
    """줄바꿈으로 잘린 고지 문구도 페이지 단위 검사로 잡는다."""
    findings = scan_specimen(_doc(["본 문서는 가상의", "예시 서식이며 법적 효력이 없습니다."]))
    assert [f for f in findings if f.type == FindingType.SPECIMEN_DOCUMENT_DECLARED]


def test_ocr_spacing_does_not_create_false_positives():
    """공백을 지우고 본다고 해서 평범한 문장이 걸리면 안 된다."""
    lines = [
        "임 대 인 과 임 차 인 은 아래 표시 부 동 산 에 관하여 임 대 차 계 약 을 체 결 한다.",
        "제 2 조 ( 존 속 기 간 ) 임대차 기간은 2028년 10월 31일까지로 한다.",
        "실제 발생한 손해에 대하여 배상을 청구할 수 있다.",
    ]
    assert scan_specimen(_doc(lines)) == []
