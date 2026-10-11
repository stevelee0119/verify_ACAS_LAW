"""Synthetic glyph observations; no document fixtures or lexical exceptions."""
import pytest

from packages.document_engine.boundary_signals import glyph_line_evidence, observe_boundary
from packages.document_engine import parse_document
from packages.document_engine.paragraph_reconstruction import join_lines


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


@pytest.mark.parametrize("has_space", [False, True])
@pytest.mark.parametrize("size,extra,width", [(10, 0, 320), (12, 1, 600), (16, 2, 900)])
def test_real_pdf_boundary_evidence_controls_reconstruction(tmp_path, has_space, size, extra, width):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    path = tmp_path / "synthetic-boundaries.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(width, 800))
    pdf.setFont("HYSMyeongJo-Medium", size)
    pdf.drawString(70, 700, "가나다 (라" + (" " if has_space else ""))
    pdf.drawString(70, 700 - size * 1.5, "마바사) 아자차카.")
    for index in range(extra):
        pdf.drawString(70, 500 - index * size * 1.5, "타파하 가나다라마 바사아자차카.")
    pdf.save()
    doc = parse_document(str(path), document_id="synthetic", filename=path.name,
                         mime_type="application/pdf", sha256="synthetic")
    observations = [entry for page in doc.pages for block in page.blocks
                    for entry in block.attributes.get("boundary_observations", [])]
    assert observations, doc.parse_warnings
    assert observations[0]["boundary_signal"] == ("SPACE_CONFIRMED" if has_space else "UNKNOWN")
    target = next(block for page in doc.pages for block in page.blocks if "가나다 (라" in block.text)
    assert target.text == "가나다 (라" + (" " if has_space else "") + "마바사) 아자차카."
    assert bool(observations[0]["space_glyph_indices"]) == has_space


@pytest.mark.parametrize("left,right", [("가나다 (라", "마바사)"), ("아자 차", "카타파"), ("하가", "나다")])
def test_explicit_signal_triplet_and_legacy_compatibility(left, right):
    assert join_lines(left, right, boundary_signal="JOIN_CONFIRMED") == left + right
    assert join_lines(left, right, boundary_signal="SPACE_CONFIRMED") == left + " " + right
    assert join_lines(left, right, True, True, boundary_signal="UNKNOWN") == join_lines(left, right, True, True)


@pytest.mark.parametrize("left,right", [("(", "가"), ("가", ")"), ("가", ",")])
def test_explicit_space_precedes_punctuation_heuristics(left, right):
    assert join_lines(left, right, boundary_signal="SPACE_CONFIRMED") == left + " " + right


@pytest.mark.parametrize("signal", ["JOIN_CONFIRMED", "SPACE_CONFIRMED", "UNKNOWN"])
def test_valid_signals_preserve_empty_identity(signal):
    assert join_lines("", " Ａ ", boundary_signal=signal) == "A "
    assert join_lines(" Ａ ", "", boundary_signal=signal) == " A"


@pytest.mark.parametrize("signal", ["join", "", None, []])
def test_invalid_signal_raises_even_for_empty_inputs(signal):
    with pytest.raises(ValueError):
        join_lines("", "", boundary_signal=signal)
