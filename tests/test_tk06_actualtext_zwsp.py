"""TK-06: ActualText 폭 0 문자(U+200B) 줄바꿈 표시와 은닉 신호 구분 단위 테스트.

- 양성 3건 이상: 단어/글자 사이에 끼워 넣은 ZWSP, 본문에 안 쓰인 글리프를 덮는 ZWSP, 여러 글리프를 덮는 ZWSP 등 은닉 공격
- 대조군 3건 이상: Google Docs 등 줄 끝(ET) 경계의 평소 공백 글리프 줄바꿈 표시, 번호 목록 뒤 평소 공백 경계, 반복 공백 글리프
- 사건 고유 값 및 서면 인용구 배제(일반화된 합성 스트림/PDF 검증)
"""
from __future__ import annotations

import pytest
from packages.document_engine.pdf_parser import (
    _actual_text_zero_width,
    _is_line_break_marker,
    _routine_glyphs,
)

# ActualText 밖에서 3회 이상 등장하는 평소 공백 글리프 스트림 (F6 글꼴의 <0003>)
ROUTINE_SPACES = b"".join(b"BT /F6 14.6 Tf 1 0 0 -1 0 .8 Tm %d 5 Td <0003> Tj ET\n" % n for n in (10, 20, 30))


# ==============================================================================
# 1. 양성 테스트: 진짜 은닉 수법 (3건 이상)
# ==============================================================================


def test_zwsp_in_between_glyphs_positive():
    """양성 1: 동일 텍스트 블록(BT...ET) 내에서 글자 사이에 끼워 넣은 ZWSP(TC-03 형태).

    EMC 직후에 ET로 끝나지 않고 곧바로 다음 글자(Tj)가 이어지는 은닉 수법.
    """
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/F6 12 Tf\n"
        b"<0041> Tj\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F6 12 Tf\n"
        b"<0003> Tj\n"
        b"EMC\n"
        b"/F6 12 Tf\n"
        b"<0042> Tj\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    # 글자 사이에 끼워 넣었으므로(ET 직전이 아니거나 단일 글리프 규격 벗어남) 은닉 신호로 잡힘
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_unregistered_glyph_positive():
    """양성 2: ActualText 밖에서는 쓰이지 않는 임의의 글리프(본문에 안 쓰인 글리프)를 덮는 ZWSP.

    ET 직전이라도 평소 공백 글리프(routine >= 3)가 아니면 은닉 신호로 탐지.
    """
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F55 15.3 Tf 14.8 0 Td <01> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_different_font_glyph_positive():
    """양성 3: 평소 글꼴(/F6)이 아닌 다른 글꼴(/F9)을 사용하여 공백을 가장한 ZWSP.

    같은 글리프 코드라도 다른 글꼴이면 평소 글리프로 인정하지 않고 은닉 신호로 탐지.
    """
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F9 14.6 Tf 14.8 0 Td <0003> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_covering_multiple_glyphs_positive():
    """양성 4: ActualText가 단일 글리프가 아니라 여러 글리프를 덮어 문자열을 은닉하는 경우."""
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F6 12 Tf\n"
        b"<0003> Tj\n"
        b"<0003> Tj\n"  # 2개의 글리프를 덮음
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_mixed_with_other_chars_positive():
    """양성 5: ActualText에 U+200B 외에 다른 문자가 혼합되어 있는 경우(ZWSP+ZWNJ)."""
    # <FEFF200B200C> : ZWSP(200B) + ZWNJ(200C)
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B200C> >> BDC\n"
        b"/F6 12 Tf\n"
        b"<0003> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert counts.get("U+200C ZERO WIDTH NON-JOINER", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


# ==============================================================================
# 2. 대조군 테스트: 정상적인 줄바꿈 및 목록 경계 표시 (3건 이상)
# ==============================================================================


def test_zwsp_at_line_end_et_control():
    """대조군 1: 줄 끝에서 평소 공백 글리프에 ActualText U+200B가 붙는 줄바꿈 표시(Google Docs)."""
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F6 14.6 Tf 1 0 0 -1 0 .8 Tm 307.7 -13.2 Td <0003> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    # 평소 공백 글리프(F6 <0003>)의 단일 글리프 줄바꿈 표시이므로 markers로 분류
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1


def test_zwsp_at_list_item_boundary_control():
    """대조군 2: 번호 목록 항목 뒤 평소 공백 글꼴 경계 표시(서면6·7 유형)."""
    stream = (
        ROUTINE_SPACES
        + b"/LI <</MCID 1 >>BDC\n"
        b"BT\n"
        b"/F6 14.6 Tf\n"
        b"12 -13 Td <0003> Tj\n"
        b"ET\n"
        b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F6 14.6 Tf\n"
        b"12 -13 Td <0003> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1


def test_zwsp_routine_space_glyph_control():
    """대조군 3: ActualText 밖에서 3회 이상 사용된 공백 글리프의 단일 줄바꿈 표시."""
    stream = (
        ROUTINE_SPACES
        + b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F6 14.6 Tf\n"
        b"<0003> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers,
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1
