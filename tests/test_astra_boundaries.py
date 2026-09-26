"""Synthetic acceptance regressions; no blind answer keys."""


import pytest

from packages.claim_engine.calculation import CalculationEngine
from packages.claim_engine.cross_document_entities import verify_cross_document_entities
from packages.common.schemas import Block, NormalizedDocument, Page
from scripts.eval_v4_scoring import REQUIRED_DOCUMENT_ENGINES, score


def calculate(cells):
    doc = NormalizedDocument(
        document_id="synthetic", filename="synthetic.pdf",
        mime_type="application/pdf", sha256="0" * 64,
        pages=[Page(page_number=1, blocks=[Block(block_id="b", text="", page=1)])],
    )
    doc.structure["tables"] = [{"table_ref": "t", "page": 1, "cells": cells}]
    findings = CalculationEngine().verify_document(doc)
    return [{"status": f.status.value, "grade": f.evidence_grade.value,
             "title": f.title, "features": f.confidence_features} for f in findings]


def finding(fid, kind, title, status="CONTRADICTED", advisory=False):
    return {"finding_id": fid, "document_id": "D-01", "type": kind,
            "status": status, "severity": "HIGH", "evidence_grade": "A",
            "advisory_only": advisory, "page": 1, "title": title,
            "detail": "", "evidence": [{"excerpt": title}], "confidence_features": {}}


def report_doc(ident, findings, *, pages=True):
    return {"document_id": ident, "filename": ident + ".pdf", "findings": findings,
            "page_coverage": [{"page": 1, "status": "EXTRACTED"}] if pages else []}


def evaluate(items, findings, *, control_pages=True):
    gt = {"documents": [{"id": "D-01", "items": items}, {"id": "D-05", "items": []}]}
    report = {"documents": [report_doc("D-01", findings),
                             report_doc("D-05", [], pages=control_pages)],
              "run_manifest": {}, "project_findings": []}
    return score(gt, report)


def test_mixed_currency_units_must_not_create_false_arithmetic_proof():
    results = calculate([
        ["품목", "공급가액(천원)", "세액(원)", "합계금액(원)"],
        ["용역", "100", "10,000", "110,000"],
    ])
    assert not [f for f in results if f["status"] == "CONTRADICTED"], results


def test_negative_deduction_refund_must_preserve_sign():
    results = calculate([
        ["성명", "지급총액", "공제총액", "실지급액"],
        ["직원", "1,000,000", "-100,000", "1,100,000"],
    ])
    assert not [f for f in results if f["status"] == "CONTRADICTED"], results


def test_unreadable_interest_must_not_be_assumed_zero():
    results = calculate([
        ["구분", "금액"], ["원금", "10,000,000"], ["이자", "판독 불가"],
        ["기변제액", "1,000,000"], ["잔존채권액", "9,500,000"],
    ])
    assert not [f for f in results if f["status"] == "CONTRADICTED"], results


def test_matching_article_number_from_a_different_law_is_not_a_hit():
    result = evaluate([["LAW-MIS", "p.1", "근로기준법 제23조", "인용 오류"]], [
        finding("law", "LAW_CITATION_ERROR", "민법 제23조 인용 오류"),
    ])
    assert result["metrics"]["confirmed_hits"] == 0, result["items"]


def test_control_without_extraction_or_execution_evidence_is_incomplete():
    result = evaluate([["ARITH", "p.1", "합계 12,500,000원", "합계 오류"]], [], control_pages=False)
    control = next(d for d in result["coverage"]["per_document"] if d["doc"] == "D-05")
    assert control["control_status"] == "INCOMPLETE", control


def test_precision_must_not_exceed_one_when_ocr_abstention_is_correct():
    result = evaluate([
        ["ARITH", "p.1", "합계 12,500,000원", "합계 오류"],
        ["OCR-REQ", "p.1", "스캔 이미지", "판독 불가 고지"],
    ], [
        finding("arithmetic", "ARITHMETIC_MISMATCH", "합계 12,500,000원 오류"),
        finding("ocr", "OCR_LOW_QUALITY", "스캔 이미지 판독 불가", status="UNVERIFIED", advisory=True),
    ])
    precision = result["metrics"]["precision_lower_bound"]
    assert precision is None or 0 <= precision <= 1, result["metrics"]


