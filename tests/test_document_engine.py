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


def test_justified_prose_is_not_duplicated_as_table(tmp_path):
    """정렬된 문단이 표로 오검출되어 " | " 파편을 만들면 안 된다.

    실제 보고서에서 주장 101건 중 16건이
    "[ | 인용 판례 | 1 — | ] | 대법원 | 2023. 11. 16. | ..." 형태의 중복이었다.
    """
    from packages.document_engine.pdf_parser import _covered_by, _text_signature

    line_text = "[인용 판례 1 — 가공 판례 테스트] 대법원 2023. 11. 16. 선고 2023다284910 판결"
    rows = [["[", "인용 판례", "1 —", "가공 판례 테스트", "]"], ["대법원", "2023. 11. 16.", "선고"]]
    assert _covered_by(_text_signature(line_text), rows) is True, "줄 텍스트와 중복된 표는 버려야 한다"

    real_rows = [["항목", "금액"], ["착수금", "300,000,000"], ["합계", "300,000,000"]]
    assert _covered_by(_text_signature("본문에는 없는 내용"), real_rows) is False, "진짜 표는 남겨야 한다"


# --- 자원 사용 -----------------------------------------------------------------
def test_page_caches_are_released_so_memory_does_not_grow_with_page_count(tmp_path):
    """긴 문서에서 pdfplumber 페이지 캐시가 쌓이면 메모리가 쪽수에 비례해 늘어난다.

    80쪽 서면 하나로 300MB를 넘겼다. 512MB 인스턴스에서는 그 자체로
    프로세스가 죽고, 죽은 워커는 임차가 만료되며 작업이 처음부터 다시
    실행된다. 읽기가 끝난 페이지는 캐시를 놓아주어야 한다.
    """
    import pdfplumber
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    from packages.document_engine.pdf_parser import PdfParser

    try:
        pdfmetrics.getFont("HYSMyeongJo-Medium")
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    path = tmp_path / "long.pdf"
    drawing = canvas.Canvas(str(path), pagesize=A4)
    for page in range(6):
        drawing.setFont("HYSMyeongJo-Medium", 10)
        y = 780
        for row in range(10):
            drawing.drawString(50, y, f"{page + 1}-{row + 1}. 원고는 피고에게 금 1,000,000원을 청구한다.")
            y -= 23
        drawing.showPage()
    drawing.save()

    flushed = []
    original = pdfplumber.page.Page.flush_cache

    def spy(self, *args, **kwargs):
        flushed.append(self.page_number)
        return original(self, *args, **kwargs)

    pdfplumber.page.Page.flush_cache = spy
    try:
        document = PdfParser().parse(str(path), document_id="d", filename="long.pdf",
                                     mime_type="application/pdf", sha256="x" * 64)
    finally:
        pdfplumber.page.Page.flush_cache = original

    assert len(document.pages) == 6
    # 파싱 도중 쪽 순서대로 한 번, 파일을 닫을 때 pdfplumber가 다시 한 번.
    # 앞의 여섯 개가 없으면 캐시가 문서를 다 읽을 때까지 쌓인 것이다.
    assert flushed[:6] == [1, 2, 3, 4, 5, 6], f"파싱 도중 쪽마다 놓아주어야 한다: {flushed}"
    assert len(flushed) > 6, f"닫을 때의 정리만 보인다면 파싱 중에는 쌓인 것이다: {flushed}"


def test_table_signature_is_built_incrementally_without_rescanning_the_document():
    """페이지마다 본문 전체를 다시 정규화하면 비용이 쪽수의 제곱으로 는다.

    \\s+ 제거는 부분마다 해도 전체에 한 번 해도 결과가 같다. 이 성질이
    깨지면 표 중복 판정이 조용히 달라지므로 시험으로 고정한다.
    """
    from packages.document_engine.pdf_parser import _text_signature

    parts = ["원고는 피고에게", "  금 1,000,000원을\t청구한다.", "\n민법 제390조"]
    assert "".join(_text_signature(p) for p in parts) == _text_signature("".join(parts))
