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


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,title,date,first,second", [
    ("갑 제1호증", "검수표", "2032. 4. 5.", "비고: 원본", "비고: 사본"),
    ("을 제2호증의 1", "장비목록", "2033-06-07", "상태, 초안", "상태, 수정본"),
    ("병 제3호증", "배치도", "2034년 8월 9일", "형태: 첨부입니다.", "상태: 보관합니다."),
])
def test_synthetic_post_creation_date_metadata(section, label, title, date, first, second):
    doc = _doc([f"{label} {title} {date} {first}", f"{label} {title} {date} {second}"], section)
    rows = exhibit_rows(doc)
    assert len(rows) == 2
    assert rows[0]["name"] == rows[1]["name"] == title
    assert rows[0]["date"] == rows[1]["date"]
    assert not _duplicates(doc)


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,first,second,date", [
    ("갑 제1호증", "검수표", "운송장", "2032. 4. 5."),
    ("을 제2호증의 1", "장비목록", "정비목록", "2033-06-07"),
    ("병 제3호증", "배치도", "노선도", "2034년 8월 9일"),
])
def test_synthetic_genuine_duplicate_with_post_date_metadata(section, label, first, second, date):
    found = _duplicates(_doc([f"{label} {first} {date} 비고: 원본", f"{label} {second} {date} 비고: 사본"], section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("first,second", [
    ("도면: 2035. 1. 2. 북쪽", "도면: 2035. 1. 2. 남쪽"),
    ("도면 [2036. 3. 4.]: 북쪽", "도면 [2036. 3. 4.]: 남쪽"),
    ('도면 "2037. 5. 6.": 북쪽', '도면 "2037. 5. 6.": 남쪽'),
])
def test_synthetic_dates_inside_explicit_title_caption(section, first, second):
    found = _duplicates(_doc([f"갑 제1호증 {first}", f"갑 제1호증 {second}"], section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


def test_public_audit_original_post_date_counterexample():
    """The auditor supplied this public synthetic counterexample, not a corpus row."""
    assert not _duplicates(_doc(["갑 제1호증 합의서 2025. 3. 4. 비고: 원본",
                                 "갑 제1호증 합의서 2025. 3. 4. 비고: 사본"]))


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,title,date,first,second", [
    ("갑 제1호증", "기록: 동쪽", "2038. 7. 8.", "비고: 원본", "비고: 사본"),
    ("을 제2호증의 1", "계획: 오후", "2039-09-10", "상태, 초안", "상태, 수정본"),
    ("병 제3호증", "도면: 입구", "2040년 11월 12일", "형태: 첨부입니다.", "상태: 보관합니다."),
])
def test_synthetic_subtitle_before_creation_date_metadata(section, label, title, date, first, second):
    doc = _doc([f"{label} {title} {date} {first}", f"{label} {title} {date} {second}"], section)
    rows = exhibit_rows(doc)
    assert rows[0]["name"] == rows[1]["name"] == title
    assert not _duplicates(doc)


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("label,first,second", [
    ("갑 제1호증", "기록: 동쪽에 있다.", "기록: 서쪽에 있다."),
    ("을 제2호증의 1", "지침: 개방을 허용한다.", "지침: 개방을 금지한다."),
    ("병 제3호증", "보고서, 배관을 교체합니다.", "보고서, 기둥을 수리합니다."),
])
def test_synthetic_unanchored_sentence_subtitles_remain_genuine(section, label, first, second):
    found = _duplicates(_doc([f"{label} {first}", f"{label} {second}"], section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


def test_synthetic_complete_title_can_anchor_description():
    assert not _duplicates(_doc(["갑 제1호증 순회표", "갑 제1호증 순회표: 이동을 표시합니다."]))


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("title,first_date,second_date", [
    ("관측 [2030. 1. 2.]", "2040. 9. 10.", "2041. 11. 12."),
    ("「분석: 2031. 3. 4.」", "2042-01-02", "2043-03-04"),
    ('대장 "2032-05-06" (2033년 7월 8일)', "2044년 5월 6일", "2045년 7월 8일"),
])
def test_synthetic_multiple_protected_dates_before_creation_metadata(section, title, first_date, second_date):
    doc = _doc([f"갑 제1호증 {title} {first_date} 비고: 원본",
                f"갑 제1호증 {title} {second_date} 비고: 사본"], section)
    rows = exhibit_rows(doc)
    assert rows[0]["name"] == rows[1]["name"]  # Legacy display extraction remains intact.
    assert [_duplicate_title_key(row) for row in rows] == ["".join(title.split())] * 2
    assert not _duplicates(doc)


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("first,second", [
    ("관측 [2030. 1. 2. 북쪽]", "관측 [2030. 1. 2. 남쪽]"),
    ("「분석: 2031. 3. 4. 오전」", "「분석: 2031. 3. 4. 오후」"),
    ('대장 "2032-05-06" (2033년 7월 8일 입구)', '대장 "2032-05-06" (2033년 7월 8일 출구)'),
])
def test_synthetic_genuine_title_difference_after_protected_dates(section, first, second):
    doc = _doc([f"갑 제1호증 {first} 2040. 9. 10. 비고: 원본",
                f"갑 제1호증 {second} 2040. 9. 10. 비고: 원본"], section)
    rows = exhibit_rows(doc)
    assert rows[0]["name"] == rows[1]["name"]
    assert [_duplicate_title_key(row) for row in rows] == ["".join(title.split()) for title in (first, second)]
    found = _duplicates(doc)
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("first,second", [
    ("관측 [2030. 1. 2.]", "관측 [2030. 1. 3.]"),
    ("「분석: 2031. 3. 4.」", "「분석: 2031. 3. 5.」"),
    ('대장 "2032-05-06"', '대장 "2032-05-07"'),
])
def test_synthetic_genuine_protected_title_date_difference(section, first, second):
    found = _duplicates(_doc([f"갑 제1호증 {first} 2040. 9. 10. 비고: 원본",
                              f"갑 제1호증 {second} 2040. 9. 10. 비고: 원본"], section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("title", ["관측 [2030. 1. 2.]", "「분석: 2031. 3. 4.」", '대장 "2032-05-06"'])
def test_synthetic_multi_date_title_still_has_location_anchor(title):
    assert not _duplicates(_doc([f"갑 제1호증 {title}, 부록 3쪽. 2040. 9. 10. 비고: 원본",
                                 f"갑 제1호증 {title}: 위치를 표시합니다. 2041. 11. 12. 비고: 사본"]))


@pytest.mark.parametrize("opening", ["[", "「", '"'])
def test_synthetic_unbalanced_protection_preserves_legacy_genuine_duplicate(opening):
    found = _duplicates(_doc([f"갑 제1호증 기록 {opening}동쪽 2030. 1. 2.",
                              f"갑 제1호증 기록 {opening}서쪽 2030. 1. 2."]))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


def test_synthetic_table_title_cells_are_complete():
    doc = _doc([])
    doc.structure["tables"] = [{"cells": [["호증", "서증명", "작성일"],
                                         ["갑 제1호증", "표목: 설명합니다.", "2031. 3. 7."],
                                         ["갑 제1호증", "표목: 기록합니다.", "2031. 3. 7."]]}]
    assert len(_duplicates(doc)) == 1


@pytest.mark.parametrize("tail", ["자료" + ", 항목" * 4000, "자료" + ": (구획, 설명)" * 3000,
                                 '자료 "' + ", 항목" * 4000, "자료, 부록 3쪽.",
                                 "자료" + " [2030. 1. 2.]" * 3000 + " 2040. 9. 10. 비고: 사본"])
def test_synthetic_linear_boundary_runtime(tail):
    row = {"name": tail, "duplicate_tail": tail, "from_lines": True}
    started = time.perf_counter()
    for _ in range(2000 if len(tail) < 100 else 1):
        _duplicate_title_key(row)
    assert time.perf_counter() - started < 0.1


def test_synthetic_cross_row_anchor_runtime_is_bounded():
    from packages.claim_engine.evidence_consistency import _numbering

    rows = exhibit_rows(_doc(["갑 제1호증 순회표, 부록 3쪽.", "갑 제1호증 순회표: 이동을 표시합니다."])) * 2000
    started = time.perf_counter()
    assert not _numbering(_doc([]), rows)
    assert time.perf_counter() - started < 0.1