def test_different_named_plaintiffs_in_one_case_must_not_be_one_person():
    docs = []
    for ident, text in [
        ("A", "사건 2024가합12345\n원고 김갑수는 2021. 3. 4. 입사하였습니다."),
        ("B", "사건 2024가합12345\n원고 이을수는 2021. 4. 3. 입사하였습니다."),
    ]:
        docs.append(NormalizedDocument(
            document_id=ident, filename=ident + ".pdf", mime_type="application/pdf", sha256="0" * 64,
            pages=[Page(page_number=1, blocks=[Block(block_id=ident, text=text, page=1)])],
        ))
    results = verify_cross_document_entities(docs)
    assert not [f for f in results if f.status.value == "CONTRADICTED"], [
        {"title": f.title, "status": f.status.value, "grade": f.evidence_grade.value,
         "features": f.confidence_features} for f in results
    ]


@pytest.mark.parametrize("unit, supply", [("천원", "100"), ("만원", "10"), ("백만원", "0.1")])
@pytest.mark.parametrize("total, mismatches", [("110,000", 0), ("120,000", 1)])
def test_unit_conversion_preserves_real_error_detection(unit, supply, total, mismatches):
    results = calculate([["품목", f"공급가액({unit})", "세액(원)", "합계금액(원)"],
                         ["용역", supply, "10,000", total]])
    assert len(results) == mismatches
    if mismatches:
        assert results[0]["features"]["computed"] == "110000.0" or results[0]["features"]["computed"] == "110000"


@pytest.mark.parametrize("interest", ["판독 불가", "", None, "500,000원?", "약 500,000원"])
@pytest.mark.parametrize("vertical", [True, False])
def test_present_but_unknown_optional_component_blocks_proof(interest, vertical):
    cells = [["구분", "금액"], ["원금", "10,000,000"], ["이자", interest],
             ["기변제액", "1,000,000"], ["잔존채권액", "9,500,000"]] if vertical else [
                 ["구분", "원금", "이자", "기변제액", "잔존채권액"],
                 ["채무", "10,000,000", interest, "1,000,000", "9,500,000"]]
    assert calculate(cells) == []


def test_optional_component_absent_and_numeric_zero_are_not_unknown():
    assert calculate([["구분", "원금", "기변제액", "잔존채권액"], ["채무", 100000, 0, 100000]]) == []
    wrong = calculate([["구분", "원금", "기변제액", "잔존채권액"], ["채무", 100000, 0, 90000]])
    assert len(wrong) == 1 and wrong[0]["features"]["difference"] == "-10000"


def test_explicit_cell_currency_is_not_scaled_twice():
    assert calculate([["품목", "공급가액(천원)", "세액(원)", "합계금액(원)"],
                      ["용역", "100,000원", "10,000", "110,000"]]) == []


def test_negative_deduction_still_detects_wrong_net_payment():
    results = calculate([["성명", "지급총액", "공제총액", "실지급액"],
                         ["직원", "1,000,000", "-100,000", "900,000"]])
    assert len(results) == 1 and results[0]["features"]["computed"] == "1100000"


@pytest.mark.parametrize("target, text, hits", [
    ("근로기준법 제23조", "근로기준법 제23조 인용 오류", 1),
    ("근로기준법 제23조", "근로기준법 제230조 인용 오류", 0),
    ("근로기준법 제23조", "근로기준법 시행령 제23조 인용 오류", 0),
    ("근로기준법 제23조 제1항", "근로기준법 제23조 제2항 인용 오류", 0),
    ("근로기준법 제23조의2", "근로기준법 제23조 인용 오류", 0),
    ("민법 제23조", "근로기준법 제23조와 민법 제24조 인용 오류", 0),
    ("민법 제23조", "민법 제23조 인용 오류", 1),
])
def test_statute_identity_includes_law_level_article_and_paragraph(target, text, hits):
    result = evaluate([["LAW-MIS", "p.1", target, ""]], [finding("law", "LAW_CITATION_ERROR", text)])
    assert result["metrics"]["confirmed_hits"] == hits, result["items"]


def test_correct_abstention_is_not_a_defect_hit_or_precision_numerator():
    result = evaluate([["OCR-REQ", "p.1", "스캔 이미지", ""]], [
        finding("ocr", "OCR_LOW_QUALITY", "스캔 이미지 판독 불가", status="UNVERIFIED", advisory=True)])
    assert result["items"][0]["result"] == "CORRECT_ABSTENTION"
    assert result["metrics"]["correct_abstentions"] == 1
    assert result["metrics"]["confirmed_hits"] == result["metrics"]["defect_items_scorable"] == 0
    assert result["metrics"]["precision_lower_bound"] is None


