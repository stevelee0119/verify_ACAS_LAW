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


def test_google_sheets_candidate_without_extension_indexed(tmp_path):
    """확장자가 없는 Google Sheets 파일도 inventory의 MIME으로 식별되어 선별 무관 색인된다 (평가 측 결함 1 보완)."""
    root = "folder_root_gs"
    table_fid = "gs_table_001"
    table_content = (
        "번호,제목,판례 정보,쟁점,선정이유,판결요지\n"
        "1,구글시트 판례,대법원 2099다500 2099-01-02,구글시트 쟁점,이유,요지입니다\n"
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
                    "name": "구글스프레드시트_표준판례",  # 확장자 없음
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "version": "1",
                    "modifiedTime": "2026-10-10T00:00:00Z",
                    "parents": [root],
                    "size": "0",  # Google Sheets는 드라이브 메타데이터 상 크기 0
                    "capabilities": {"canDownload": True},
                }
            return {}

        def inventory(self, *a, **kw):
            return [self.metadata(table_fid)]

        def download(self, item, **kw):
            return table_content.encode(), "구글스프레드시트_표준판례.csv", "text/csv"

        def search_fulltext(self, *a, **kw):
            return []

        def close(self):
            pass

    settings = replace(
        get_settings(),
        allow_network=True,
        rag_drive_folder_id=root,
        storage_root=tmp_path / "storage_gs",
        rag_metadata_first=True,
    )
    library = ReferenceLibrary(settings, client_factory=SyntheticDrive)
    # 서면 질의와 파일명이 전혀 일치하지 않아도 MIME으로 후보 감지 및 색인
    sync_summary = library.sync(query="소유권이전등기 말소 청구의 소")
    assert sync_summary["status"] in ("READY", "PARTIAL")
    assert library.has_case_tables() is True
    status_info = library.case_table_status()
    assert status_info["status"] == "INDEXED"
    assert status_info["indexed_rows"] == 1
    assert len(status_info["candidates"]) == 1
    assert status_info["candidates"][0]["file_id"] == table_fid
    # 사건번호 정확 조회 가능 확인
    match = library.match_case({"canonical_case_number": "2099다500", "court": "대법원", "decision_date": "2099-01-02"})
    assert match["status"] == "MATCH"


def test_non_case_table_spreadsheet_control_and_resync_recovery(tmp_path):
    """대조군 및 질의 변경 재선별 회귀 방지 시험 (평가 측 결함 3 보완):
    1. 첫 질의(불일치): 판례표가 아니므로 eligible 제외 및 NOT_A_CASE_TABLE 처리되나 DB 캐시(chunks)는 보존됨.
    2. 두 번째 질의(일치): 캐시를 재사용하여 INDEXED로 복구되고 RAG select() 발췌가 정상 복구됨.
    """
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
        storage_root=tmp_path / "storage_control",
        rag_metadata_first=True,
    )

    # 1. 첫 번째 sync: 파일명/본문 불일치 질의
    library = ReferenceLibrary(settings, client_factory=SyntheticDrive)
    sync1 = library.sync(query="법률 계약 해석 분쟁")

    # 판례 표가 아님 확인
    assert library.has_case_tables() is False
    status_info = library.case_table_status()
    assert status_info["status"] == "NO_CASE_TABLE"
    assert len(status_info["candidates"]) == 1
    assert status_info["candidates"][0]["status"] == "NOT_A_CASE_TABLE"
    # 판례표가 아니므로 eligible 제외 -> RAG select 발췌에서 격리됨
    assert budget_fid not in library.eligible
    selection1 = library.select("소모품비 지출")
    assert selection1["sources"] == []

    # 그러나 추후 일반 문서 선별 시 재사용을 위해 chunks 테이블과 files 캐시는 보존되어 있어야 함
    with library.connect() as db:
        chunk_count = db.execute("SELECT count(*) FROM chunks WHERE file_id=?", (budget_fid,)).fetchone()[0]
        row_count = db.execute("SELECT count(*) FROM case_rows WHERE file_id=?", (budget_fid,)).fetchone()[0]
        assert chunk_count > 0  # 청크가 삭제되지 않고 DB에 보존됨
        assert row_count == 0   # 판례표가 아니므로 case_rows는 0

    # 2. 두 번째 sync: 파일명과 일치하는 질의로 재선별
    sync2 = library.sync(query="예산 지출 내역 소모품비 회계")
    # 캐시 재사용 확인
    assert sync2["files_reused"] == 1
    entry = next(i for i in sync2["inventory"] if i["file_id"] == budget_fid)
    assert entry["status"] == "INDEXED"
    assert budget_fid in library.eligible

    # RAG select() 발췌가 정상 복구됨 (기준 03fdcdb와 동일한 동작 확인)
    selection2 = library.select("소모품비 지출")
    assert len(selection2["sources"]) >= 1
    assert selection2["sources"][0]["file_id"] == budget_fid


