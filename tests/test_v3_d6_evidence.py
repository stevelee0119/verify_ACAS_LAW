"""v3 D6·G6: 호증 표기 전용 파서, 표 셀 단위 자료명, 증거 파일 미입력 알림 묶기.

재현: 테스트셋 v1 TC-01 "갑 제5호증의 1 내지 3 각 진술서" → '내지 3각 진술서', TC-05 표 행이 한 줄로 붙은
"징계처분서2026. 4. 28.피고이 사건 처분의…". 합성: 민사·국가배상·형사 분야 호증 표기.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from packages.claim_engine.attachments import analyze_attachments
from packages.claim_engine.exhibits import parse_exhibit_label
from packages.common.schemas import Block, NormalizedDocument, Page


@pytest.mark.parametrize("text, expected", [
    ("갑 제5호증의 1 내지 3 각 진술서", ("갑", 5, 1, 3, "진술서")),                 # 행정(재현)
    ("을 제2호증의2 진단서(○○병원)", ("을", 2, 2, 2, "진단서(○○병원)")),          # 국가배상
    ("갑제10호증 부동산등기사항전부증명서", ("갑", 10, None, None, "부동산등기사항전부증명서")),  # 민사
    ("갑 제3호증의 1~4 각 금융거래내역", ("갑", 3, 1, 4, "금융거래내역")),          # 민사
    ("증 제7호증 압수조서", ("증", 7, None, None, "압수조서")),                     # 형사
])
def test_exhibit_label_parser(text, expected):
    parsed = parse_exhibit_label(text)
    assert (parsed["party"], parsed["number"], parsed["branch_from"], parsed["branch_to"], parsed["name"]) == expected


def test_branch_range_lists_every_branch():
    assert parse_exhibit_label("갑 제5호증의 1 내지 3 각 진술서")["branches"] == [1, 2, 3]


def _doc(lines, *, table_lines=()):
    blocks = [Block(block_id=f"b{i}", text=t, page=1, block_type="table_line" if i in table_lines else "paragraph")
              for i, t in enumerate(lines)]
    return NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="x",
                              pages=[Page(page_number=1, blocks=blocks)])


def test_reproduction_range_label_gives_the_real_document_name():
    result = analyze_attachments(_doc(["입증방법", "1. 갑 제5호증의 1 내지 3 각 진술서", "2. 갑 제6호증 처벌불원서"]))
    names = [i["name"] for i in result["items"]]
    assert "진술서" in names and not any("내지" in n for n in names)


def test_reproduction_glued_table_rows_are_not_read_as_list_items():
    result = analyze_attachments(_doc(["갑 제1호증 징계처분서2026. 4. 28.피고이 사건 처분의 존재 및 내용"], table_lines={0}))
    assert not any("2026" in i["name"] for i in result["items"])


def test_missing_evidence_is_one_info_notice_per_document_when_no_evidence_file_was_uploaded():
    lines = ["입증방법"] + [f"{n}. 갑 제{n}호증 자료{n}" for n in range(1, 8)]
    result = analyze_attachments(_doc(lines))
    [notice] = result["findings"]
    assert str(notice.severity) == "INFO" and "첨부 증거 7건이 입력에 없음" in notice.title
    assert len(notice.confidence_features["missing_items"]) == 7


def test_individual_comparison_only_when_evidence_files_were_uploaded():
    lines = ["입증방법", "1. 갑 제1호증 징계처분서", "2. 갑 제2호증 표창장 사본"]
    uploads = [{"document_id": "e1", "filename": "징계처분서.pdf", "sha256": "0" * 64}]
    result = analyze_attachments(_doc(lines), uploads)
    statuses = {i["name"]: i["status"] for i in result["items"]}
    assert statuses["징계처분서"] == "ATTACHED" and statuses["표창장 사본"] == "REFERENCE_MISSING"
    assert [f.title for f in result["findings"]] == ["첨부·증거로 적힌 자료를 입력 파일에서 찾지 못함: 표창장 사본"]


def test_reproduction_tc05_names_come_from_cells():
    from packages.document_engine import parse_document
    path = next(Path("tests/fixtures/legal_verifier_testset").glob("TC-05*.pdf"))
    doc = parse_document(str(path), document_id="TC-05", filename=path.name, mime_type="",
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    names = [i["name"] for i in analyze_attachments(doc)["items"]]
    assert "징계처분서" in names and not any(any(ch.isdigit() for ch in n[:6]) and "." in n for n in names), names
