"""Delayed source lookups are recovered before downstream legal analysis."""
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from packages.common.enums import AdapterStatus
from packages.legal_engine import LegalVerifier, extract_from_text
from packages.source_adapters import transport
from packages.source_adapters.law_go_kr import LawGoKrAdapter
from packages.source_adapters.local_mirror import LocalLegalMirror
from test_source_transport import install_mock


def verifier(tmp_path):
    adapter = LawGoKrAdapter(mirror=LocalLegalMirror(root=tmp_path / "empty"))
    adapter.settings = replace(adapter.settings, allow_network=True, law_go_kr_oc="test")
    return LegalVerifier(SimpleNamespace(law=adapter))


def citations():
    return extract_from_text("대법원 2099. 1. 15. 선고 2099도99999 판결")


def official(request):
    return httpx.Response(200, json={"PrecSearch": {"prec": [{
        "사건번호": "2099도99999", "법원명": "대법원", "선고일자": "20990115",
        "판례일련번호": "synthetic", "판례내용": "Synthetic official text for a transport test only.",
    }]}})


def test_deferred_retry_replaces_timeout_findings_and_keeps_audit(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) <= 3:
            raise httpx.ReadTimeout("SECRET", request=request)
        return official(request)
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    verdict = result.data["verdicts"][0]
    assert verdict["levels"]["level1"] == "VERIFIED"
    assert verdict["source_lookup"]["deferred_retry"]
    assert verdict["source_lookup"]["recovery_status"] == "RECOVERED"
    assert verdict["source_lookup"]["http_attempts"] == 4
    assert not verdict["source_lookup"]["retryable"]
    assert not any(f.status == "UNVERIFIED" for f in result.findings)
    assert any(r.status == AdapterStatus.TIMEOUT for r in result.source_records)
    assert any(r.status == AdapterStatus.READY for r in result.source_records)
    assert "SECRET" not in str(result.data)


def test_persistent_outage_remains_honest_and_bounded(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("SECRET", request=request)
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    verdict = result.data["verdicts"][0]
    assert verdict["status"] == "UNVERIFIED"
    assert verdict["source_lookup"]["recovery_status"] == "RETRY_EXHAUSTED"
    assert len(calls) == 6
    assert not any(f.status == "NOT_FOUND" for f in result.findings)


@pytest.mark.parametrize("code", [401, 403, 404])
def test_nontransient_errors_do_not_retry(tmp_path, monkeypatch, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    assert len(calls) == 1
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
    assert not result.data["verdicts"][0]["source_lookup"]["deferred_retry"]


def test_empty_success_is_not_retried_as_a_timeout(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"PrecSearch": {"prec": []}})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    assert result.data["verdicts"][0]["status"] == "NOT_FOUND"
    assert not result.data["verdicts"][0]["source_lookup"]["deferred_retry"]
    # 정확 조회 1 + 사건번호 지정 조회 1(본문검색이 빗나가는 유형을 위한 대안) +
    # 선고일·법원 재검색 2. 대안은 순수 사건번호일 때만, 최초 조회가 실패했을 때만
    # 붙으므로 인용 한 건당 최대 1회 증가한다.
    assert len(calls) == 4


def test_timeout_in_fallback_search_is_not_reported_as_absent_case(tmp_path, monkeypatch):
    def handler(request):
        if request.url.params["query"] == "2099도99999":
            return httpx.Response(200, json={"PrecSearch": {"prec": []}})
        raise httpx.ReadTimeout("test")
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, max_attempts=1, retry_backoff=0):
        monkeypatch.setattr(transport, "_wait", lambda session, seconds: session.check_active())
        result = verifier(tmp_path).verify_citations(citations())
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
    assert not any(f.status == "NOT_FOUND" for f in result.findings)


def test_recovery_does_not_hide_subsequent_auth_error(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("test")
        return httpx.Response(403)
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, max_attempts=1, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    verdict = result.data["verdicts"][0]
    assert verdict["status"] == "UNVERIFIED"
    assert verdict["source_lookup"]["recovery_status"] == "UNAVAILABLE"


def test_deferred_detail_lookup_reuses_successful_search(tmp_path, monkeypatch):
    searches, details = [], []
    def handler(request):
        if request.url.path.endswith("lawSearch.do"):
            searches.append(request)
            return httpx.Response(200, json={"PrecSearch": {"prec": [{
                "사건번호": "2099도99999", "법원명": "대법원", "선고일자": "20990115",
                "판례일련번호": "synthetic",
            }]}})
        details.append(request)
        if len(details) <= 3:
            raise httpx.ReadTimeout("test")
        return httpx.Response(200, json={"PrecService": {
            "사건번호": "2099도99999", "판례내용": "Synthetic full judgment for tests only.",
        }})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0):
        result = verifier(tmp_path).verify_citations(citations())
    verdict = result.data["verdicts"][0]
    assert len(searches) == 1 and len(details) == 4
    assert verdict["official_record"]["full_text"].startswith("Synthetic")
    assert verdict["source_lookup"]["cache_hits"] == 1
    assert verdict["source_lookup"]["recovery_status"] == "RECOVERED"
