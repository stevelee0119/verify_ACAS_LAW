"""제6장 Document Ingestion 및 정규화."""
from __future__ import annotations

import zipfile

import pytest
from helpers import make_docx, make_pdf

from packages.document_engine import ALLOWED_EXTENSIONS, guess_mime, parse_document, select_parser


def test_supported_formats_cover_spec():
    """제1.1장에서 요구한 형식을 지원한다."""
    required = {".pdf", ".docx", ".hwpx", ".hwp", ".txt", ".csv", ".xlsx", ".jpg", ".jpeg", ".png"}
    assert required <= set(ALLOWED_EXTENSIONS)


@pytest.mark.parametrize(
    "filename,parser",
    [
        ("a.pdf", "PdfParser"),
        ("a.docx", "DocxParser"),
        ("a.hwpx", "HwpxParser"),
        ("a.hwp", "HwpParser"),
        ("a.xlsx", "SpreadsheetParser"),
        ("a.csv", "SpreadsheetParser"),
        ("a.png", "ImageParser"),
        ("a.txt", "TextParser"),
    ],
)
def test_parser_selection(filename, parser):
    assert select_parser(guess_mime(filename), filename).name == parser


def test_pdf_preserves_page_and_bbox(tmp_path):
    path = make_pdf(tmp_path / "p.pdf", ["첫 번째 문단이다.", "두 번째 문단이다."])
    doc = parse_document(str(path), document_id="D", filename="p.pdf", mime_type="application/pdf", sha256="x")
    blocks = doc.visible_blocks()
    assert blocks
    for block in blocks:
        assert block.page == 1 and block.bbox is not None
        assert block.bbox.x1 > block.bbox.x0 and block.bbox.y1 > block.bbox.y0


def test_pdf_layers_are_separated(tmp_path):
    path = make_pdf(tmp_path / "l.pdf", ["표시되는 본문이다."], hidden=["숨겨진 문장이다."])
    doc = parse_document(str(path), document_id="D", filename="l.pdf", mime_type="application/pdf", sha256="x")
    assert "표시되는 본문" in doc.raw_layers["rendered_text"]
    assert "숨겨진 문장" not in doc.raw_layers["rendered_text"]
    assert "숨겨진 문장" in doc.raw_layers["hidden_text"]
    assert "숨겨진 문장" in doc.raw_layers["raw_text"]


def test_docx_structure_extraction(tmp_path):
    body = (
        "<w:p><w:r><w:t>본문 문단이다.</w:t></w:r></w:p>"
        '<w:p><w:ins w:author="A" w:date="2026-01-01T00:00:00Z"><w:r><w:t>삽입</w:t></w:r></w:ins>'
        '<w:del w:author="A" w:date="2026-01-01T00:00:00Z"><w:r><w:delText>삭제</w:delText></w:r></w:del></w:p>'
    )
    comments = '<w:comment w:id="1" w:author="B"><w:p><w:r><w:t>코멘트</w:t></w:r></w:p></w:comment>'
    path = make_docx(tmp_path / "d.docx", body, comments_xml=comments)
    doc = parse_document(str(path), document_id="D", filename="d.docx", mime_type="", sha256="x")
    assert doc.structure["tracked_inserts"][0]["text"] == "삽입"
    assert doc.structure["tracked_deletes"][0]["text"] == "삭제"
    assert doc.structure["comments"][0]["text"] == "코멘트"
    assert "삭제" not in doc.raw_layers["rendered_text"]


def test_unsupported_format_does_not_raise(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x00\x01\x02")
    doc = parse_document(str(path), document_id="D", filename="x.bin", mime_type="", sha256="x")
    assert doc.structure.get("unsupported_format") is True
    assert doc.parse_warnings


def test_corrupt_file_degrades_gracefully(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip at all")
    doc = parse_document(str(path), document_id="D", filename="broken.docx", mime_type="", sha256="x")
    assert doc.parse_warnings and "parse_error" in doc.structure


def test_zip_bomb_is_rejected(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"A" * 20_000_000)
    doc = parse_document(str(path), document_id="D", filename="bomb.docx", mime_type="", sha256="x")
    assert "parse_error" in doc.structure


def test_spreadsheet_hidden_sheet_detected(tmp_path):
    import openpyxl

    workbook = openpyxl.Workbook()
    visible = workbook.active
    visible.title = "본문"
    visible.append(["항목", "금액"])
    hidden = workbook.create_sheet("숨김시트")
    hidden.append(["비공개", 1000])
    hidden.sheet_state = "hidden"
    path = tmp_path / "s.xlsx"
    workbook.save(path)

    doc = parse_document(str(path), document_id="D", filename="s.xlsx", mime_type="", sha256="x")
    assert doc.structure["hidden_sheets"] == ["숨김시트"]


def test_scanned_pdf_flags_unverified(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.rect(100, 100, 200, 200, fill=0)
    c.save()
    doc = parse_document(str(path), document_id="D", filename="scan.pdf", mime_type="application/pdf", sha256="x")
    assert doc.structure.get("scanned_pdf") is True
    assert any("UNVERIFIED" in warning for warning in doc.parse_warnings)


def test_normalized_document_serialization(tmp_path):
    path = make_pdf(tmp_path / "n.pdf", ["본문이다."])
    doc = parse_document(str(path), document_id="D", filename="n.pdf", mime_type="application/pdf", sha256="x")
    data = doc.to_dict()
    assert data["document_id"] == "D" and data["pages"][0]["blocks"]
    assert data["pages"][0]["blocks"][0]["bbox"] is not None
