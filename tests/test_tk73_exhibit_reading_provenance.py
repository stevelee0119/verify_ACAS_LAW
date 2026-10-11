"""Public synthetic document-to-mention provenance and reflow controls."""
import time
import unicodedata

import pytest

from packages.claim_engine.evidence_consistency import (
    _duplicate_mention_view, _exhibit_source_spans, _numbering, check_exhibits, exhibit_rows,
)
from packages.document_engine.reading_text import SPACE_MAP, build_reading_text
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


def _parsed(tmp_path, extension, lines):
    path = tmp_path / f"public_provenance.{extension}"
    if extension == "pdf":
        build_pdf({"name": path.name, "header": "합성 출처 시험", "footer": "가상 자료",
                   "body": [("p", line) for line in lines]}, path)
    else:
        path.write_text("\n".join(lines), encoding="utf-8")
    doc = parse_document(str(path), document_id="public_provenance", filename=path.name,
                         mime_type="application/pdf" if extension == "pdf" else "text/plain", sha256="0" * 64)
    assert not doc.parse_warnings
    return doc


def _duplicates(doc):
    return [f for f in check_exhibits(doc)
            if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]


def _assert_source_projection(doc, row, view):
    reading = build_reading_text(doc)
    blocks = {block.block_id: block for block in doc.blocks}
    assert view["source_mapping_verified"]
    assert view["origins"]
    for origin in view["origins"]:
        start, end = origin["reading_span"]
        assert reading.text[start:end] == origin["text"]
        local_start, local_end = origin["raw_span"]
        assert view["raw_comparison_text"][local_start:local_end] == origin["text"]
        assert origin["normalization_precision"] == "fragment"
        for source in origin["sources"]:
            block = blocks[source["block_id"]]
            source_start, source_end = source["reading_span"]
            block_start, block_end = source["block_span"]
            assert 0 <= block_start < block_end <= len(block.text)
            assert block.text[block_start:block_end].translate(SPACE_MAP) == reading.text[source_start:source_end]
            assert start <= source_start < source_end <= end
        if origin["origin"] == "item":
            reference_start, reference_end = origin["reference_span"]
            assert reference_end == start
            assert "호증" in unicodedata.normalize("NFKC", reading.text[reference_start:reference_end])
    if view["title_span"]:
        start, end = view["title_span"]
        title = view["comparison_text"][start:end].strip().rstrip(".!?。！？")
        assert "".join(title.split()) == view["title_key"]


_REFLOW_CONTROLS = [
    (["갑 제1호증 보관목록, 부록 7쪽,", "발췌 부분.", "갑 제1호증 보관목록: 저장 위치를 설명한다."], "7쪽"),
    (["갑 제1호증 대여대장, 부록 7", "쪽 하단 영역.", "갑 제1호증 대여대장: 이동 경로를 표시한다."], "7쪽"),
    (["갑 제1호증 승인표, 부록 7-", "9쪽 확인 부분.", "갑 제1호증 승인표: 승인 순서를 기록한다."], "7-9쪽"),
    (["갑 제1호증 공정표, 부록7쪽 일부.", "갑 제1호증 공정표: 공정 위치를 설명한다."], "7쪽"),
    (["갑 제1호증 장비표, 참고 부록 제 5페이지 하단 영역.", "갑 제1호증 장비표: 배치 경로를 표시한다."], "5페이지"),
    (["갑 제１호증： 옮김표， 부록７－９쪽； 발췌 부분。", "갑 제1호증 옮김표： 옮김 순서를 기록한다。"], "7-9쪽"),
    (["갑 제1호증 순회표; 참고 부록 제 12행 일부", "갑 제1호증 순회표: 순회 경로를 설명한다."], "12행"),
    (["갑 제1호증 요약표, " + "참고 설명 " * 30 + "부록7쪽 " + "부가 설명 " * 30 + ".",
      "갑 제1호증 요약표: 목록 순서를 기록한다."], "7쪽"),
]


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("lines,coordinate", _REFLOW_CONTROLS)
def test_synthetic_reflow_locator_mentions_have_verified_origins(tmp_path, extension, section, lines, coordinate):
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + lines)
    rows = exhibit_rows(doc)
    assert len(rows) == 2
    views = [_duplicate_mention_view(row) for row in rows]
    assert [view["kind"] for view in views] == ["locator", "prose"]
    assert views[0]["title_key"] == views[1]["title_key"]
    for row, view in zip(rows, views):
        _assert_source_projection(doc, row, view)
        assert row["date"] == row["author"] == row["purpose"] == ""
    start, end = views[0]["location_span"]
    assert views[0]["comparison_text"][start:end].replace(" ", "") == coordinate
    prefix_start, prefix_end = views[0]["location_prefix_span"]
    qualifier_start, qualifier_end = views[0]["location_qualifier_span"]
    assert prefix_end == start and qualifier_start == end
    assert views[0]["location_context_span"] == (prefix_start, qualifier_end)
    start, end = views[1]["narrative_span"]
    assert views[1]["comparison_text"][start:end].endswith("한다")
    assert not _duplicates(doc)


