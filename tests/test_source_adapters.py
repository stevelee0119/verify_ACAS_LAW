"""제10장 Source Adapter 계약.

실제 외부 API 없이 응답 형식 → 내부 표준 형태 변환을 고정한다.
공식 API 응답 스키마가 바뀌면 이 테스트가 먼저 깨져야 한다.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

import pytest

from packages.common.enums import AdapterStatus

LAW_RESPONSE: Dict[str, Any] = {
    "LawSearch": {
        "law": [
            {
                "법령명한글": "형법",
                "공포일자": "19530918",
                "시행일자": "19531003",
                "법령ID": "001234",
                "법령상세링크": "/lsInfoP.do?lsiSeq=1",
            }
        ]
    }
}
PREC_RESPONSE: Dict[str, Any] = {
    "PrecSearch": {
        "prec": [
            {
                "사건번호": "2020다12345",
                "법원명": "대법원",
                "선고일자": "20210311",
                "사건명": "손해배상(기)",
                "판결유형": "판결",
                "판시사항": "판시사항 본문이다.",
                "판결요지": "판결요지 본문이다.",
                "판례상세링크": "/precInfoP.do?precSeq=1",
            }
        ]
    }
}


class _Handler(BaseHTTPRequestHandler):
    received: Dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.received = query
        body = LAW_RESPONSE if query.get("target") == ["law"] else PREC_RESPONSE
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture()
def mock_law_api(monkeypatch):
    """국가법령정보 응답을 흉내내는 로컬 서버로 Adapter를 향하게 한다."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/DRF/lawSearch.do"

    import packages.source_adapters.law_go_kr as module

    monkeypatch.setattr(module, "SEARCH_URL", url)
    monkeypatch.setenv("LV_LAW_GO_KR_OC", "TEST_OC")
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")

    from packages.common import config

    config.reset_settings()
    from packages.source_adapters import SourceRegistry
    from packages.source_adapters.local_mirror import LocalLegalMirror

    registry = SourceRegistry()
    # Mirror에 자료가 있으면 외부 호출을 하지 않으므로 빈 Mirror로 교체한다
    registry.law.mirror = LocalLegalMirror(root=Path("/nonexistent-mirror"))
    yield registry
    server.shutdown()
    config.reset_settings()


def test_adapter_becomes_ready_with_key(mock_law_api):
    assert mock_law_api.law.status() == AdapterStatus.READY


def test_case_search_sends_required_parameters(mock_law_api):
    mock_law_api.law.search_case("2020다12345")
    query = _Handler.received
    assert query["OC"] == ["TEST_OC"], "OC 인증 파라미터가 전달되어야 한다"
    assert query["target"] == ["prec"]
    assert query["type"] == ["JSON"]


def test_case_response_is_normalized(mock_law_api):
    response = mock_law_api.law.search_case("2020다12345")
    assert response.status == AdapterStatus.READY
    record = response.records[0]
    assert record["case_number"] == "2020다12345"
    assert record["court"] == "대법원"
    assert record["decision_date"] == "2021-03-11", "YYYYMMDD가 ISO 형식으로 정규화되어야 한다"
    assert record["holding"] and record["summary"]


def test_law_response_is_normalized(mock_law_api):
    response = mock_law_api.law.search_law("형법")
    record = response.records[0]
    assert record["law_name"] == "형법"
    assert record["effective_from"] == "1953-10-03"
    assert record["promulgation_date"] == "1953-09-18"


def test_source_record_preserves_provenance(mock_law_api):
    """제15.3장: Source·Query·조회시각·응답 Hash·사용 필드를 보존한다."""
    response = mock_law_api.law.search_case("2020다12345")
    record = response.source_record
    assert record.adapter == "law_go_kr"
    assert record.query == "2020다12345"
    assert record.response_hash and len(record.response_hash) == 64
    assert record.used_fields and "사건번호" in record.used_fields
    assert record.retrieved_at is not None


def test_verification_uses_official_record(mock_law_api):
    """Adapter 응답이 Level 1·2 검증으로 이어진다."""
    from packages.common.enums import FindingType
    from packages.legal_engine import LegalVerifier, extract_from_text

    citations = extract_from_text(
        "대법원 2019. 1. 1. 선고 2020다12345 판결", document_id="D", block_id="B", page=1
    )
    result = LegalVerifier(mock_law_api).verify_citations(citations)
    # 문서의 선고일(2019-01-01)이 공식 기록(2021-03-11)과 다르므로 불일치가 나와야 한다
    assert any(f.type == FindingType.CASE_METADATA_MISMATCH for f in result.findings)


def test_unknown_response_shape_yields_zero_records_not_crash(monkeypatch):
    """응답 스키마가 바뀌어도 예외 대신 0건으로 처리해 Job을 실패시키지 않는다."""
    from packages.source_adapters.law_go_kr import _normalize_case_payload, _normalize_law_payload

    assert _normalize_case_payload({"UnexpectedRoot": {"items": [1, 2]}}) == []
    assert _normalize_law_payload({"UnexpectedRoot": []}) == []
    assert _normalize_case_payload(None) == []
