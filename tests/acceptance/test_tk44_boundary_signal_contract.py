"""Evaluator-owned structural contract; all inputs below are synthetic.

UNKNOWN retains legacy behavior. Explicit evidence determines only the separator;
absence of a source whitespace glyph does not establish JOIN_CONFIRMED.
Evaluator promotion: all 49 structural and existing boundary checks passed.
"""
from __future__ import annotations

import hashlib
import inspect
import unicodedata

import pytest

from packages.document_engine import paragraph_reconstruction as reconstruction


def _require_contract():
    parameter = inspect.signature(reconstruction.join_lines).parameters.get("boundary_signal")
    if parameter is None:
        raise TypeError("boundary_signal contract is not implemented")
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default == "UNKNOWN"


@pytest.mark.parametrize("prev,nxt", [
    ("자료는 (새", "문서)로 정리된다."),
    ("검토 대상", "에 관한 기록이다."),
    ("정리하면 (", "기록이다)."),
    ("표현은 본문", ")으로 이어진다."),
    ("보고서 Ａ", "Ｂ 항목이다."),
])
@pytest.mark.parametrize("signal", ["JOIN_CONFIRMED", "SPACE_CONFIRMED", "UNKNOWN"])
def test_signal_controls_separator_before_legacy_heuristics(prev, nxt, signal):
    _require_contract()
    legacy = reconstruction.join_lines(prev, nxt, prev_full=True, char_wrap_context=True)
    p = unicodedata.normalize("NFKC", prev).rstrip()
    n = unicodedata.normalize("NFKC", nxt).lstrip()
    expected = legacy if signal == "UNKNOWN" else p + (" " if signal == "SPACE_CONFIRMED" else "") + n
    assert reconstruction.join_lines(prev, nxt, prev_full=True, char_wrap_context=True,
                                     boundary_signal=signal) == expected


@pytest.mark.parametrize("signal", ["JOIN_CONFIRMED", "SPACE_CONFIRMED", "UNKNOWN"])
@pytest.mark.parametrize("prev,nxt,expected", [("", "Ｂ", "B"), ("Ａ", "", "A"), ("", "", "")])
def test_empty_operands_keep_normalized_identity(signal, prev, nxt, expected):
    _require_contract()
    assert reconstruction.join_lines(prev, nxt, boundary_signal=signal) == expected


@pytest.mark.parametrize("signal", [None, "", "SPACE", "join_confirmed", 1])
def test_invalid_signal_is_rejected(signal):
    _require_contract()
    with pytest.raises(ValueError):
        reconstruction.join_lines("기록", "항목", boundary_signal=signal)


def _make_pdf(path, *, trailing_space, page_width, extra_paragraph):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    font = "HYSMyeongJo-Medium"
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    page = canvas.Canvas(str(path), pagesize=(page_width, 842))
    page.setFont(font, 10.5)
    if extra_paragraph:
        page.drawString(72, 810, "별도 문단은 배치 변화만 확인한다.")
    page.drawString(72, 760, "자료는 (새" + (" " if trailing_space else ""))
    page.drawString(72, 745, "문서)로 정리된다.")
    page.save()