_OPPOSITE_CONTROLS = [
    ["갑 제1호증 사진, 부록7쪽", "동쪽 풍경.", "갑 제1호증 사진, 부록7쪽", "서쪽 풍경."],
    ["갑 제1호증 지도, 참고 부록7-9쪽 동쪽.", "갑 제1호증 지도, 참고 부록7-9쪽 서쪽."],
    ["갑 제1호증 대장, 부록7쪽 일부.", "갑 제1호증 대장추가: 저장 위치를 설명한다."],
    ["갑 제1호증 대장, 부록7쪽 일부.", "갑 제1호증 대장, 부록8쪽 일부.", "을 제1호증 대장: 위치를 설명한다."],
    ["갑 제1호증의 1 대장, 부록7쪽 일부.", "갑 제1호증의 1 대장, 부록8쪽 일부.",
     "갑 제1호증의 2 대장: 위치를 설명한다."],
    ["갑 제1호증 대장, 부록7쪽 일부.", "갑 제1호증 대장, 부록8쪽 일부.", "갑 제2호증 대장: 위치를 설명한다."],
    ["갑 제1호증 동작, 지속시간7초 시작.", "갑 제1호증 동작, 지속시간8초 종료."],
    ["갑 제1호증 배포, 버전7.9", "갑 제1호증 배포, 버전7.10"],
    ["갑 제1호증 기기, 부품7개", "갑 제1호증 기기, 부품8개"],
    ["갑 제1호증 사진, 「7쪽 풍경」", "갑 제1호증 사진: 입구를 표시한다."],
    ["갑 제1호증 기록: 동쪽에 있다.", "갑 제1호증 기록: 서쪽에 있다."],
]


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("lines", _OPPOSITE_CONTROLS)
def test_synthetic_reflow_opposites_preserve_genuine_duplicate(tmp_path, extension, section, lines):
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + lines)
    for row in exhibit_rows(doc):
        _assert_source_projection(doc, row, _duplicate_mention_view(row))
    found = _duplicates(doc)
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("extension", ["pdf", "txt"])
def test_synthetic_multi_item_continuations_keep_separate_source_groups(tmp_path, extension):
    doc = _parsed(tmp_path, extension, [
        "갑 제1호증: 첫 대장, 부록7쪽 일부. 갑 제2호증: 둘째 대장, 부록9-11쪽,", "발췌 부분.",
        "갑 제1호증 첫 대장: 순서를 설명한다.", "갑 제2호증 둘째 대장: 위치를 기록한다.",
    ])
    rows = exhibit_rows(doc)
    assert len(rows) == 4
    views = [_duplicate_mention_view(row) for row in rows]
    for row, view in zip(rows, views):
        _assert_source_projection(doc, row, view)
    assert len(views[0]["origins"]) == 1
    assert views[1]["origins"][1]["origin"] == "continuation"
    assert not _duplicates(doc)


def test_synthetic_authoritative_table_title_never_uses_locator_splitting(tmp_path):
    doc = _parsed(tmp_path, "txt", [])
    doc.structure["tables"] = [{"table_ref": "synthetic_table", "cells": [
        ["호증", "서증명", "작성일"], ["갑 제1호증", "사진, 7쪽 풍경", "2030. 1. 2."],
        ["갑 제1호증", "사진: 저장 위치를 설명한다.", "2030. 1. 2."],
    ]}]
    rows = exhibit_rows(doc)
    assert [row["name"] for row in rows] == ["사진, 7쪽 풍경", "사진: 저장 위치를 설명한다."]
    assert all(_duplicate_mention_view(row)["origin_kind"] == "table_title" for row in rows)
    assert len(_duplicates(doc)) == 1