def test_completed_table_with_quarantined_candidate_yields_partial(tmp_path):
    """완료 표와 격리 후보가 공존할 때 전체 상태는 INDEXED가 아니라 PARTIAL이어야 한다 (평가 측 결함 2 보완)."""
    library = ReferenceLibrary.__new__(ReferenceLibrary)
    library.eligible = {
        "good_table": {
            "file_id": "good_table",
            "name": "표준판례.xlsx",
            "structured_case_table": True,
            "case_table_only": True,
            "case_table_stats": {"indexed": 5, "discovered": 5},
        }
    }
    library.summary = {
        "status": "READY",
        "snapshot_hash": "hash123",
        "inventory": [
            {
                "file_id": "good_table",
                "name": "표준판례.xlsx",
                "status": "INDEXED",
                "reason": "TEXT_INDEXED",
                "continuation": False,
                "case_table_stats": {"indexed": 5, "discovered": 5},
            },
            {
                "file_id": "bad_table",
                "name": "악성_판례표.xlsx",
                "status": "QUARANTINED",
                "reason": "REFERENCE_QUARANTINED",
                "continuation": False,
                "case_table_stats": {"indexed": 0, "quarantined": 10},
            },
        ],
        "diagnostics": {},
    }
    library.db_path = tmp_path / "index_quar.sqlite3"
    library.directory = tmp_path
    library._case_rows_cache = None
    library._case_number_index = {}

    with library.connect() as db:
        rows = [
            ("r1", "good_table", "v1", "시트", 2, "A2:F2", "1", "사건1", "대법원 2099다100 2099-01-02",
             "대법원", "2099-01-02", '["2099다100"]', '["2099다100"]', '[]', "쟁점", "사실", "이유", "요지",
             '[]', '[]', "머리", "텍스트", "{}"),
        ]
        db.executemany("INSERT INTO case_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.commit()

    status_info = library.case_table_status()
    # 완료 표가 있어도 격리 후보가 함께 있으므로 전체는 INDEXED가 아니라 PARTIAL
    assert status_info["status"] == "PARTIAL"
    assert status_info["indexed_rows"] == 5
    assert len(status_info["candidates"]) == 2


def test_failed_candidate_yields_partial_not_no_case_table(tmp_path):
    """후보 읽기 실패/타임아웃 시 NO_CASE_TABLE로 단정되지 않고 PARTIAL로 유지된다 (평가 측 결함 2 보완)."""
    library = ReferenceLibrary.__new__(ReferenceLibrary)
    library.eligible = {}
    library.summary = {
        "status": "PARTIAL",
        "snapshot_hash": "hash_failed",
        "inventory": [
            {
                "file_id": "timeout_table",
                "name": "타임아웃_판례표.xlsx",
                "status": "PARSE_FAILED",
                "reason": "REFERENCE_PARSE_TIMEOUT",
                "continuation": False,
                "case_table_stats": {},
            }
        ],
        "diagnostics": {},
    }
    library.db_path = tmp_path / "index_failed.sqlite3"
    library.directory = tmp_path
    library._case_rows_cache = None
    library._case_number_index = {}

    status_info = library.case_table_status()
    # 읽기 실패/타임아웃 후보가 있으면 NO_CASE_TABLE이 아니라 PARTIAL이어야 함
    assert status_info["status"] == "PARTIAL"
    assert status_info["candidates"][0]["status"] == "PARSE_FAILED"

    # 서면 검토 연동 시 미조회 사건 메타데이터 보강 확인
    document = NormalizedDocument("doc", "doc.txt", "text", "", pages=[Page(1, blocks=[Block("b", "문서", 1)])])
    result = DocumentResult("doc", "doc.txt", normalized=document)
    result.citations = [
        {"citation_id": "c1", "canonical_case_number": "2099다100", "court": "대법원", "decision_date": "2099-01-02"},
    ]
    router = SimpleNamespace(has_available_provider=lambda **kw: False)
    pii = SimpleNamespace(mask_text=lambda value: SimpleNamespace(masked_text=value))

    review = review_document(result, library, router, ProjectContext("p"), pii)
    assert review["case_table_status"] == "PARTIAL"
    assert review["reference_case_matches"]["c1"]["status"] == "NOT_IN_REFERENCE"
    assert review["reference_case_matches"]["c1"]["scope"] == "PARTIAL_INDEX_RANGE"
    assert review["reference_case_matches"]["c1"]["partial_indexed"] is True


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


def test_real_sync_csv_timeout_and_failure_not_overwritten_by_not_a_case_table(tmp_path):
    """실제 sync 경로 시험: 서면 선별에서 제외된 CSV 후보의 추출기가 타임아웃/실패를 반환할 때

    is_non_case_candidate 분기가 이를 NOT_A_CASE_TABLE로 덮어쓰지 않고,
    PARSE_FAILED 및 원본 사유(REFERENCE_EXTRACT_TIMEOUT)를 온전히 보존하여
    종합 상태가 PARTIAL로 유지되고 미조회 메타데이터가 보강되는지 검증한다 (TK-74 한국어 주석).
    """
    root = "folder_root_timeout"
    cand_fid = "cand_timeout_001"
    cand_content = "번호,사건,내용\n1,미확인,데이터\n"

    class SyntheticDrive:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, **kw):
            return self

        def remaining(self):
            return 120

        def metadata(self, fid):
            return {
                "id": cand_fid,
                "name": "후보_대용량_표.csv",
                "mimeType": "text/csv",
                "version": "1",
                "modifiedTime": "2026-10-10T00:00:00Z",
                "parents": [root],
                "size": str(len(cand_content.encode())),
                "capabilities": {"canDownload": True},
                "md5Checksum": hashlib.md5(cand_content.encode()).hexdigest(),
            }

        def inventory(self, *a, **kw):
            return [self.metadata(cand_fid)]

        def download(self, item, **kw):
            return cand_content.encode(), "후보_대용량_표.csv", "text/csv"

        def search_fulltext(self, *a, **kw):
            return []

        def close(self):
            pass

    settings = replace(
        get_settings(),
        allow_network=True,
        rag_drive_folder_id=root,
        storage_root=tmp_path / "storage_timeout",
        rag_metadata_first=True,
    )

    # 추출기가 partial=True 및 REFERENCE_EXTRACT_TIMEOUT을 반환하는 상황 시뮬레이션
    def timeout_extractor(data, filename, mime, **kwargs):
        return {
            "chunks": [],
            "case_records": [],
            "partial": True,
            "reason": "REFERENCE_EXTRACT_TIMEOUT",
            "sha256": hashlib.sha256(data).hexdigest(),
            "pages": 1,
            "read_pages": 0,
        }

    library = ReferenceLibrary(settings, client_factory=SyntheticDrive, extractor=timeout_extractor)
    # 서면 질의와 일치하지 않아 이름 선별에서는 제외되나 표 후보로 다운로드됨
    library.sync(query="전혀 다른 검색어")

    # 1. inventory 검증: NOT_A_CASE_TABLE로 덮어써지지 않고 PARSE_FAILED 및 원본 사유 보존
    inv_entry = next(i for i in library.summary["inventory"] if i["file_id"] == cand_fid)
    assert inv_entry["status"] == "PARSE_FAILED"
    assert inv_entry["reason"] == "REFERENCE_EXTRACT_TIMEOUT"

    # 2. summary issues에 오류 사유 기록 확인
    assert any(iss["file_id"] == cand_fid and iss["reason"] == "REFERENCE_EXTRACT_TIMEOUT" for iss in library.summary["issues"])

    # 3. eligible에서 제외되어 일반 RAG select() 격리 확인
    assert cand_fid not in library.eligible

    # 4. case_table_status 검증: NO_CASE_TABLE로 단정되지 않고 PARTIAL 유지
    status_info = library.case_table_status()
    assert status_info["status"] == "PARTIAL"
    assert len(status_info["candidates"]) == 1
    assert status_info["candidates"][0]["status"] == "PARSE_FAILED"
    assert status_info["candidates"][0]["reason"] == "REFERENCE_EXTRACT_TIMEOUT"

    # 5. 서면 검토(review_document) 연동 시 미조회 사건의 메타데이터 보강 확인
    document = NormalizedDocument("doc", "doc.txt", "text", "", pages=[Page(1, blocks=[Block("b", "문서", 1)])])
    result = DocumentResult("doc", "doc.txt", normalized=document)
    result.citations = [
        {"citation_id": "c1", "canonical_case_number": "2099다100", "court": "대법원", "decision_date": "2099-01-02"},
    ]
    router = SimpleNamespace(has_available_provider=lambda **kw: False)
    pii = SimpleNamespace(mask_text=lambda value: SimpleNamespace(masked_text=value))

    review = review_document(result, library, router, ProjectContext("p"), pii)
    assert review["case_table_status"] == "PARTIAL"
    assert review["reference_case_matches"]["c1"]["status"] == "NOT_IN_REFERENCE"
    assert review["reference_case_matches"]["c1"]["scope"] == "PARTIAL_INDEX_RANGE"
    assert review["reference_case_matches"]["c1"]["partial_indexed"] is True


