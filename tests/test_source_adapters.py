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


def test_oc_credential_never_reaches_source_records():
    """상세링크에 실려 오는 OC(OPEN API 식별자)가 보고서로 새어나가면 안 된다."""
    from packages.source_adapters.law_go_kr import _normalize_case_payload, _normalize_law_payload

    case = _normalize_case_payload({"PrecSearch": {"prec": [{
        "사건번호": "2024도12341",
        "판례상세링크": "/DRF/lawService.do?OC=DL_stevelaw&target=prec&ID=619505",
    }]}})[0]
    law = _normalize_law_payload({"LawSearch": {"law": [{
        "법령명한글": "민법",
        "법령상세링크": "/DRF/lawService.do?OC=DL_stevelaw&target=law&MST=1",
    }]}})[0]
    for record in (case, law):
        assert "DL_stevelaw" not in str(record)
        assert "[REDACTED]" in str(record["detail_link"])


def test_case_lookup_tries_a_second_query_shape_before_giving_up(mock_law_api, monkeypatch):
    """조회 방식이 하나뿐이면 그 방식이 맞지 않는 사건 유형이 통째로 미확인이 된다.

    배포에서 대법원 2011모1839(형사 재항고 결정)가 확인되지 않았다. 본문검색이
    빗나가는 유형을 위해 사건번호 지정 조회를 대안으로 둔다. 채택 조건은 여전히
    사건번호 완전일치이므로, 대안이 오탐을 만들 수는 없다.
    """
    seen = []

    def spy(url, *, params=None, **kwargs):
        seen.append(dict(params or {}))
        return original(url, params=params, **kwargs)

    adapter = mock_law_api.law
    original = adapter._http_get
    monkeypatch.setattr(adapter, "_http_get", spy)

    adapter.search_case("2099도99999")           # 존재하지 않는 사건
    shapes = [tuple(sorted(k for k in p if k not in ("OC", "target", "type", "display", "page"))) for p in seen]
    assert ("query", "search") in shapes, shapes
    assert ("nb",) in shapes, "사건번호 지정 조회를 시도해야 한다"

    # 법원·선고일을 덧붙인 조합 질의에는 대안을 붙이지 않는다(요청 낭비).
    seen.clear()
    adapter.search_case("대법원 2099도99999")
    assert all("nb" not in p for p in seen), seen


def test_case_lookup_stops_at_the_matching_shape(mock_law_api, monkeypatch):
    """사건번호가 일치하면 더 조회하지 않는다."""
    seen = []
    adapter = mock_law_api.law
    original = adapter._http_get

    def spy(url, *, params=None, **kwargs):
        seen.append(dict(params or {}))
        return original(url, params=params, **kwargs)

    monkeypatch.setattr(adapter, "_http_get", spy)
    response = adapter.search_case("2020다12345")   # mock이 일치 기록을 돌려주는 사건
    assert response.records
    assert len(seen) == 1, f"일치했는데도 추가 조회가 일어났다: {seen}"


# --- 결정(모) 사건이 조회부터 전문까지 이어지는가 -------------------------------
DECISION_RESPONSE: Dict[str, Any] = {
    "PrecSearch": {"prec": [{
        "사건번호": "2011모1839",
        "법원명": "대법원",
        "선고일자": "20110526",
        "사건명": "준항고기각결정에대한재항고",
        "판결유형": "결정",
        "판시사항": "판시사항 본문이다.",
        "판결요지": "판결요지 본문이다.",
        "판례일련번호": "123456",
        "판례상세링크": "/precInfoP.do?precSeq=123456",
    }]}
}
DECISION_DETAIL: Dict[str, Any] = {
    "PrecService": {
        "사건번호": "2011모1839", "법원명": "대법원", "선고일자": "20110526",
        "판결유형": "결정",
        "판례내용": "이 사건 결정의 전문이다. 압수·수색의 범위에 관하여 판시한다.",
    }
}


def test_decision_case_flows_from_lookup_to_full_text(monkeypatch, tmp_path):
    """결정(모) 사건도 조회 → 사건번호 일치 → 전문 확보까지 이어져야 한다.

    전문이 없으면 파이프라인의 의미·적용 검토(AI 단계)가 "공식 판결 전문이 없어
    수행하지 않음"으로 건너뛴다. 조회가 막히면 AI도 아무 일을 하지 않는다.
    """
    import packages.source_adapters.law_go_kr as module
    from packages.common.enums import AdapterStatus
    from packages.source_adapters.law_go_kr import LawGoKrAdapter
    from packages.source_adapters.local_mirror import LocalLegalMirror

    monkeypatch.setenv("LV_LAW_GO_KR_OC", "TEST_OC")
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")
    from packages.common import config
    config.reset_settings()

    class _Resp:
        status_code = 200
        def __init__(self, body): self._body = body
        def json(self): return self._body
        def raise_for_status(self): return None

    adapter = LawGoKrAdapter(mirror=LocalLegalMirror(root=tmp_path / "none"))
    calls = []

    def fake_get(url, *, params=None, **kwargs):
        calls.append(dict(params or {}))
        if url == module.SERVICE_URL:
            return _Resp(DECISION_DETAIL)
        # 본문검색(search=2)은 이 사건을 돌려주지 못한다고 가정한다.
        if (params or {}).get("search") == 2:
            return _Resp({"PrecSearch": {"prec": []}})
        return _Resp(DECISION_RESPONSE)

    monkeypatch.setattr(adapter, "_http_get", fake_get)

    response = adapter.search_case("2011모1839")
    assert response.status == AdapterStatus.READY
    assert [r["case_number"] for r in response.records] == ["2011모1839"], \
        "대안 조회로 결정 사건을 찾아야 한다"

    detail = adapter.fetch_case(response.records[0])
    assert detail.records and detail.records[0].get("full_text"), \
        "전문이 없으면 의미·적용 검토가 통째로 건너뛰어진다"
    config.reset_settings()