def control_report(*, pages=True):
    return {"documents": [report_doc("D-05", [], pages=pages)], "run_manifest": {"engines": {
        name: {"executed": True, "documents": [{"document_id": "D-05", "inputs": 1}]}
        for name in ("parsing", *REQUIRED_DOCUMENT_ENGINES)}}}


@pytest.mark.parametrize("pages", [True, False])
def test_control_pass_requires_positive_extraction_and_execution_evidence(pages):
    report = control_report(pages=pages)
    result = score({"documents": [{"id": "D-05", "items": []}]}, report)
    assert result["evaluation_status"] == "COMPLETE"
    assert result["coverage"]["per_document"][0]["control_status"] == "PASS"


@pytest.mark.parametrize("failure", ["missing", "skipped", "error", "another_document"])
def test_control_cannot_pass_when_a_required_engine_did_not_complete(failure):
    report = control_report()
    engines = report["run_manifest"]["engines"]
    if failure == "missing":
        del engines["arithmetic"]
    elif failure == "another_document":
        engines["arithmetic"]["documents"][0]["document_id"] = "OTHER"
    else:
        engines["arithmetic"]["documents"][0][failure] = "not completed"
    result = score({"documents": [{"id": "D-05", "items": []}]}, report)
    assert result["evaluation_status"] == "INCOMPLETE"
    assert result["coverage"]["per_document"][0]["coverage"] == "EXECUTION_INCOMPLETE"


def test_empty_pageless_parse_is_not_positive_extraction_evidence():
    report = control_report(pages=False)
    report["run_manifest"]["engines"]["parsing"]["documents"][0]["inputs"] = 0
    result = score({"documents": [{"id": "D-05", "items": []}]}, report)
    assert result["coverage"]["per_document"][0]["coverage"] == "EXTRACTION_INCOMPLETE"


@pytest.mark.parametrize("first, second, expected", [
    ("원고 김○○는", "원고 김○○는", "CONTRADICTED"),
    ("원고 김○○는", "원고 이○○는", None),
    ("원고는", "원고는", "SUSPICIOUS"),
    ("원고 김○○\n원고는", "원고 김○○\n원고는", "CONTRADICTED"),
    ("원고 김○○\n원고 김갑수는", "원고 김○○\n원고 이을수는", "SUSPICIOUS"),
])
def test_identity_evidence_not_role_controls_cross_document_promotion(first, second, expected):
    docs = [NormalizedDocument(document_id=ident, filename=ident + ".pdf", mime_type="application/pdf", sha256="0",
                               pages=[Page(page_number=1, blocks=[Block(block_id=ident, page=1,
                                   text=f"사건 2024가합12345\n{prefix} {date} 입사하였습니다.")])])
            for ident, prefix, date in [("A", first, "2021. 3. 4."), ("B", second, "2021. 4. 3.")]]
    findings = verify_cross_document_entities(docs)
    assert [f.status.value for f in findings] == ([expected] if expected else [])
    if expected == "CONTRADICTED":
        assert findings[0].confidence_features["subject_identity"] == "김○○"


def test_another_named_party_does_not_hide_conflicts_for_the_same_person():
    docs = [NormalizedDocument(document_id=ident, filename=ident + ".pdf", mime_type="application/pdf", sha256="0",
                               pages=[Page(page_number=1, blocks=[Block(block_id=ident, page=1,
                                   text=f"사건 2024가합12345\n원고 {name}는 {date} 입사하였습니다.")])])
            for ident, name, date in [("A", "김○○", "2021. 3. 4."), ("B", "김○○", "2021. 4. 3."),
                                      ("C", "이○○", "2022. 2. 2.")]]
    findings = verify_cross_document_entities(docs)
    assert len(findings) == 1 and findings[0].status.value == "CONTRADICTED"
    assert set(findings[0].confidence_features["documents"]) == {"A.pdf", "B.pdf"}


@pytest.mark.parametrize("balance, expected", [("95,000", 0), ("90,000", 1)])
def test_vertical_formula_uses_row_units(balance, expected):
    results = calculate([["구분", "금액"], ["원금(만원)", "10"], ["이자(원)", "5,000"],
                         ["기변제액(천원)", "10"], ["잔존채권액(원)", balance]])
    assert len(results) == expected