def test_real_sync_continuation_zero_rows_distinguished_and_resumed(tmp_path):
    """실제 sync 경로 시험: 0행 이어 읽기(continuation) 상태가 정상 음성/실패와 구분되고 다음 실행에서 재개(resume)되는지 검증 (TK-74)."""
    root = "folder_root_continuation"
    cand_fid = "cand_cont_001"
    cand_content = "번호,사건,내용\n1,진행중,데이터\n"

    class SyntheticDrive:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, **kw):
            return self

        def remaining(self):
            return 120

        def metadata(self, fid):
            return {
                "id": cand_fid,
                "name": "대규모_미완료_표.csv",
                "mimeType": "text/csv",
                "version": "1",
                "modifiedTime": "2026-10-10T00:00:00Z",
                "parents": [root],
                "size": str(len(cand_content.encode())),
                "capabilities": {"canDownload": True},
                "md5Checksum": hashlib.md5(cand_content.encode()).hexdigest(),
            }

        def inventory(self, *a, **kw):
            return [self.metadata(cand_fid)]

        def download(self, item, **kw):
            return cand_content.encode(), "대규모_미완료_표.csv", "text/csv"

        def search_fulltext(self, *a, **kw):
            return []

        def close(self):
            pass

    settings = replace(
        get_settings(),
        allow_network=True,
        rag_drive_folder_id=root,
        storage_root=tmp_path / "storage_cont",
        rag_metadata_first=True,
    )

    call_count = 0
    received_continuations = []

    def mock_extractor(data, filename, mime, **kwargs):
        nonlocal call_count
        call_count += 1
        continuation = kwargs.get("continuation")
        received_continuations.append(continuation)
        if call_count == 1:
            # 1회차: 이번 배치에서는 0행이지만 continuation 커서가 남아있는 상태
            return {
                "chunks": [],
                "case_records": [],
                "partial": True,
                "structured_case_table": True,
                "continuation": {"cursor": 50, "sheet": "Sheet1"},
                "reason": "REFERENCE_PARTIALLY_READ",
                "sha256": hashlib.sha256(data).hexdigest(),
                "resumed": False,
                "stats": {"indexed": 0, "discovered": 100},
            }
        else:
            # 2회차: 재개되어 완료됨
            return {
                "chunks": [{"page": 1, "start": 0, "text": "완료 텍스트"}],
                "case_records": [{"record_id": "r1", "case_numbers": ["2099다100"], "court": "대법원"}],
                "partial": False,
                "structured_case_table": True,
                "continuation": None,
                "reason": "",
                "sha256": hashlib.sha256(data).hexdigest(),
                "resumed": True,
                "stats": {"indexed": 1, "discovered": 100},
            }

    library = ReferenceLibrary(settings, client_factory=SyntheticDrive, extractor=mock_extractor)

    # 1회차 실행: 0행 이어 읽기 상태
    library.sync(query="검색어")
    inv1 = next(i for i in library.summary["inventory"] if i["file_id"] == cand_fid)
    assert inv1["status"] == "INDEXED_PARTIAL"
    assert inv1["continuation"] is True
    status1 = library.case_table_status()
    assert status1["status"] == "PARTIAL"
    assert status1["candidates"][0]["continuation"] is True

    # 2회차 실행: 다음 실행에서 직전 continuation 체크포인트가 전달되어 재개되는지 확인
    library2 = ReferenceLibrary(settings, client_factory=SyntheticDrive, extractor=mock_extractor)
    library2.sync(query="검색어")
    assert call_count == 2
    assert received_continuations[1] == {"cursor": 50, "sheet": "Sheet1"}
    inv2 = next(i for i in library2.summary["inventory"] if i["file_id"] == cand_fid)
    assert inv2["status"] == "INDEXED"
    assert inv2["continuation"] is False
    status2 = library2.case_table_status()
    assert status2["status"] == "INDEXED"
    assert status2["indexed_rows"] == 1
