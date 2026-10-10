"""TK-74 합성 자료 시험: 문서 단위 선별과 무관한 표준판례 표 색인 경로 및 판례 대조 검증.

실제 Drive 자료나 비공개 판례 문구는 저장소에 넣지 않으며, 모든 시험 데이터는 합성(synthetic)이다.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

import pytest

from packages.common.config import get_settings
from packages.common.schemas import NormalizedDocument, Page, Block
from packages.rag_engine.library import ReferenceLibrary, is_case_table_candidate
from packages.rag_engine.review import review_document
from packages.verification_engine.pipeline import DocumentResult, ProjectContext


def test_is_case_table_candidate_repeated_performance():
    """표 후보 판별 반복 입력 시간 시험 (2,500회 0.1초 이내)."""
    items = [
        {"name": "표준판례.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size": 1024},
        {"name": "참고자료.pdf", "mimeType": "application/pdf", "size": 2048},
        {"name": "data.csv", "mimeType": "text/csv", "size": 512},
        {"name": "google_sheet", "mimeType": "application/vnd.google-apps.spreadsheet", "size": 0},
        {"name": "huge.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size": 100 * 1024 * 1024},
    ] * 500
    t0 = time.perf_counter()
    results = [is_case_table_candidate(item) for item in items]
    t1 = time.perf_counter()
    assert len(results) == 2500
    assert results[0] is True
    assert results[1] is False
    assert results[2] is True
    assert results[3] is True
    assert results[4] is False  # 96MB 초과
    assert (t1 - t0) < 0.1


def test_case_table_indexed_without_name_match_real_path(tmp_path, monkeypatch):
    """실제 선별 경로 합성 시험: 서면 낱말과 불일치하는 판례 표가 게이트 제외와 무관하게 색인되고 정확 조회가 연결된다."""
    root = "folder_root_001"
    table_fid = "table_file_001"
    table_content = (
        "번호,제목,판례 정보,쟁점,선정이유,판결요지\n"
        "1,합성 일치 사건,대법원 2099다100 2099-01-02,계약 요건,선정 근거,계약의 주요 요건을 판단하였다\n"
        "2,합성 불일치 사건,대법원 2099다200 2099-01-02,손해배상,선정 근거,손해배상 범위를 판단하였다\n"
    )

    class SyntheticDrive:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, **kw):
            return self

        def remaining(self):
            return 120

        def metadata(self, fid):
            if fid == table_fid:
                return {
                    "id": table_fid,
                    "name": "일반_자료_목록_종합.csv",  # 서면 낱말("근로", "계약", "해고")과 전혀 일치하지 않는 이름
                    "mimeType": "text/csv",
                    "version": "1",
                    "modifiedTime": "2026-10-10T00:00:00Z",
                    "parents": [root],
                    "size": str(len(table_content.encode())),
                    "capabilities": {"canDownload": True},
                    "md5Checksum": hashlib.md5(table_content.encode()).hexdigest(),
                }
            return {}

        def inventory(self, *a, **kw):
            return [self.metadata(table_fid)]

        def download(self, item, **kw):
            return table_content.encode(), "일반_자료_목록_종합.csv", "text/csv"

        def search_fulltext(self, folders, words):
            return []  # Drive 본문 검색에서도 매칭 없음

        def close(self):
            pass

    settings = replace(
        get_settings(),
        allow_network=True,
        rag_drive_folder_id=root,
        storage_root=tmp_path / "storage",
        rag_max_files=10,
        rag_download_mb=32,
        rag_metadata_first=True,
    )

    library = ReferenceLibrary(settings, client_factory=SyntheticDrive)

    # 서면 질의(해고무효, 근로기준법)와 파일명/본문이 완전히 불일치하는 상태로 동기화 실행
    sync_summary = library.sync(query="근로기준법 제23조 해고무효확인 및 임금 청구의 소")
    assert sync_summary["status"] in ("READY", "PARTIAL")

    # 1. 파일명 무관 표 후보 감지 및 색인 확인
    assert library.has_case_tables() is True
    status_info = library.case_table_status()
    assert status_info["status"] == "INDEXED"
    assert status_info["indexed_rows"] == 2
    assert len(status_info["candidates"]) == 1
    assert status_info["candidates"][0]["file_id"] == table_fid
    assert status_info["candidates"][0]["status"] == "INDEXED"

    # 2. 일반 발췌(select) 격리 확인: prose retrieval에 표 행 chunk가 주입되지 않음
    prose_selection = library.select("근로계약 해고 요건")
    assert prose_selection["sources"] == []
    assert prose_selection["decision"] in ("NOT_USED", "NO_ELIGIBLE_REFERENCE")

    # 3. 서면 검토(review_document) 연결 및 3종 대조 결과 확인
    # - c1: 사건번호, 법원, 선고일 모두 일치 (MATCH)
    # - c2: 사건번호 일치, 선고일 불일치 (METADATA_MISMATCH)
    # - c3: 표에 없는 사건번호 (NOT_IN_REFERENCE)
    doc_text = "원고는 대법원 2099다100 판결 및 대법원 2099다200 판결, 대법원 2099다999 판결을 인용한다."
    document = NormalizedDocument(
        "doc1", "doc1.txt", "text", "",
        pages=[Page(1, blocks=[Block("b1", doc_text, 1)])]
    )
    result = DocumentResult("doc1", "doc1.txt", normalized=document)
    result.citations = [
        {"citation_id": "c1", "canonical_case_number": "2099다100", "court": "대법원", "decision_date": "2099-01-02"},
        {"citation_id": "c2", "canonical_case_number": "2099다200", "court": "대법원", "decision_date": "2099-05-05"},  # 불일치 날짜
        {"citation_id": "c3", "canonical_case_number": "2099다999", "court": "대법원", "decision_date": "2099-01-02"},  # 부재 사건
    ]

    router = SimpleNamespace(has_available_provider=lambda **kw: False)
    pii = SimpleNamespace(mask_text=lambda value: SimpleNamespace(masked_text=value))

    review = review_document(result, library, router, ProjectContext("proj"), pii)

    # 일반 prose sources가 0건이어도 표 대조 결과와 상태가 정상 수록됨 (평가 측 조건 3)
    assert review["case_table_status"] == "INDEXED"
    assert "reference_case_matches" in review
    matches = review["reference_case_matches"]
    assert matches["c1"]["status"] == "MATCH"
    assert matches["c1"]["court"] == "대법원"
    assert matches["c2"]["status"] == "METADATA_MISMATCH"
    assert matches["c3"]["status"] == "NOT_IN_REFERENCE"


def test_non_case_table_spreadsheet_control_not_indexed_as_rag(tmp_path):
    """대조군 시험: 판례표 머리글이 없는 스프레드시트는 NOT_A_CASE_TABLE로 판정되고 RAG chunk로 색인되지 않는다."""
    root = "folder_root_002"
    budget_fid = "budget_file_001"
    budget_content = "일자,항목,수입,지출,잔액\n2099-01-01,소모품비,0,50000,100000\n"

    class SyntheticDrive:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, **kw):
            return self

        def remaining(self):
            return 120

        def metadata(self, fid):
            return {
                "id": budget_fid,
                "name": "예산_지출_내역.csv",
                "mimeType": "text/csv",
                "version": "1",
                "modifiedTime": "2026-10-10T00:00:00Z",
                "parents": [root],
                "size": str(len(budget_content.encode())),
                "capabilities": {"canDownload": True},
                "md5Checksum": hashlib.md5(budget_content.encode()).hexdigest(),
            }

        def inventory(self, *a, **kw):
            return [self.metadata(budget_fid)]

        def download(self, item, **kw):
            return budget_content.encode(), "예산_지출_내역.csv", "text/csv"

        def search_fulltext(self, *a, **kw):
            return []

        def close(self):
            pass

    settings = replace(
        get_settings(),
        allow_network=True,
        rag_drive_folder_id=root,
        storage_root=tmp_path / "storage",
        rag_metadata_first=True,
    )

    library = ReferenceLibrary(settings, client_factory=SyntheticDrive)
    library.sync(query="법률 계약 해석 분쟁")

    # 판례 표가 아님 확인
    assert library.has_case_tables() is False
    status_info = library.case_table_status()
    assert status_info["status"] == "NO_CASE_TABLE"
    assert len(status_info["candidates"]) == 1
    assert status_info["candidates"][0]["status"] == "NOT_A_CASE_TABLE"

    # RAG chunks에도 들어가지 않음
    with library.connect() as db:
        chunk_count = db.execute("SELECT count(*) FROM chunks WHERE file_id=?", (budget_fid,)).fetchone()[0]
        row_count = db.execute("SELECT count(*) FROM case_rows WHERE file_id=?", (budget_fid,)).fetchone()[0]
        assert chunk_count == 0
        assert row_count == 0


def test_partial_indexing_distinguished_from_no_case_table(tmp_path):
    """부분 색인 상태가 NO_CASE_TABLE과 명확히 구분되며, 미조회 사건에 partial_indexed 메타데이터가 보강된다 (평가 측 조건 2)."""
    library = ReferenceLibrary.__new__(ReferenceLibrary)
    library.eligible = {
        "file1": {
            "file_id": "file1",
            "name": "부분_판례표.xlsx",
            "structured_case_table": True,
            "case_table_only": True,
            "case_table_stats": {"indexed": 1, "discovered": 10},
        }
    }
    library.summary = {
        "status": "PARTIAL",
        "snapshot_hash": "synthetic_hash",
        "inventory": [
            {
                "file_id": "file1",
                "name": "부분_판례표.xlsx",
                "status": "INDEXED_PARTIAL",
                "reason": "REFERENCE_PARTIALLY_READ",
                "continuation": True,
                "case_table_stats": {"indexed": 1, "discovered": 10},
            }
        ],
        "diagnostics": {},
    }
    library.db_path = tmp_path / "index.sqlite3"
    library.directory = tmp_path
    library._case_rows_cache = None
    library._case_number_index = {}

    with library.connect() as db:
        rows = [
            ("r1", "file1", "v1", "시트", 2, "A2:F2", "1", "합성 사건", "대법원 2099다100 2099-01-02",
             "대법원", "2099-01-02", '["2099다100"]', '["2099다100"]', '[]', "쟁점", "사실", "이유", "요지",
             '[]', '[]', "[시트] 대법원 2099다100", "텍스트", "{}"),
        ]
        db.executemany("INSERT INTO case_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.commit()

    status_info = library.case_table_status()
    # 1. 완전 부재(NO_CASE_TABLE)가 아니라 PARTIAL 상태임
    assert status_info["status"] == "PARTIAL"
    assert status_info["candidates"][0]["continuation"] is True

    # 2. 서면 검토 연동 시 미조회 사건의 메타데이터 보강 확인
    document = NormalizedDocument("doc", "doc.txt", "text", "", pages=[Page(1, blocks=[Block("b", "문서", 1)])])
    result = DocumentResult("doc", "doc.txt", normalized=document)
    result.citations = [
        {"citation_id": "c_found", "canonical_case_number": "2099다100", "court": "대법원", "decision_date": "2099-01-02"},
        {"citation_id": "c_missing", "canonical_case_number": "2099다999", "court": "대법원", "decision_date": "2099-01-02"},
    ]
    router = SimpleNamespace(has_available_provider=lambda **kw: False)
    pii = SimpleNamespace(mask_text=lambda value: SimpleNamespace(masked_text=value))

    review = review_document(result, library, router, ProjectContext("p"), pii)

    assert review["case_table_status"] == "PARTIAL"
    matches = review["reference_case_matches"]
    assert matches["c_found"]["status"] == "MATCH"
    # 미조회 사건: 기존 NOT_IN_REFERENCE 계약 유지 + 부분 색인 메타데이터 보강
    assert matches["c_missing"]["status"] == "NOT_IN_REFERENCE"
    assert matches["c_missing"]["scope"] == "PARTIAL_INDEX_RANGE"
    assert matches["c_missing"]["partial_indexed"] is True
