"""v4 P4: 한글 금액 해석(30건)·한글↔숫자 병기 대조·증거목록 금액↔첨부 원문·호증 번호 중복·작성일 선후."""
from __future__ import annotations

from decimal import Decimal

import pytest

from packages.claim_engine.evidence_consistency import check_exhibits, document_date
from packages.claim_engine.korean_amount import parse_korean_amount, words_digits_mismatches
from packages.common.enums import FindingType
from packages.common.schemas import Block, NormalizedDocument, Page
from tests.test_v3_g5_facts import doc

CONVERSIONS = [
    ("일원", 1), ("십원", 10), ("오십", 50), ("백", 100), ("천", 1000), ("만원", 10_000), ("십만", 100_000),
    ("사십오만", 450_000), ("백만원", 1_000_000), ("오백만원", 5_000_000), ("칠백만", 7_000_000),
    ("칠백오십만원", 7_500_000), ("천만", 10_000_000), ("2천만", 20_000_000), ("삼천오백만", 35_000_000),
    ("억", 100_000_000), ("일억", 100_000_000), ("1억2,000만", 120_000_000), ("이억영천만", 200_000_000),
    ("이억오천만", 250_000_000), ("3억 5천만", 350_000_000), ("구억구천만", 990_000_000), ("십억", 1_000_000_000),
    ("백이십삼만사천오백육십칠", 1_234_567), ("구십구억구천구백구십구만", 9_999_990_000), ("일조", 10 ** 12),
    ("일금 오백만원정", 5_000_000), ("금 삼백이십만원", 3_200_000), ("오천삼백", 5_300), ("육백칠십팔만구천", 6_789_000),
]


@pytest.mark.parametrize("words, value", CONVERSIONS)
def test_korean_amount_conversion(words, value):
    assert parse_korean_amount(words) == Decimal(value)


def test_conversion_set_has_thirty_cases():
    assert len(CONVERSIONS) >= 30


@pytest.mark.parametrize("text", ["가나다", "오백만불", "삼만 원숭이", ""])
def test_unparseable_words_return_none(text):
    assert parse_korean_amount(text) is None


@pytest.mark.parametrize("line, words_value, digits_value", [
    ("위자료는 금 칠백만원(7,500,000원)으로 산정하였다.", 7_000_000, 7_500_000),                  # 민사
    ("피고는 원고에게 재산분할로 금 이억오천만원(205,000,000원)을 지급하라.", 250_000_000, 205_000_000),  # 가사
    ("피고인은 금 5,000,000원(삼백만원)을 공탁하였다.", 3_000_000, 5_000_000),                       # 형사
    ("과징금 일금 삼천만원정(30,000,000원)을 부과한 처분은 적법하다.", None, None),                     # 행정(일치)
])
def test_words_and_digits_are_compared(line, words_value, digits_value):
    found = words_digits_mismatches(doc(line))
    if words_value is None:
        assert found == []
    else:
        [f] = found
        assert f.confidence_features["defect_code"] == "AMOUNT_WORDS_MISMATCH"
        assert Decimal(f.confidence_features["words_value"]) == words_value
        assert Decimal(f.confidence_features["digits_value"]) == digits_value


def test_particle_before_amount_is_not_part_of_the_words():
    assert words_digits_mismatches(doc("손해액이 오백만원(5,000,000원)이다.")) == []


# --- 증거목록 --------------------------------------------------------------------------------
HEADER = ["호증", "증거명", "작성일", "금액"]


def test_list_amount_differs_from_attached_original():                                 # 가사
    d = doc("입증방법", "첨부 입금확인서(사본)", "입금확인서: 금 21,000,000원이 입금되었음을 확인합니다.",
            tables=[[HEADER, ["갑 제2호증", "입금확인서", "2021. 7. 9.", "12,000,000원"]]])
    [f] = [f for f in check_exhibits(d) if f.confidence_features.get("rule_id") == "EVI.LIST_AMOUNT_MISMATCH"]
    assert f.confidence_features["digit_transposition"] and "12,000,000" in f.title


def test_list_amount_matching_the_original_is_fine():                                  # 민사
    d = doc("첨부 영수증(사본)", "영수증: 치료비 금 1,200,000원을 영수함",
            tables=[[HEADER, ["갑 제5호증", "영수증", "2023. 4. 1.", "1,200,000원"]]])
    assert not [f for f in check_exhibits(d) if f.confidence_features.get("rule_id") == "EVI.LIST_AMOUNT_MISMATCH"]


@pytest.mark.parametrize("party", ["갑", "을", "증"])
def test_duplicate_exhibit_number(party):
    rows = [["호증", "증거명", "작성일"], [f"{party} 제5호증", "영수증", "2023. 4. 1."], [f"{party} 제5호증", "급여명세서", "2023. 2. 28."]]
    if party == "증":
        rows = [["호증", "증거명", "작성일"], ["을 제1호증", "처분서", "2024. 2. 1."], ["을 제1호증", "의견제출서", "2024. 1. 20."]]
    found = [f for f in check_exhibits(doc("증거목록", tables=[rows]))
             if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(found) == 1 and found[0].evidence_grade.value == "A"


def test_branch_numbers_are_not_duplicates():
    rows = [["호증", "증거명", "작성일"], ["갑 제2호증의 1", "사진", "2023. 3. 15."], ["갑 제2호증의 2", "사진", "2023. 3. 15."]]
    assert not [f for f in check_exhibits(doc("증거목록", tables=[rows]))
                if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]


def _signed_doc(*lines, footer="원고 소송대리인 변호사 이○○", tables=()):
    blocks = [Block(block_id=f"b{i}", text=t, page=1) for i, t in enumerate(lines)]
    blocks.append(Block(block_id="foot", text=footer, page=1, block_type="running_head"))
    d = NormalizedDocument(document_id="S", filename="S.pdf", mime_type="application/pdf", sha256="0",
                           pages=[Page(page_number=1, blocks=blocks)])
    d.structure["tables"] = [{"table_ref": f"t{i}", "page": 1, "cells": c} for i, c in enumerate(tables)]
    return d


def test_filing_date_found_from_footer_signature_and_later_exhibit_flagged():          # 민사
    table = [["호증", "증거명", "작성일"], ["갑 제4호증", "사실확인서", "2024. 6. 1."]]
    d = _signed_doc("원고는 2023. 3. 15. 사고로 부상을 입었다.", "이상과 같이 주장합니다.", "2024. 5. 20.", tables=[table])
    assert str(document_date(d)) == "2024-05-20"
    assert any(f.type == FindingType.EVIDENCE_TIMELINE_INVERSION and "사실확인서" in f.title for f in check_exhibits(d))


def test_incident_report_written_before_the_incident():                                 # 민사
    table = [["호증", "증거명", "작성일", "입증취지"], ["갑 제3호증", "사고경위서", "2023. 1. 10.", "사고 발생 경위"],
             ["갑 제5호증", "영수증", "2023. 4. 1.", "치료비 지출"]]
    d = doc("원고는 2023. 3. 15. 작업 중 사고로 부상을 입었다.",
            "원고의 청구권은 사고일인 2023. 3. 15.부터 3년이 경과한 2026. 9. 15. 소멸한다.", tables=[table])
    inversions = [f for f in check_exhibits(d) if f.type == FindingType.EVIDENCE_TIMELINE_INVERSION]
    assert [("사고경위서" in f.title) for f in inversions] == [True]   # 영수증(사고 뒤)은 오탐하지 않는다
