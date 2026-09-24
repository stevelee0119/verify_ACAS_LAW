"""v3 추가지시 G1·J1·J5: 헌법재판소 결정 조회.

현상: 실존 헌재 결정이 NOT_FOUND(B)로 판정됐다. 원인: (1) '헌재' 약칭이 법원명으로 정규화되지 않아 판례 DB(prec)로
조회, (2) 본문검색(search=2)을 먼저 해 정확한 사건이 첫 페이지에 없음, (3) 헌재 조회 실패를 NOT_FOUND로 처리.
응답 모양은 공식 원문 수집(CI)에서 확인한 DetcSearch 형식이다. 사건번호는 널리 알려진 실존 결정이다.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from packages.common.enums import AdapterStatus, CitationType
from packages.legal_engine.citation_extractor import extract_from_text
from packages.source_adapters.law_go_kr import LawGoKrAdapter
from packages.source_adapters.local_mirror import LocalLegalMirror

REAL = {"2004헌마554": "2004.10.21", "2016헌나1": "2017.03.10", "2004헌나1": "2004.05.14",
        "2017헌바127": "2019.04.11", "2008헌가23": "2010.02.25", "2011헌바379": "2018.06.28",
        "2009헌바17": "2015.02.26", "2013헌다1": "2014.12.19", "2015헌마236": "2016.07.28",
        "96헌가2": "1996.02.16", "89헌마82": "1990.09.10"}


def detc(rows, total=None):
    return {"DetcSearch": {"totalCnt": str(total if total is not None else len(rows)), "page": "1",
                           "detc": [{"사건번호": n, "종국일자": d, "사건명": "사건", "헌재결정례일련번호": str(i)}
                                    for i, (n, d) in enumerate(rows)]}}


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    a = LawGoKrAdapter(mirror=LocalLegalMirror(tmp_path / "empty"))
    monkeypatch.setattr(a, "status", lambda: AdapterStatus.READY)
    monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_OC"))
    return a


def serve(monkeypatch, adapter, answer):
    calls = []

    def get(url, *, params):
        calls.append(dict(params))
        return httpx.Response(200, json=answer(params), request=httpx.Request("GET", url))
    monkeypatch.setattr(adapter, "_http_get", get)
    return calls


def test_constitutional_court_abbreviation_is_normalized():
    [c] = extract_from_text("(헌재 1990. 9. 10. 89헌마82)")
    assert c.court == "헌법재판소"


@pytest.mark.parametrize("number", sorted(REAL))
def test_regression_real_decisions_are_found_by_case_number_first(adapter, monkeypatch, number):
    def answer(params):
        if params.get("nb") == number:  # 사건번호 지정 조회는 정확한 결정(과 번호가 비슷한 결정)을 돌려준다
            return detc([(number + "0", "2012.05.31"), (number, REAL[number])])
        return detc([("2008헌마456", "2008.09.25")], total=500)
    calls = serve(monkeypatch, adapter, answer)
    response = adapter.search_case(number, court="헌법재판소")
    assert response.records and response.records[0]["case_number"] == number
    assert calls[0]["target"] == "detc" and "nb" in calls[0] and len(calls) == 1


def test_code_decides_the_database_even_when_the_court_label_is_wrong(adapter, monkeypatch):
    calls = serve(monkeypatch, adapter, lambda p: detc([("2005헌바28", "2007.05.31")]))
    adapter.search_case("2005헌바28", court="대법원")
    assert calls[0]["target"] == "detc"


def test_exact_decision_on_a_later_page_is_found(adapter, monkeypatch):
    def answer(params):
        if "nb" in params:
            return detc([])
        page = int(params.get("page", 1))
        rows = [(f"2014헌바{i}", "2015.01.01") for i in range(100 * (page - 1), 100 * page)]
        if page == 2:
            rows[37] = ("2014헌바148", "2016.02.25")
        return detc(rows, total=250)
    serve(monkeypatch, adapter, answer)
    response = adapter.search_case("2014헌바148", court="헌법재판소")
    assert response.records and response.records[0]["case_number"] == "2014헌바148"


def test_malformed_response_is_an_error_not_an_empty_result(adapter, monkeypatch):
    serve(monkeypatch, adapter, lambda p: {"unexpected": {}})
    response = adapter.search_case("2017헌바127", court="헌법재판소")
    assert response.status == AdapterStatus.ERROR and "응답 형식" in response.message


def test_unconfirmed_constitutional_decision_is_unverified_with_lookup_evidence(adapter, monkeypatch):
    from packages.legal_engine.verifier import LegalVerifier
    serve(monkeypatch, adapter, lambda p: detc([("2008헌마456", "2008.09.25")], total=1))
    [c] = [c for c in extract_from_text("헌법재판소 2016. 2. 25. 2014헌바148 결정")
           if c.type in (CitationType.CASE, CitationType.CONSTITUTIONAL)]
    result = LegalVerifier(SimpleNamespace(law=adapter)).verify_citations([c], current_date="2026-09-24")
    [verdict] = result.data["verdicts"]
    assert verdict["status"] == "UNVERIFIED"
    [finding] = result.findings
    assert str(finding.status) == "UNVERIFIED" and "nb" in finding.detail and "detc" in finding.detail
