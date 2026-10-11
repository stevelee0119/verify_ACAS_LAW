"""Synthetic glyph observations; no document fixtures or lexical exceptions."""
import pytest

from packages.document_engine.boundary_signals import glyph_line_evidence, observe_boundary
from packages.document_engine import parse_document


def _glyphs(text, *, upright=True):
    return [{"text": char, "x0": i * 10, "x1": (i + 1) * 10,
             "size": 10, "upright": upright} for i, char in enumerate(text)]


@pytest.mark.parametrize("left,right", [("가나다 ", "라마"), ("바사", " 아자"), ("차카 ", " 타파")])
def test_direct_boundary_whitespace_is_observable(left, right):
    a = glyph_line_evidence(_glyphs(left), list(range(len(left))))
    b = glyph_line_evidence(_glyphs(right), list(range(len(left), len(left) + len(right))))
    observation = observe_boundary({"glyph_boundary_evidence": a}, {"glyph_boundary_evidence": b})
    assert observation["boundary_signal"] == "SPACE_CONFIRMED"
    assert observation["space_glyph_indices"]


@pytest.mark.parametrize("left,right", [("가나다", "라마"), ("바사", "아자"), ("차카", "타파")])
def test_absent_space_is_not_join_evidence(left, right):
    a = glyph_line_evidence(_glyphs(left), list(range(len(left))))
    b = glyph_line_evidence(_glyphs(right), list(range(len(left), len(left) + len(right))))
    assert observe_boundary({"glyph_boundary_evidence": a}, {"glyph_boundary_evidence": b})["boundary_signal"] == "UNKNOWN"


def test_rotated_or_overlapping_glyphs_cannot_confirm_spaces():
    chars = _glyphs("가나 ", upright=False)
    evidence = glyph_line_evidence(chars, [0, 1, 2])
    assert not evidence["usable"]
    chars = _glyphs("가나 ")
    chars[-1]["x0"] = 0
    assert not glyph_line_evidence(chars, [0, 1, 2])["usable"]


def test_real_pdf_edge_space_survives_stripping(tmp_path):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    path = tmp_path / "synthetic-boundaries.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.setFont("HYSMyeongJo-Medium", 12)
    pdf.drawString(70, 700, "가나다 (라 ")
    pdf.drawString(70, 682, "마바사) 아자차카.")
    pdf.save()
    doc = parse_document(str(path), document_id="synthetic", filename=path.name,
                         mime_type="application/pdf", sha256="synthetic")
    observations = [entry for page in doc.pages for block in page.blocks
                    for entry in block.attributes.get("boundary_observations", [])]
    assert observations, doc.parse_warnings
    assert observations[0]["boundary_signal"] == "SPACE_CONFIRMED"
    assert observations[0]["space_glyph_indices"]
