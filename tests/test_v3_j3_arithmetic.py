"""추가지시 J3: 금액 표·내역에서 산식이 든 행을 건너뛰지 않는다. 행마다 최종 금액을 쓰고 산식은 따로 검산한다."""
from __future__ import annotations

from decimal import Decimal

from packages.claim_engine.calculation import CalculationEngine
from packages.common.schemas import Block, NormalizedDocument, Page


def doc(lines=(), tables=()):
    blocks = [Block(block_id=f"b{i}", text=t, page=1) for i, t in enumerate(lines)]
    page = Page(page_number=1, blocks=blocks)
    d = NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0", pages=[page])
    d.structure["tables"] = [{"table_ref": f"t{i}", "page": 1, "cells": cells} for i, cells in enumerate(tables)]
    return d


def test_reproduction_formula_row_is_included_with_its_final_amount():
    # 국가배상: 치료비 산식 행이 있는 손해액 내역
    findings = CalculationEngine().verify_document(doc([
        "가. 치료비: 3,100,000원 + 1,250,000원 = 4,350,000원",
        "나. 일실수입: 12,000,000원",
        "다. 위자료: 10,000,000원",
        "합계: 33,000,000원",
    ]))
    [f] = findings
    assert Decimal(f.confidence_features["computed"]) == Decimal("26350000")
    assert Decimal(f.confidence_features["difference"]) == Decimal("6650000")
    assert any("치료비" in row for row in f.confidence_features["rows_used"])


def test_synthetic_wrong_formula_is_reported_separately():
    # 민사: 대여금 원리금 산식 자체가 틀림
    findings = CalculationEngine().verify_document(doc(["원리금: 50,000,000원 + 4,000,000원 = 45,000,000원"]))
    assert any("산식" in f.title and Decimal(f.confidence_features["computed"]) == Decimal("54000000")
               for f in findings)


def test_synthetic_table_uses_the_amount_column_and_formula_cells():
    # 형사: 피해액 표(산식 칸 + 금액 칸)
    table = [["항목", "산식", "금액"],
             ["현금", "", "2,000,000원"],
             ["물품", "500,000원 × 3", "1,500,000원"],
             ["수리비", "700,000원 + 300,000원 = 1,000,000원", "1,000,000원"],
             ["합계", "", "5,000,000원"]]
    [f] = CalculationEngine().verify_document(doc(tables=[table]))
    assert Decimal(f.confidence_features["computed"]) == Decimal("4500000")
    assert len(f.confidence_features["rows_used"]) == 3


def test_synthetic_correct_totals_are_silent():
    assert CalculationEngine().verify_document(doc([
        "1. 임대료 미지급분: 1,200,000원 + 1,200,000원 = 2,400,000원",
        "2. 관리비: 300,000원",
        "합계: 2,700,000원",
    ])) == []
