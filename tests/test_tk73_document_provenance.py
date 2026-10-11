"""Public synthetic TK-73 document-path controls; no retired/private inputs."""
from copy import deepcopy
import time

import pytest

from packages.claim_engine.evidence_consistency import _numbering, check_exhibits, exhibit_rows
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


CASES = [
    ("갑 제4호증의 1", "냉각도", "배치도", "별지 11쪽", "이동 경로를 설명한다."),
    ("을 제5호증", "운행표", "설비목록", "제 13페이지", "점검 순서를 표시한다."),
    ("병 제6호증의 2", "조명대장", "전력계통도", "첨부 17행", "교체 시점을 기록한다."),
]


def _parse(tmp_path, extension, entries, section):
    path = tmp_path / f"public_provenance.{extension}"
    heading = ["입증방법"] if section else []
    if extension == "pdf":
        build_pdf({"name": path.name, "header": "공개 합성 경계 점검", "footer": "가상 입력",
                   "body": [("p", h) for h in heading] + [("lines", lines) for lines in entries]}, path)
    else:
        path.write_text("\n\n".join(heading + ["\n".join(lines) for lines in entries]), encoding="utf-8")
    doc = parse_document(str(path), document_id="public_provenance", filename=path.name,
                         mime_type="application/pdf" if extension == "pdf" else "text/plain", sha256="0" * 64)
    assert not doc.parse_warnings
    return doc


def _duplicates(doc):
    return [f for f in check_exhibits(doc)
            if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]


def _entries(case, layout, different=False):
    label, title, other, location, prose = case
    target = other if different else title
    metadata = "원본 표시 구역."
    if layout == "single":
        return [[f"{label}: {title}, {location} {metadata}"], [f"{label} {target}: {prose}"]]
    if layout == "coordinate":
        return [[f"{label}: {title}, {location}", metadata], [f"{label} {target}: {prose}"]]
    if layout == "parenthesis":
        return [[f"{label}: {title}, ({location}", metadata.rstrip(".") + ")."],
                [f"{label} {target}: {prose}"]]
    if layout == "title":
        return [[f"{label}: {title[:1]}", f"{title[1:]}, {location}", metadata],
                [f"{label} {target}: {prose}"]]
    return [[f"{label}: {title}, {location}", metadata],
            [f"{label} {target}:", prose[:-2], prose[-2:]]]