_AMBIGUOUS_ANCHOR_CONTROLS = [
    ["갑 제1호증 사진, 부록7쪽 동쪽 풍경.", "갑 제1호증 사진, 부록7쪽 서쪽 풍경.",
     "갑 제1호증 사진: 촬영 위치를 설명한다."],
    ["갑 제1호증 지도, 부록7-9쪽 동쪽.", "갑 제1호증 지도, 부록7-9쪽 서쪽.",
     "갑 제1호증 지도: 이동 경로를 표시한다."],
    ["갑 제1호증 요약표; 제12행 상단.", "갑 제1호증 요약표; 제12행 하단.",
     "갑 제1호증 요약표: 작업 순서를 기록한다."],
    ["갑 제1호증 기록, 제7행성 탐사.", "갑 제1호증 기록: 탐사 경로를 설명한다."],
    ["갑 제1호증 기록, 제7행성 탐사.", "갑 제1호증 기록, 제8행성 탐사.",
     "갑 제1호증 기록: 탐사 경로를 설명한다."],
    ["갑 제1호증 장치, 7페이지형 부품.", "갑 제1호증 장치: 부품 위치를 설명한다."],
    ["갑 제1호증 표본, 7쪽빛 분류.", "갑 제1호증 표본: 분류 위치를 설명한다."],
    ["갑 제1호증 공정표, 부록7쪽일부.", "갑 제1호증 공정표: 공정 위치를 설명한다."],
    ["갑 제1호증 기록, 제7행", "성 탐사.", "갑 제1호증 기록: 탐사 경로를 설명한다."],
    ["갑 제1호증 장치, 7페이지", "형 부품.", "갑 제1호증 장치: 부품 위치를 설명한다."],
    ["갑 제1호증 표본, 7쪽", "빛 분류.", "갑 제1호증 표본: 분류 위치를 설명한다."],
    ["갑 제1호증 보관목록, 부록 7쪽", "발췌 부분.",
     "갑 제1호증 보관목록: 저장 위치를 설명한다."],
]


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("lines", _AMBIGUOUS_ANCHOR_CONTROLS)
def test_synthetic_generic_anchor_cannot_erase_weak_or_lexical_identity(tmp_path, extension, section, lines):
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + lines)
    for row in exhibit_rows(doc):
        _assert_source_projection(doc, row, _duplicate_mention_view(row))
    found = _duplicates(doc)
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("title,locator", [("장비표", "부록7쪽 일부."),
                                           ("배선도", "도면7-9페이지 하단."),
                                           ("요약표", "첨부제12행 확인 부분.")])
def test_synthetic_repeated_complete_locator_identity_still_corroborates(tmp_path, extension, section, title, locator):
    line = f"갑 제1호증 {title}, {locator}"
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + [
        line, line, f"갑 제1호증 {title}: 위치를 설명한다.",
    ])
    assert not _duplicates(doc)


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("character", ["\u200d", "\u200b", "\x01", "±", "★", "‿", "\u200e"])
def test_synthetic_uncertain_source_character_never_certifies_coordinate(tmp_path, extension, section, character):
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + [
        f"갑 제1호증 기록, 제7행{character}성 탐사.", "갑 제1호증 기록: 탐사 경로를 설명한다.",
    ])
    reading = build_reading_text(doc)
    if extension == "txt":
        assert character in reading.text
    elif character not in reading.text:
        # The public PDF font omits some format/control glyphs. Verify the
        # actual extracted lexical word without claiming original glyph survival.
        assert "제7행성" in reading.text
    for row in exhibit_rows(doc):
        _assert_source_projection(doc, row, _duplicate_mention_view(row))
    found = _duplicates(doc)
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("extension", ["pdf", "txt"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("delimiter", [" ", "\u3000", ",", ";"])
def test_synthetic_observed_delimiter_certifies_complete_coordinate(tmp_path, extension, section, delimiter):
    doc = _parsed(tmp_path, extension, (["입증방법"] if section else []) + [
        f"갑 제1호증 대장, 부록7행{delimiter}확인 부분.", "갑 제1호증 대장: 순서를 설명한다.",
    ])
    assert not _duplicates(doc)


def test_synthetic_forward_provenance_and_continuation_runtime(tmp_path):
    # Measure the new source projection/comparison work on thousands of
    # distinct physical mentions. Existing PDF/TXT parsing is outside this
    # 0.1-second rule budget; the full reading path is verified above.
    doc = _parsed(tmp_path, "txt", [
        line for _ in range(1000) for line in ("갑 제1호증 대장, 부록7-9쪽,", "발췌 부분.",
                                             "갑 제1호증 대장: 저장 위치를 설명한다.")
    ])
    rows = exhibit_rows(doc)
    reading = build_reading_text(doc)
    empty = _parsed(tmp_path, "txt", [])
    started = time.perf_counter()
    cursor = [0]
    for row in rows:
        for source in row["duplicate_sources"]:
            start, end = source["reading_span"]
            assert _exhibit_source_spans(reading, start, end, cursor) == source["sources"]
    assert len(rows) == 2000
    assert not _numbering(empty, rows)
    assert time.perf_counter() - started < 0.1