@pytest.mark.parametrize("trailing_space", [False, True])
@pytest.mark.parametrize("page_width,extra_paragraph", [(420, False), (595, False), (720, True)])
def test_real_pdf_boundary_evidence_reaches_joiner(tmp_path, monkeypatch, trailing_space,
                                                  page_width, extra_paragraph):
    _require_contract()
    import pdfplumber
    from packages.document_engine import parse_document

    path = tmp_path / "synthetic.pdf"
    _make_pdf(path, trailing_space=trailing_space, page_width=page_width, extra_paragraph=extra_paragraph)
    with pdfplumber.open(path) as pdf:
        source_chars = pdf.pages[0].chars
        assert any(c["text"].isspace() for c in source_chars)  # Interior spaces always exist.
    observed = []
    original = reconstruction.join_lines

    def capture(prev, nxt, **kwargs):
        if "자료는 (새" in prev and "문서)" in nxt:
            observed.append(kwargs.get("boundary_signal", "UNKNOWN"))
        return original(prev, nxt, **kwargs)

    monkeypatch.setattr(reconstruction, "join_lines", capture)
    doc = parse_document(str(path), document_id="synthetic", filename=path.name,
                         mime_type="application/pdf", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert not doc.parse_warnings
    expected_signal = "SPACE_CONFIRMED" if trailing_space else "UNKNOWN"
    assert observed and set(observed) == {expected_signal}
    blocks = [b for page in doc.pages for b in page.blocks if "자료는 (새" in b.text]
    assert len(blocks) == 1
    expected = "자료는 (새 문서)로 정리된다." if trailing_space else original("자료는 (새", "문서)로 정리된다.")
    assert blocks[0].text == expected
    evidence = blocks[0].attributes["boundary_observations"]
    assert len(evidence) == 1
    receipt = evidence[0]
    assert receipt["boundary_signal"] == expected_signal
    for key in ("previous_glyph_indices", "following_glyph_indices"):
        assert receipt[key] and all(0 <= i < len(source_chars) for i in receipt[key])
    indices = receipt["space_glyph_indices"]
    assert bool(indices) == trailing_space
    assert all(source_chars[i]["text"].isspace() for i in indices)
    assert receipt["reason"] == ("DIRECT_SPACE_GLYPH" if trailing_space else "NO_DIRECT_BOUNDARY_EVIDENCE")


@pytest.mark.parametrize("page_width", [420, 595, 720])
@pytest.mark.parametrize("endpoints", [(300, 250), (300, 300, 250), (500, 500, 250)])
def test_unknown_upstream_layout_keeps_frozen_baseline_output(page_width, endpoints):
    from packages.common.schemas import BBox, Block

    lines = ["기록을 확인할 수", "있다는 점을 적는다."]
    if len(endpoints) == 3:
        lines.insert(0, "관측 기록을 살펴보았다")
    blocks = [Block(f"synthetic-{i}", text, 1,
                    bbox=BBox(72, 100 + 16 * i, x1, 112 + 16 * i))
              for i, (text, x1) in enumerate(zip(lines, endpoints))]
    out = reconstruction.reconstruct_page_blocks(blocks, page_num=1,
                                                  page_width=page_width, page_height=842)
    # Frozen 5dea baseline: UNKNOWN historically depends on the legacy page
    # floor. Retaining that limitation prevents a new word-fragment regression.
    joined = endpoints == (500, 500, 250) and page_width in (420, 595)
    tail = "기록을 확인할 수" + ("" if joined else " ") + "있다는 점을 적는다."
    expected = ("관측 기록을 살펴보았다 " if len(endpoints) == 3 else "") + tail
    assert len(out) == 1 and out[0].text == expected
    assert all(o["boundary_signal"] == "UNKNOWN"
               for o in out[0].attributes["boundary_observations"])


@pytest.mark.parametrize("page_width", [420, 595, 720])
def test_actual_pdf_unknown_does_not_create_new_word_fragments(tmp_path, page_width):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    from packages.document_engine import parse_document

    path = tmp_path / "synthetic-unknown.pdf"
    font = "HYSMyeongJo-Medium"
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    page = canvas.Canvas(str(path), pagesize=(page_width, 842))
    page.setFont(font, 10.5)
    page.drawString(72, 760, "기록을 확인할 수")
    page.drawString(72, 745, "있다.")
    page.save()
    doc = parse_document(str(path), document_id="synthetic-unknown", filename=path.name,
                         mime_type="application/pdf", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert not doc.parse_warnings
    blocks = [b for p in doc.pages for b in p.blocks if "기록을 확인할 수" in b.text]
    assert len(blocks) == 1 and blocks[0].text == "기록을 확인할 수 있다."
    receipt, = blocks[0].attributes["boundary_observations"]
    assert receipt["boundary_signal"] == "UNKNOWN"
    assert receipt["space_glyph_indices"] == []
    assert receipt["reason"] == "NO_DIRECT_BOUNDARY_EVIDENCE"
