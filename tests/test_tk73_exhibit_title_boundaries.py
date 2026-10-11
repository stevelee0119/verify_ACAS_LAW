"""TK-73 public synthetic controls; no real/retired case data or PDFs."""
import time

import pytest

from packages.claim_engine.evidence_consistency import _duplicate_title_key, check_exhibits, exhibit_rows
from packages.common.schemas import Block, NormalizedDocument, Page


def _doc(lines, section=False):
    text = "\n".join((["입증방법"] if section else []) + lines)
    return NormalizedDocument("synthetic", "synthetic.txt", "text/plain", "0" * 64,
                              pages=[Page(1, blocks=[Block("b1", text, 1)])])


def _duplicates(doc):
    return [f for f in check_exhibits(doc)
            if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,title,location,description", [
    ("갑 제1호증", "장치대장", "부록 4쪽.", "교체 시점을 설명합니다."),
    ("을 제2호증의 1", "배선도", "도면 6쪽.", "접속 경로를 보여줍니다."),
    ("병 제3호증", "출입기록", "첨부 8쪽.", "방문 순서를 확인합니다."),
    ("갑 제4호증의 1", "관측: 동쪽, 봄철", "제 5쪽 2행.", "측정 순서를 설명한다."),
])
def test_synthetic_same_title_descriptions(section, label, title, location, description):
    doc = _doc([f"{label}: {title}, {location}", f"{label} {title}: {description}"], section)
    rows = exhibit_rows(doc)
    assert len(rows) == 2
    assert rows[0]["name"] != rows[1]["name"]  # Display/source name remains intact.
    assert not _duplicates(doc)


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,first,second", [
    ("갑 제1호증", "관측: 동쪽", "관측: 서쪽"),
    ("을 제2호증", "집계, 봄철", "집계, 겨울철"),
    ("병 제3호증의 1", "운영지침", "순찰일지"),
    ("갑 제4호증", "관측: 2031. 3. 7. 동쪽", "관측: 2031. 3. 7. 서쪽"),
    ("을 제5호증", "사진, 4쪽 풍경", "사진, 4쪽 입구"),
    ("병 제6호증", '기록 "제목, 항목을 설명합니다."', '기록 "제목, 출입을 설명합니다."'),
    ("갑 제7호증", "보고서 (점검: 동쪽)", "보고서 (점검: 서쪽)"),
])
def test_synthetic_genuine_different_titles(section, label, first, second):
    found = _duplicates(_doc([f"{label} {first}", f"{label} {second}"], section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


def test_synthetic_multiple_exhibits_in_one_paragraph():
    doc = _doc(["가. 참고자료 목록", "갑 제1호증: 열람표, 부록 3쪽. 갑 제2호증: 보관표, 첨부 7쪽.",
                "갑 제1호증 열람표: 열람 시각을 표시합니다.", "갑 제2호증 보관표: 보관 경로를 설명합니다."])
    assert len(exhibit_rows(doc)) == 4
    assert not _duplicates(doc)


def test_synthetic_width_and_whitespace_normalization():
    assert not _duplicates(_doc(["갑 제1호증： ＡＢＣ 대장, 부록 9쪽.", "갑 제1호증 ABC대장: 이동을 기록합니다."]))


def test_synthetic_invalid_date_and_gap_retained():
    doc = _doc(["갑 제1호증 열람표, 부록 3쪽. 2031. 2. 30.",
                "갑 제1호증 열람표: 순서를 표시합니다.", "갑 제3호증 보관표"])
    findings = check_exhibits(doc)
    ids = {f.confidence_features.get("rule_id") for f in findings}
    assert "EVI.EVIDENCE_DATE_INVALID" in ids
    assert "EVI.EVIDENCE_NUMBERING_GAP" in ids
    assert not _duplicates(doc)


def test_synthetic_protected_title_and_multiple_description_clauses():
    doc = _doc(['갑 제1호증: 「관측: 동쪽, 항목을 설명합니다.」, 부록 3쪽, 이동을 기록합니다.',
                '갑 제1호증 「관측: 동쪽, 항목을 설명합니다.」: 접속을 설명합니다. 날짜는 별도입니다.'])
    assert not _duplicates(doc)


def test_synthetic_table_title_cells_are_complete():
    doc = _doc([])
    doc.structure["tables"] = [{"cells": [["호증", "서증명", "작성일"],
                                         ["갑 제1호증", "표목: 설명합니다.", "2031. 3. 7."],
                                         ["갑 제1호증", "표목: 기록합니다.", "2031. 3. 7."]]}]
    assert len(_duplicates(doc)) == 1


@pytest.mark.parametrize("tail", ["자료" + ", 항목" * 4000, "자료" + ": (구획, 설명)" * 3000,
                                 '자료 "' + ", 항목" * 4000, "자료, 부록 3쪽."])
def test_synthetic_linear_boundary_runtime(tail):
    row = {"name": tail, "duplicate_tail": tail, "from_lines": True}
    started = time.perf_counter()
    for _ in range(2000 if len(tail) < 100 else 1):
        _duplicate_title_key(row)
    assert time.perf_counter() - started < 0.1
