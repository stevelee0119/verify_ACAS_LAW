"""v3 §3-5 보강: 소계가 있는 표의 계층 검산과 만료일 재계산(민사·형사·가사·행정 합성 문장)."""
from __future__ import annotations

import pytest

from packages.claim_engine.calculation import CalculationEngine
from packages.claim_engine.fact_checks import check_periods
from tests.test_verification_regressions import document


def table(rows):
    return document("표", tables=[{"table_ref": "t1", "page": 1, "cells": rows}])


@pytest.mark.parametrize("rows, difference", [
    # 민사 손해액: 소계는 맞고 합계만 틀림(소계 7,100,000 + 위자료 5,000,000 = 12,100,000)
    ([["항목", "금액"], ["치료비", "1,200,000원"], ["일실수입", "3,400,000원"], ["간병비", "2,500,000원"],
      ["소계", "7,100,000원"], ["위자료", "5,000,000원"], ["합계", "12,700,000원"]], "600,000"),
    # 가사 재산목록: 소계가 틀림
    ([["재산", "금액"], ["예금", "10,000,000원"], ["보험", "5,000,000원"], ["소계", "16,000,000원"],
      ["아파트", "300,000,000원"], ["합계", "316,000,000원"]], "1,000,000"),
])
def test_subtotal_segments_are_checked_separately(rows, difference):
    titles = [f.title for f in CalculationEngine().verify_document(table(rows))]
    assert len(titles) == 1 and difference in titles[0], titles


def test_consistent_table_with_subtotal_has_no_finding():
    # 행정 과징금 산정표: 소계·합계 모두 맞음(소계 행을 항목으로 다시 더하지 않는다)
    rows = [["구분", "금액"], ["기본 과징금", "2,000,000원"], ["가중", "500,000원"], ["소계", "2,500,000원"],
            ["감경", "-300,000원"], ["합계", "2,200,000원"]]
    assert CalculationEngine().verify_document(table(rows)) == []


@pytest.mark.parametrize("sentence, stated", [
    ("원고의 청구권은 사고일인 2023. 3. 15.부터 3년이 경과한 2026. 9. 15. 소멸한다.", "2026. 9. 15."),            # 민사
    ("피고인의 공소시효는 범행일인 2015. 1. 10.부터 7년이 경과한 2022. 7. 10. 완성되었다.", "2022. 7. 10."),        # 형사
    ("이혼한 날인 2020. 5. 1.부터 2년이 경과한 2022. 11. 1. 재산분할청구권이 소멸하였다.", "2022. 11. 1."),          # 가사
    ("처분이 있음을 안 2023. 1. 2.부터 90일이 경과한 2023. 6. 30. 제소기간이 도과하였다.", "2023. 6. 30."),          # 행정
])
def test_stated_expiry_later_than_calculated_is_flagged(sentence, stated):
    found = [f for f in check_periods(document(sentence)) if f.confidence_features.get("rule_id") == "CALC.EXPIRY_DATE"]
    assert found and f"문서 {stated}" in found[0].title and "민법 제157조" in found[0].detail


@pytest.mark.parametrize("sentence", [
    "원고가 손해를 안 2023. 3. 15.부터 3년이 경과한 2026. 3. 15. 무렵까지는 시효가 완성되지 않는다.",
    "처분일인 2020. 1. 1.부터 1년이 경과한 2024. 6. 1. 현재 제소기간이 도과하였다.",
    "2020. 1. 1.부터 1년이 경과한 2024. 6. 1. 시효가 완성되지 않았다.",
    "사고일인 2023. 3. 15.부터 3년이 경과한 2026. 3. 15. 소멸한다.",
])
def test_correct_or_non_expiry_statements_are_not_flagged(sentence):
    assert check_periods(document(sentence)) == []
