"""v5 3-8: 본문·OCR 글의 달력에 없는 날짜, OCR 숫자 오인식 보정, OCR 신뢰도를 판정 등급에 반영.

재현(일반화): 돌려 스캔한 쪽에서 한글 금액 불일치는 잡았지만 같은 쪽의 불가능한 날짜는 놓쳤다. 날짜 형식 검사가
인용·증거표에만 있었고 OCR 숫자 오인식 보정이 없었다. 문서·날짜는 모두 시험용 합성이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from packages.claim_engine.calendar_dates import calendar_date_findings, normalize_ocr_dates
from packages.common.enums import EvidenceGrade
from packages.common.schemas import Block, NormalizedDocument, Page
from scripts.audit.corpus import _append_scan_page, build_pdf


def _pdf(tmp_path: Path, name: str, body, *, scan=None, rotate=0):
    from packages.document_engine.registry import parse_document

    path = build_pdf({"name": name, "header": "합성 시험 문서", "footer": "시험용 가상 문서", "body": body},
                     tmp_path / f"{name}.pdf")
    if scan:
        _append_scan_page(path, scan, rotate=rotate)
    return parse_document(str(path), document_id=name, filename=path.name, mime_type="application/pdf", sha256="0" * 64)


def _ocr_doc(text: str, confidence: float):
    block = Block(block_id="o1", text=text, page=1, block_type="paragraph", source_layer="ocr_layer",
                  attributes={"ocr_confidence": confidence})
    return NormalizedDocument(document_id="scan", filename="scan.pdf", mime_type="application/pdf", sha256="0",
                              pages=[Page(page_number=1, blocks=[block])])


@pytest.mark.parametrize("raw, fixed", [
    ("지급기일 2O26. 4. 3l. 까지", "2026. 4. 31."), ("합의일 2025, 2, 29,", "2025. 2. 29."), ("2O2S. 6. 3I.", "2025. 6. 31.")])
def test_ocr_digit_confusions_are_corrected_inside_date_tokens(raw, fixed):
    text, changes = normalize_ocr_dates(raw)
    assert fixed in text and changes


def test_words_are_not_turned_into_dates():
    assert normalize_ocr_dates("Section l. 2. 3. 및 Blood. 1. 2.")[1] == []


# --- 민사: 텍스트 PDF 본문의 불가능한 날짜 -------------------------------------------------------
def test_civil_settlement_payment_date_not_on_calendar(tmp_path):
    doc = _pdf(tmp_path, "civil", [("h", "합 의 서"), ("p", "갑은 을에게 합의금을 지급기일 2026. 4. 31.까지 지급한다."),
                                   ("p", "당사자는 2024. 2. 29. 합의 내용을 확인하였다.")])
    [finding] = calendar_date_findings(doc)
    assert finding.confidence_features["written_date"] == "2026. 4. 31." and finding.evidence_grade == EvidenceGrade.A
    assert not finding.confidence_features["ocr"]


# --- 형사: OCR 글자층의 오인식 날짜와 신뢰도별 등급 ------------------------------------------------
@pytest.mark.parametrize("confidence, grade", [(0.95, EvidenceGrade.B), (0.7, EvidenceGrade.B), (0.4, EvidenceGrade.C)])
def test_criminal_ocr_date_grade_follows_confidence_and_correction(confidence, grade):
    [finding] = calendar_date_findings(_ocr_doc("피해자와의 합의일 2O26. 2. 3O. 에 합의금 전액을 지급하였다.", confidence))
    features = finding.confidence_features
    assert features["written_date"] == "2026. 2. 30." and features["ocr"] and features["ocr_corrections"]
    assert finding.evidence_grade == grade  # 보정했으면 신뢰도가 높아도 A가 아니다
    assert "원본 이미지로 확인" in finding.detail


def test_clean_ocr_with_high_confidence_is_grade_a():
    [finding] = calendar_date_findings(_ocr_doc("공판기일은 2026. 11. 31. 로 지정되었다.", 0.93))
    assert finding.evidence_grade == EvidenceGrade.A


# --- 행정: 이미 판정한 인용 날짜는 중복하지 않고, 윤년 날짜는 판정하지 않는다 ----------------------------
def test_admin_existing_citation_verdict_is_not_duplicated(tmp_path):
    from packages.legal_engine.citation_extractor import extract_citations
    from packages.legal_engine.verifier import LegalVerifier
    from types import SimpleNamespace

    doc = _pdf(tmp_path, "admin", [
        ("h", "소 장(과징금부과처분 취소)"), ("p", "피고는 2025. 6. 31. 원고에게 과징금 부과처분을 하였다."),
        ("p", "대법원 2019. 2. 30. 선고 2018두47215 판결 참조."), ("p", "처분서는 2024. 2. 29. 작성되었다.")])

    class Law:
        def search_case(self, query, court=None):
            return SimpleNamespace(status="UNAVAILABLE", records=[], source_record=None, message="", found=False)
    existing = LegalVerifier(SimpleNamespace(law=Law())).verify_citations(extract_citations(doc),
                                                                         current_date="2026-09-25").findings
    dates = [f.confidence_features["written_date"] for f in calendar_date_findings(doc, existing)]
    assert dates == ["2025. 6. 31."]


# --- 돌려 스캔한 쪽(OCR) -------------------------------------------------------------------------
def test_rotated_scan_page_impossible_date_is_found(tmp_path):
    from packages.document_engine.ocr_readiness import probe_tesseract

    if not probe_tesseract("kor+eng").get("available"):
        pytest.skip("tesseract kor 없음")
    doc = _pdf(tmp_path, "rotated", [("h", "합의서 사본 첨부")],
               scan=["합 의 서", "합의금 지급기일: 2026. 4. 31.", "합의금: 금 이천만원정"], rotate=90)
    found = [f for f in calendar_date_findings(doc) if f.confidence_features["written_date"] == "2026. 4. 31."]
    assert found and found[0].confidence_features["ocr"]