@pytest.mark.parametrize("extension", ["txt", "pdf"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("layout", ["single", "coordinate", "parenthesis", "title", "prose"])
def test_public_same_exhibit_is_invariant_under_document_wrapping(tmp_path, extension, section, case, layout):
    doc = _parse(tmp_path, extension, _entries(case, layout), section)
    rows = exhibit_rows(doc)
    assert len(rows) == 2
    assert all(row.get("duplicate_source") for row in rows)
    assert not _duplicates(doc)


@pytest.mark.parametrize("extension", ["txt", "pdf"])
@pytest.mark.parametrize("section", [False, True])
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("layout", ["coordinate", "parenthesis", "title"])
def test_public_genuine_duplicate_survives_document_wrapping(tmp_path, extension, section, case, layout):
    found = _duplicates(_parse(tmp_path, extension, _entries(case, layout, different=True), section))
    assert len(found) == 1
    assert str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("extension", ["txt", "pdf"])
def test_public_multiple_entries_and_branches_preserve_source_receipts(tmp_path, extension):
    doc = _parse(tmp_path, extension, [
        ["갑 제2호증의 1: 운행표, 별지 11쪽", "일부 구역. 갑 제2호증의 2: 냉각도, 첨부 13행", "표시 구역."],
        ["갑 제2호증의 1 운행표: 이동을 표시한다."],
        ["갑 제2호증의 2 냉각도: 위치를 설명한다."],
    ], False)
    rows = exhibit_rows(doc)
    assert len(rows) == 4
    assert not _duplicates(doc)
    blocks = {b.block_id: b for b in doc.body_blocks()}
    for row in rows:
        source = row["duplicate_source"]
        assert source["fragments"]
        for fragment in source["fragments"]:
            block = blocks[fragment["block_id"]]
            lines = block.attributes.get("lines") or [block.text]
            line = lines[fragment["line_index"]]
            raw = line["text"] if isinstance(line, dict) else line
            assert raw[fragment["source_start"]:fragment["source_end"]] == fragment["text"]
            assert fragment["page"] == block.page
            assert fragment["source_layer"] == block.source_layer
    # Roles are source-tail spans; the location includes later continuation text.
    _numbering(doc, rows)
    for row in rows[:2]:
        source = row["duplicate_source"]
        role = next(r for r in source["roles"] if r["kind"] == "qualified_location")
        assert role["end"] == len(source["tail"])


def _manual(lines):
    return NormalizedDocument("public", "public.txt", "text/plain", "0" * 64,
                              pages=[Page(1, blocks=[Block(f"line{i}", line, 1) for i, line in enumerate(lines)])])


def test_public_original_row_metadata_survives_comparison_source_change():
    doc = _manual(["갑 제4호증: 냉각도, 별지 11쪽", "원본 표시 구역.",
                   "갑 제4호증 냉각도: 경로를 설명한다."])
    rows = exhibit_rows(doc)
    assert rows[0]["name"] == "냉각도, 별지 11쪽원본 표시 구역."
    assert rows[0]["duplicate_tail"] == rows[0]["name"]
    assert rows[0]["duplicate_source"]["tail"] == "냉각도, 별지 11쪽 원본 표시 구역."
    original = deepcopy(rows)
    for row in original:
        row.pop("duplicate_source")
    assert len([f for f in _numbering(doc, original)
                if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]) == 1
    assert not _duplicates(doc)
    assert [{k: v for k, v in row.items() if k != "duplicate_source"} for row in rows] == original


@pytest.mark.parametrize("first,second", [
    ("도식, (첨부 17행 입구).", "도식, (첨부 17행 출구)."),
    ("사진, 별지 11쪽: 북쪽 구역.", "사진, 별지 11쪽: 남쪽 구역."),
    ("대장: 장치를 가동한다.", "대장: 장치를 정지한다."),
])
def test_public_subtitles_are_not_metadata_without_independent_prose(first, second):
    assert len(_duplicates(_manual([f"갑 제4호증 {first}", f"갑 제4호증 {second}"]))) == 1


@pytest.mark.parametrize("extension", ["txt", "pdf"])
@pytest.mark.parametrize("title", ["항목: 동쪽, 오전", "「기록: 가동한다, 2046. 1. 2.」", '대장 "2047-03-04" [2048. 5. 6.]'])
def test_public_full_punctuation_and_protected_dates_survive_wrapping(tmp_path, extension, title):
    doc = _parse(tmp_path, extension, [
        [f"을 제5호증: {title}, (별지 11쪽", "수록 구역). 2049. 7. 8. 상태: 초안"],
        [f"을 제5호증 {title}: 이동을 설명한다. 2050. 9. 10. 상태: 수정본"],
    ], False)
    assert not _duplicates(doc)


@pytest.mark.parametrize("physical", [["갑 제4호증 도면: 서쪽"], [{"text": None}], "malformed"])
def test_public_unaligned_physical_attributes_fall_back_without_guessing(physical):
    doc = _manual(["갑 제4호증 도면: 동쪽", "갑 제4호증 도면: 서쪽"])
    doc.pages[0].blocks[0].attributes["lines"] = physical
    assert exhibit_rows(doc)[0]["duplicate_source"] is None
    assert len(_duplicates(doc)) == 1


@pytest.mark.parametrize("width", [150, 240, 360])
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("different", [False, True])
def test_public_natural_pdf_wrap_uses_real_line_coordinates(tmp_path, width, case, different):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from scripts.audit.corpus import FONT, _register_font

    _register_font()
    label, title, other, location, prose = case
    target = other if different else title
    path = tmp_path / "public_natural_wrap.pdf"
    style = ParagraphStyle("public", fontName=FONT, fontSize=10.5, leading=15)
    first = f"{label}: {title}, ({location} 원본에 표시된 공간에서 확인한 여러 구획의 배치 부분)."
    second = f"{label} {target}: {prose} 다른 항목의 내용은 별도로 정리한다."
    SimpleDocTemplate(str(path), pagesize=(width + 100, 500), leftMargin=50, rightMargin=50,
                      topMargin=50, bottomMargin=50).build(
        [Paragraph(first, style), Spacer(1, 12), Paragraph(second, style)])
    doc = parse_document(str(path), document_id="public_natural", filename=path.name,
                         mime_type="application/pdf", sha256="0" * 64)
    assert not doc.parse_warnings
    rows = exhibit_rows(doc)
    assert len(rows) == 2
    assert all(row.get("duplicate_source") for row in rows)
    assert all(f["bbox"] is not None for row in rows for f in row["duplicate_source"]["fragments"])
    assert len(rows[0]["duplicate_source"]["fragments"]) >= 2
    found = _duplicates(doc)
    assert bool(found) == different
    if different:
        assert len(found) == 1 and str(found[0].evidence_grade) == "A"


@pytest.mark.parametrize("lines", [
    ["갑 제4호증: 냉각도, 별지 11쪽", "설명 중 을 제5호증을 언급한다.", "갑 제4호증 냉각도: 경로를 설명한다."],
    ["갑 제4호증: 냉각도, (별지 11쪽", '표시: 갑 제5호증: 제목 안에 둔 표시).', "갑 제4호증 냉각도: 경로를 설명한다."],
])
def test_public_inline_or_protected_reference_is_not_recovered_as_a_definition(lines):
    rows = exhibit_rows(_manual(lines))
    assert len(rows) == 2
    assert {r["number"] for r in rows} == {4}


def test_public_cross_branch_candidates_cannot_corroborate():
    found = _duplicates(_manual([
        "갑 제4호증의 1 사진, (별지 11쪽 북쪽).",
        "갑 제4호증의 1 사진, (별지 11쪽 남쪽).",
        "갑 제4호증의 2 사진: 경로를 설명한다.",
    ]))
    assert len(found) == 1
    assert found[0].confidence_features["exhibit"] == "갑 제4호증의 1"


def test_public_creation_date_and_protected_date_difference_remain_independent(tmp_path):
    doc = _parse(tmp_path, "txt", [
        ['갑 제4호증: 「대장 2046. 1. 2.」, (별지 11쪽', '수록 구역). 2049. 2. 30. 상태: 초안'],
        ['갑 제4호증 「대장 2046. 1. 3.」: 경로를 설명한다.'],
    ], False)
    assert len(_duplicates(doc)) == 1
    rows = exhibit_rows(doc)
    _numbering(doc, rows)
    assert any(r["kind"] == "creation_metadata" for r in rows[0]["duplicate_source"]["roles"])


def test_public_provenance_repeated_comparison_meets_ticket_time_bound():
    doc = _manual(["갑 제4호증: 냉각도, 별지 11쪽", "원본 표시 구역.", "갑 제4호증 냉각도: 경로를 설명한다."])
    rows = exhibit_rows(doc) * 2000
    started = time.perf_counter()
    assert not [f for f in _numbering(_manual([]), rows)
                if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert time.perf_counter() - started < 0.1
