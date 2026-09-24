"""추가지시 G2: 한국어 OCR 품질.

- 쪽별 OCR 신뢰도와 한글 비율을 재고, 기준에 못 미치면 OCR_LOW_QUALITY로 표시해 그 쪽의 '결함 없음'을 막는다.
- 한글 OCR이 음절마다 띄어 읽은 글자를 붙여 날짜·사건번호 형식 검사가 OCR 텍스트에도 걸리게 한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from packages.document_engine.ocr import OCRLine, get_ocr_adapter, normalize_ocr_spacing, page_quality
from packages.legal_engine.citation_extractor import extract_from_text

NANUM = Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")


def _lines(*items):
    return [OCRLine(text=text, page=1, confidence=conf) for text, conf in items]


# --- 쪽별 품질 -----------------------------------------------------------------------
def test_garbled_korean_page_is_low_quality():
    """한국어 모델로 읽었는데 한글이 로마자로 깨진 쪽('의 xj ot AOO')."""
    quality = page_quality(_lines(("의 xj ot AOO ll ahd tk", 0.62), ("sjdl dkf ekt xhd dmf", 0.58)), lang="kor+eng")
    assert quality["low_quality"] and any("한글 비율" in r for r in quality["reasons"])


def test_low_confidence_page_is_low_quality_even_with_hangul():
    quality = page_quality(_lines(("피고는 원고에게 금원을 지급하라", 0.41), ("청구원인 사건의 개요", 0.52)), lang="kor+eng")
    assert quality["low_quality"] and any("신뢰도" in r for r in quality["reasons"])


def test_clean_page_is_not_low_quality():
    quality = page_quality(_lines(("대법원 2019. 2. 3. 선고 2018두47215 판결", 0.92),
                                  ("원고는 피고에게 손해배상을 청구한다", 0.9)), lang="kor+eng")
    assert not quality["low_quality"] and quality["hangul_ratio"] > 0.8


def test_short_latin_terms_do_not_trigger_the_ratio_rule():
    """'abuse of discretion' 같은 짧은 영문 병기는 한글 비율 판단에 쓰기에 글자가 적다."""
    quality = page_quality(_lines(("재량권 남용(abuse)", 0.9)), lang="kor+eng")
    assert not quality["low_quality"]


# --- 음절 띄어 읽기 보정 ---------------------------------------------------------------
@pytest.mark.parametrize("raw,fixed", [
    ("헌 법 재판소 2021. 11. 31. 2020 헌 마 1127 결 정", "헌법 재판소 2021. 11. 31. 2020 헌마 1127 결정"),   # 헌법
    ("피 고 는 2024. 3. 5. 처 분 을 하였다.", "피고는 2024. 3. 5. 처분을 하였다."),                          # 행정
    ("원고의 청구를 기각한다", "원고의 청구를 기각한다"),                                                        # 민사(그대로)
])
def test_syllable_spacing_is_joined(raw, fixed):
    assert normalize_ocr_spacing(raw) == fixed


@pytest.mark.parametrize("text,number,date", [
    ("헌법 재판소 2021. 11. 31. 2020 헌마 1127 결정", "2020헌마1127", "2021-11-31"),
    ("대법원 2019. 2. 30. 선고 2018 두 47215 판결", "2018두47215", "2019-02-30"),
    ("서울고등법원 2023. 4. 31. 선고 2022 나 1234 판결", "2022나1234", "2023-04-31"),
])
def test_ocr_spaced_citations_keep_date_and_number_for_format_checks(text, number, date):
    [citation] = extract_from_text(text)
    assert citation.case_number == number and citation.decision_date == date


# --- 실제 엔진으로 만든 한국어 스캔 합성 문서 ---------------------------------------------
def _scanned_korean_pdf(tmp_path, lines):
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    font = ImageFont.truetype(str(NANUM), 34)
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((120, 200 + index * 90), line, font=font, fill="black")
    png = tmp_path / "page.png"
    image.save(png)
    target = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(target), pagesize=A4)
    c.drawImage(ImageReader(str(png)), 0, 0, width=A4[0], height=A4[1])
    c.save()
    return target


@pytest.mark.skipif(not NANUM.exists() or "kor" not in (get_ocr_adapter().diagnostics or {}).get("languages", []),
                    reason="한국어 OCR 데이터 또는 나눔고딕 글꼴이 없는 환경")
def test_korean_scan_yields_dates_and_case_numbers(tmp_path):
    from packages.document_engine import parse_document
    from packages.legal_engine.citation_extractor import extract_citations

    path = _scanned_korean_pdf(tmp_path, ["준 비 서 면",
                                          "원고는 대법원 2019. 2. 30. 선고 2018두47215 판결을 인용한다.",
                                          "헌법재판소 2021. 11. 31. 2020헌마1127 결정도 같은 취지이다."])
    doc = parse_document(str(path), document_id="D", filename="scan.pdf", mime_type="application/pdf", sha256="x")
    [coverage] = doc.structure["page_coverage"]
    assert coverage["status"] == "OCR_EXTRACTED" and coverage["ocr_quality"]["hangul_ratio"] > 0.5
    found = {c.case_number: c.decision_date for c in extract_citations(doc)}
    assert found.get("2018두47215") == "2019-02-30" and found.get("2020헌마1127") == "2021-11-31"


# --- 품질 미달 쪽은 '확인하지 못함'으로 남는다 -----------------------------------------------
def test_low_quality_scan_page_is_reported_and_blocks_a_clean_conclusion(tmp_path, monkeypatch):
    from test_ocr import _scanned_pdf, stub_ocr

    from packages.document_engine import parse_document
    from packages.common.enums import FindingType
    from packages.pii_engine import PseudonymStore
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    path = _scanned_pdf(tmp_path, ["placeholder"])
    garbled = [("의 xj ot AOO ll ahd tk sjdl", 0.8), ("dkf ekt xhd dmf qwe rty", 0.8)]
    with stub_ocr({1: garbled}):
        doc = parse_document(str(path), document_id="S", filename="s.pdf", mime_type="application/pdf", sha256="x")
    [coverage] = doc.structure["page_coverage"]
    assert coverage["status"] == "OCR_LOW_QUALITY"
    monkeypatch.setattr(module, "parse_document", lambda p, document_id=None, **kw: doc)
    monkeypatch.setattr(module, "PseudonymStore", lambda project_id: PseudonymStore(project_id, root=tmp_path))
    result = VerificationPipeline().run("run-g2", ProjectContext("project-g2"), [DocumentInput("S", "s.pdf", "s.pdf")])
    document = result.documents[0]
    assert any(f.type == FindingType.OCR_LOW_QUALITY and "확인하지 못함" in f.detail for f in document.findings)
    assert any(i.get("kind") == "page" and i.get("status") == "OCR_LOW_QUALITY" for i in document.unverified_items)
    assert result.scores["release_gate"]["release_gate"] != "PASS"
