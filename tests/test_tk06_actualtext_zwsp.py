"""TK-06: ActualText 폭 0 문자(U+200B) 줄바꿈 표시와 은닉 신호 구분 단위 테스트.

- 양성 3건 이상: 단어/글자 사이에 끼워 넣은 ZWSP, 여러 글리프를 덮는 ZWSP 등 은닉 공격
- 대조군 3건 이상: Google Docs 등 줄 끝(ET) 경계 표시, 번호 목록 뒤 경계 표시, 평소 공백 글리프
- 사건 고유 값 및 서면 인용구 배제(일반화된 합성 스트림/PDF 검증)
"""
import pytest
from packages.document_engine.pdf_parser import (
    _actual_text_zero_width,
    _is_line_break_marker,
    _routine_glyphs,
)


# ==============================================================================
# 1. 양성 테스트: 진짜 은닉 수법 (3건 이상)
# ==============================================================================

def test_zwsp_in_between_glyphs_positive():
    """양성 1: 동일 텍스트 블록(BT...ET) 내에서 글자 사이에 끼워 넣은 ZWSP(TC-03 형태).
    
    EMC 직후에 ET로 끝나지 않고 곧바로 다음 글자(Tj)가 이어지는 은닉 수법.
    """
    # 스트림 데이터: 글자 A -> ActualText ZWSP -> 글자 B (같은 BT...ET 내)
    stream = (
        b"BT\n"
        b"/F1 12 Tf\n"
        b"<0041> Tj\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F2 12 Tf\n"
        b"<0001> Tj\n"
        b"EMC\n"
        b"/F1 12 Tf\n"
        b"<0042> Tj\n"
        b"ET\n"
    )
    counts = {}
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    # 글자 사이에 끼워 넣었으므로 줄바꿈 표시(markers)로 걸러지지 않고 은닉 신호(counts)로 잡혀야 함
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_covering_multiple_glyphs_positive():
    """양성 2: ActualText가 단일 글리프가 아니라 여러 글리프를 덮어 문자열을 은닉하는 경우."""
    stream = (
        b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F1 12 Tf\n"
        b"<0041> Tj\n"
        b"<0042> Tj\n"  # 2개의 글리프를 덮음
        b"EMC\n"
        b"ET\n"
    )
    counts = {}
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    # 여러 글리프를 가리는 행위는 은닉 신호
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 0


def test_zwsp_mixed_with_other_chars_positive():
    """양성 3: ActualText에 U+200B 외에 다른 문자가 혼합되어 있는 경우."""
    # <FEFF200B200C> : ZWSP(200B) + ZWNJ(200C)
    stream = (
        b"BT\n"
        b"/Span<</ActualText <FEFF200B200C> >> BDC\n"
        b"/F1 12 Tf\n"
        b"<0001> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    counts = {}
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 1
    assert counts.get("U+200C ZERO WIDTH NON-JOINER", 0) == 1


# ==============================================================================
# 2. 대조군 테스트: 정상적인 줄바꿈 및 목록 경계 표시 (3건 이상)
# ==============================================================================

def test_zwsp_at_line_end_et_control():
    """대조군 1: 줄 끝에서 공백 글리프에 ActualText U+200B가 붙고 바로 ET로 끝나는 줄바꿈 표시(Google Docs)."""
    stream = (
        b"BT\n"
        b"/F1 12 Tf\n"
        b"<0041> Tj\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F1 12 Tf\n"
        b"10 0 Td <0020> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    # 줄 끝 ET 경계이므로 은닉 신호가 아닌 줄바꿈 표시로 정상 분류
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1


def test_zwsp_at_list_item_boundary_control():
    """대조군 2: 번호 목록 항목 뒤 공백 글꼴 경계 표시(서면7의 F7 글꼴 유형).
    
    ActualText 밖에서 사용 빈도가 적더라도(routine=0), 독립 블록의 단일 글리프 끝(ET)이면 줄/단락 경계로 분류.
    """
    stream = (
        b"/LI <</MCID 1 >>BDC\n"
        b"BT\n"
        b"/F7 14 Tf\n"
        b"<0014> Tj\n"
        b"ET\n"
        b"BT\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"/F7 14 Tf\n"
        b"12 -13 Td <0003> Tj\n"
        b"EMC\n"
        b"ET\n"  # 바로 ET로 끝남
        b"BT\n"
        b"/F4 14 Tf\n"
        b"<0055> Tj\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1


def test_zwsp_routine_space_glyph_control():
    """대조군 3: ActualText 밖에서 반복 사용된 평소 공백 글리프(routine >= 3)인 경우."""
    # F1의 <0020>이 ActualText 밖에서 3회 이상 등장
    stream = (
        b"BT\n"
        b"/F1 12 Tf\n"
        b"<0020> Tj\n"
        b"<0020> Tj\n"
        b"<0020> Tj\n"
        b"/Span<</ActualText <FEFF200B> >> BDC\n"
        b"<0020> Tj\n"
        b"EMC\n"
        b"ET\n"
    )
    markers = {}
    counts = _actual_text_zero_width(
        b"stream\n" + stream + b"\nendstream",
        collect=False,
        line_break_markers=markers
    )
    assert counts.get("U+200B ZERO WIDTH SPACE", 0) == 0
    assert markers.get("U+200B ZERO WIDTH SPACE", 0) == 1
