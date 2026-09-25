"""v5 3-3·3-5: 증거표를 열 구조로 알아보기, 모든 증거표에 날짜·번호·작성일 검사, '금 …원정 (₩…)' 병기 대조,
파생 비율(%) 재계산과 원인 연결, 같은 합계에 대한 판정 하나로 병합.

문서·금액·성명은 모두 시험용 합성이다(블라인드 문장·표를 쓰지 않는다). 분야: 형사·민사·가사·행정.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from packages.claim_engine.calculation import CalculationEngine
from packages.claim_engine.evidence_consistency import check_document, exhibit_rows
from packages.claim_engine.korean_amount import words_digits_mismatches
from scripts.audit.corpus import build_pdf


def _doc(tmp_path: Path, name: str, body):
    from packages.document_engine.registry import parse_document

    path = build_pdf({"name": name, "header": "합성 시험 문서", "footer": "시험용 가상 문서", "body": body},
                     tmp_path / f"{name}.pdf")
    return parse_document(str(path), document_id=name, filename=path.name, mime_type="application/pdf", sha256="0" * 64)


def _all(doc):
    return CalculationEngine().verify_document(doc) + words_digits_mismatches(doc) + check_document(doc)


def _titles(findings):
    return [f.title for f in findings if str(f.status) == "CONTRADICTED"]


# --- 형사: 표준이 아닌 머리글의 양형자료 표 --------------------------------------------------------
def test_criminal_sentencing_table_is_recognised_by_its_columns(tmp_path):
    doc = _doc(tmp_path, "criminal", [
        ("h", "양형자료 제출서"),
        ("table", [["연번", "내용", "일시", "비고"],
                   ["증 제1호증", "합의서", "2026. 3. 2.", "피해자와 합의"],
                   ["증 제2호증", "탄원서", "2026. 2. 30.", "가족 탄원"],
                   ["증 제2호증", "반성문", "2026. 3. 5.", "반성"],
                   ["증 제3호증", "재직증명서", "2026. 10. 1.", "재직"]]),
        ("p", "피고인은 피해자에게 금 칠백만원정 (₩7,500,000)을 지급하였습니다."),
        ("p", "2026. 9. 1."), ("p", "피고인의 변호인 변호사 ○○○ (인)")])
    assert len(exhibit_rows(doc)) == 4
    titles = " ".join(_titles(_all(doc)))
    assert "달력에 없는 날짜다: 증 제2호증" in titles
    assert "같은 호증 번호가 두 번 쓰였다: 증 제2호증" in titles
    assert "서면의 작성일보다 뒤다: 증 제3호증" in titles
    assert "'칠백만'=7,000,000원 / 숫자 7,500,000원" in titles


# --- 민사: 틀린 합계에서 나온 비율 → 원인은 합계 칸 -------------------------------------------------
def test_civil_percentages_derived_from_wrong_total_point_to_the_total(tmp_path):
    doc = _doc(tmp_path, "civil", [
        ("h", "손해배상 청구 내역"),
        ("table", [["항목", "금액", "비율"], ["치료비", "1,000,000원", "20%"], ["일실수입", "2,000,000원", "40%"],
                   ["위자료", "1,000,000원", "20%"], ["합계", "5,000,000원", "100%"]]),
        ("p", "피고는 원고에게 일금 오백만원정(￦5,000,000-)을 지급하라.")])
    findings = CalculationEngine().verify_document(doc)
    total = [f for f in findings if "합계가 세부 금액" in f.title]
    percent = [f for f in findings if f.confidence_features.get("rule_id") == "CALC.PERCENT_MISMATCH"]
    assert len(total) == 1 and len(percent) == 1
    assert percent[0].confidence_features["cause"] == "STATED_TOTAL"
    assert percent[0].confidence_features["cause_finding"] == total[0].finding_id
    assert total[0].confidence_features["derived_effects"]
    assert words_digits_mismatches(doc) == []  # 오백만원 = 5,000,000원(일치)


# --- 가사: 비율 계산 자체의 오류와 작성자 성명 불일치 ------------------------------------------------
def test_family_percentage_error_and_statement_name_mismatch(tmp_path):
    doc = _doc(tmp_path, "family", [
        ("h", "재산분할 대상 재산"),
        ("table", [["재산", "금액", "구성비"], ["아파트", "400,000,000원", "60%"], ["예금", "200,000,000원", "30%"],
                   ["합계", "600,000,000원", "100%"]]),
        ("h", "증거 목록"),
        ("table", [["호증", "서증명", "작성일", "작성자", "입증취지"],
                   ["갑 제1호증", "혼인관계증명서", "2026. 5. 1.", "○○구청", "혼인 사실"],
                   ["갑 제2호증", "사실확인서", "2026. 5. 3.", "이○○", "별거 사실"]]),
        ("p", "[갑 제2호증] 사실확인서"), ("p", "성 명: 박○○"), ("p", "위 사람은 2025. 3.부터 별거하였음을 확인합니다."),
        ("p", "2026. 6. 1."), ("p", "위 원고 소송대리인 변호사 ○○○ (인)")])
    findings = _all(doc)
    percent = [f for f in findings if f.confidence_features.get("rule_id") == "CALC.PERCENT_MISMATCH"]
    assert percent and percent[0].confidence_features["cause"] == "PERCENT_CALCULATION"
    assert not [f for f in findings if "합계가 세부 금액" in f.title]  # 합계는 맞다
    names = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.PERSON_NAME_MISMATCH"]
    assert names and "이○○ ↔ 박○○" in names[0].title


# --- 행정: 같은 합계에 대한 판정은 하나(칸 단위·줄 단위 이중 판정 병합) --------------------------------
def test_admin_same_total_is_judged_once_with_all_items(tmp_path):
    doc = _doc(tmp_path, "admin", [
        ("h", "과징금 산정 내역"),
        ("table", [["구분", "금액"], ["기본 산정액", "3,000,000원"], ["1차 가중", "1,200,000원"],
                   ["2차 가중", "600,000원"], ["합계", "6,000,000원"]])])
    sums = [f for f in CalculationEngine().verify_document(doc) if "합계가 세부 금액" in f.title]
    assert len(sums) == 1
    assert sums[0].confidence_features["computed"] == "4800000" and sums[0].confidence_features["item_count"] == 3


# --- 대조군: 맞는 표·병기는 아무것도 내지 않는다(3분야) ----------------------------------------------
@pytest.mark.parametrize("name, body", [
    ("civil_ok", [("table", [["항목", "금액", "비율"], ["치료비", "1,000,000원", "25%"], ["일실수입", "2,000,000원", "50%"],
                             ["위자료", "1,000,000원", "25%"], ["합계", "4,000,000원", "100%"]]),
                  ("p", "피고는 원고에게 금 사백만원정 (₩4,000,000)을 지급하라.")]),
    ("family_ok", [("table", [["재산", "금액", "구성비"], ["아파트", "400,000,000원", "66.7%"],
                              ["예금", "200,000,000원", "33.3%"], ["합계", "600,000,000원", "100%"]])]),
    ("criminal_ok", [("table", [["연번", "내용", "일시", "비고"], ["증 제1호증", "합의서", "2026. 3. 2.", "합의"],
                                ["증 제2호증", "탄원서", "2026. 3. 4.", "탄원"]]),
                     ("p", "2026. 9. 1."), ("p", "피고인의 변호인 변호사 ○○○ (인)")]),
])
def test_consistent_tables_produce_no_contradiction(tmp_path, name, body):
    assert _titles(_all(_doc(tmp_path, name, body))) == []
