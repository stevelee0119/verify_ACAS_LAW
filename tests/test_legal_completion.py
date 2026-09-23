"""Official-contract fixtures. No credentials, live law data, or network required."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from packages.common.enums import AdapterStatus, CitationType, VerificationStatus
from packages.common.schemas import Citation
from packages.legal_engine import LegalVerifier, extract_from_text
from packages.legal_engine.source_review import case_applicability_review
from packages.source_adapters.base import response_hash
from packages.source_adapters.law_go_kr import LawGoKrAdapter, _normalize_law_payload
from packages.source_adapters.legal_history import legal_date, parse_law_body, select_provision, select_version
from packages.source_adapters.local_mirror import LocalLegalMirror


def history_row(mst="100", effective="20190101", promulgated="20180601", **extra):
    return {"법령명한글": "검증법", "법령ID": "000123", "법령일련번호": mst,
            "공포일자": promulgated, "시행일자": effective, "공포번호": "101",
            "제개정구분명": "일부개정", **extra}


def law_body(mst="100", effective="20190101", promulgated="20180601"):
    return {"법령": {
        "기본정보": {"법령ID": "000123", "법령일련번호": mst, "법령명_한글": "검증법",
                 "시행일자": effective, "공포일자": promulgated, "공포번호": "101"},
        "조문": {"조문단위": [
            {"조문번호": "10", "조문가지번호": "2", "조문여부": "조문",
             "조문시행일자": effective, "조문내용": "제10조의2(검토) 본문",
             "항": [
                 {"항번호": "①", "항내용": "첫 번째 항의 본문이다.",
                  "호": [{"호번호": "1.", "호내용": "첫 번째 호의 본문이다.",
                           "목": [{"목번호": "가.", "목내용": "원문에서 정확히 확인하는 첫 번째 조건이다."},
                                  {"목번호": "나.", "목내용": "전혀 다른 두 번째 조건의 문장이다."}]}]},
                 {"항번호": "②", "항내용": "두 번째 항에만 있는 독립 문언이다.",
                  "호": [{"호번호": "1.", "호내용": "동일 번호이지만 다른 항에 속한 호이다."}]},
             ]},
            {"조문번호": "11", "조문여부": "조문", "조문시행일자": effective,
             "조문내용": "제11조(삭제) 삭제"},
        ]},
        "부칙": {"부칙단위": {"부칙공포일자": promulgated, "부칙공포번호": "101",
                         "부칙내용": ["제1조(시행일) 이 법은 2019년 1월 1일부터 시행한다."]}},
    }}


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    law = LawGoKrAdapter(mirror=LocalLegalMirror(tmp_path / "empty"))
    monkeypatch.setattr(law, "status", lambda: AdapterStatus.READY)
    monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_SECRET_OC"))
    return law


def install_law(monkeypatch, adapter, rows=None, body=None):
    rows = rows if rows is not None else [history_row(), history_row("200", "20220101", "20210601")]
    calls = []

    def request(url, *, params):
        calls.append((url, deepcopy(params)))
        assert params["target"] == "eflaw"
        if "MST" in params:
            row = next(r for r in rows if r["법령일련번호"] == params["MST"]
                       and r["시행일자"] == params["efYd"])
            payload = body if body is not None else law_body(row["법령일련번호"], row["시행일자"], row["공포일자"])
        else:
            payload = {"LawSearch": {"totalCnt": len(rows), "page": 1, "law": rows}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(adapter, "_http_get", request)
    return calls


def statute(**values):
    return Citation.create(CitationType.STATUTE, values.pop("raw_text", "검증법 제10조의2 제1항 제1호 가목"),
                           law_name="검증법", article="10의2", paragraph="1", item="1", **values)


def verifier(adapter):
    return LegalVerifier(SimpleNamespace(law=adapter))


def test_exact_effective_boundary_and_current_version_separated(adapter, monkeypatch):
    calls = install_law(monkeypatch, adapter)
    old = adapter.resolve_statute("검증법", as_of="2021-12-31", current_date="2026-09-18")
    new = adapter.resolve_statute("검증법", as_of="2022-01-01", current_date="2026-09-18")
    assert old.ok and new.ok
    assert old.records[0]["version_id"] == "100"
    assert old.records[0]["effective_until"] == "2022-01-01"  # exclusive
    assert old.records[0]["current_version"]["version_id"] == "200"
    assert new.records[0]["version_id"] == "200"
    details = [p for _, p in calls if "MST" in p]
    assert [(p["MST"], p["efYd"]) for p in details] == [("100", "20190101"), ("200", "20220101")]
    assert all("ID" not in p and "ancYd" not in p and "date" not in p for _, p in calls)
    assert calls[1][1]["LID"] == "123" and calls[1][1]["nw"] == "1,2,3"


def test_same_mst_with_two_effective_dates_is_not_collapsed(adapter, monkeypatch):
    install_law(monkeypatch, adapter, [
        history_row("100", "20190101"), history_row("100", "20190701")])
    result = adapter.resolve_statute("검증법", as_of="2019-08-01")
    assert result.ok
    assert result.records[0]["effective_from"] == "2019-07-01"


@pytest.mark.parametrize("change", [
    {"시행일자": ""}, {"공포일자": ""}, {"시행일자": "20220230"},
    {"법령일련번호": ""}, {"법령ID": ""},
])
def test_missing_history_dates_or_ids_fail_closed(adapter, monkeypatch, change):
    install_law(monkeypatch, adapter, [history_row(**change)])
    response = adapter.resolve_statute("검증법", as_of="2020-01-01")
    assert response.status == AdapterStatus.ERROR and not response.records
    assert response.source_records


@pytest.mark.parametrize("rows", [
    [history_row(), history_row("101")],
    [history_row(), history_row("200", 법령ID="999")],
    [history_row(제개정구분명="폐지")],
    [history_row(promulgated="20250101")],
])
def test_ambiguous_identity_boundary_repeal_or_retroactivity(adapter, monkeypatch, rows):
    install_law(monkeypatch, adapter, rows)
    response = adapter.resolve_statute("검증법", as_of="2020-01-01")
    assert not response.ok and not response.records


@pytest.mark.parametrize("when", ["", "2026-02-30", "next year", "2099-01-01"])
def test_invalid_or_future_date_never_becomes_current(adapter, monkeypatch, when):
    calls = install_law(monkeypatch, adapter)
    response = adapter.resolve_statute("검증법", as_of=when)
    assert not response.ok and calls == []


def test_paginated_history_all_pages_are_snapshotted(adapter, monkeypatch):
    rows = [history_row(), history_row("200", "20220101", "20210601")]
    calls = []
    def request(url, *, params):
        calls.append(params)
        page = params["page"]
        return httpx.Response(200, json={"LawSearch": {"totalCnt": 2, "page": page, "law": rows[page - 1]}})
    monkeypatch.setattr(adapter, "_http_get", request)
    result = adapter.search_law_history("검증법")
    assert result.ok and result.complete and len(result.records) == 2
    assert len(result.source_records) == 4
    assert [p["page"] for p in calls] == [1, 2, 1, 2]


@pytest.mark.parametrize("failure", ["repeat", "count_changed", "missing_count", "empty", "429", "malformed"])
def test_incomplete_history_keeps_successful_snapshots(adapter, monkeypatch, failure):
    def request(url, *, params):
        if params["page"] == 1:
            return httpx.Response(200, json={"LawSearch": {"totalCnt": 2, "page": 1, "law": history_row()}})
        if failure == "429":
            return httpx.Response(429, json={"error": "rate limited"})
        if failure == "malformed":
            return httpx.Response(200, content=b"<html>unavailable</html>")
        container = {"totalCnt": 2, "page": 2, "law": history_row()}
        if failure == "count_changed":
            container["totalCnt"] = 3
        if failure == "missing_count":
            del container["totalCnt"]
        if failure == "empty":
            container["law"] = []
        return httpx.Response(200, json={"LawSearch": container})
    monkeypatch.setattr(adapter, "_http_get", request)
    result = adapter.resolve_statute("검증법", as_of="2020-01-01")
    assert not result.ok and not result.records and len(result.source_records) == 2
    assert result.source_records[0].payload["snapshot"]["canonical_json"]


def test_detail_identity_mismatch_is_not_bound(adapter, monkeypatch):
    body = law_body()
    body["법령"]["기본정보"]["법령ID"] = "999"
    install_law(monkeypatch, adapter, body=body)
    result = adapter.resolve_statute("검증법", as_of="2020-01-01")
    assert not result.ok and not result.records
    assert len(result.source_records) == 3


def test_canonical_sanitized_snapshot_is_reproducible_and_detached(adapter, monkeypatch):
    rows = [history_row(OC="TEST_SECRET_OC", 법령상세링크="/x?OC=TEST_SECRET_OC&target=eflaw")]
    install_law(monkeypatch, adapter, rows)
    result = adapter.resolve_statute("검증법", as_of="2020-01-01")
    assert result.ok
    for source in result.source_records:
        snapshot = source.payload["snapshot"]
        assert snapshot["sha256"] == hashlib.sha256(snapshot["canonical_json"].encode("utf-8")).hexdigest()
        assert json.loads(snapshot["canonical_json"]) == source.payload["response"]
        assert source.response_hash == response_hash(source.payload)
        assert len(snapshot["response_body_sha256"]) == 64
        assert "TEST_SECRET_OC" not in json.dumps(source.to_dict())
    before = result.source_records[-1].payload["snapshot"]["canonical_json"]
    result.records[0]["provisions"][0]["text"] = "consumer mutation"
    assert result.source_records[-1].payload["snapshot"]["canonical_json"] == before


def test_exact_article_paragraph_item_subitem_text(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_statute(statute(), as_of="2020-01-01", incident_date="2019-08-01")
    assert result.status == VerificationStatus.PARTIALLY_VERIFIED
    assert result.levels["temporal"] == "VERIFIED", (result.review, result.notes)
    assert result.review["provision"]["path"] == {"article": "10의2", "paragraph": "1", "item": "1", "subitem": "가"}
    assert result.review["provision"]["text"] == "원문에서 정확히 확인하는 첫 번째 조건이다."
    assert "두 번째" not in result.review["provision"]["text"]
    assert result.review["dates"]["incident_date"] == "2019-08-01"
    assert result.review["dates"]["reference_date"] == "2020-01-01"
    assert result.levels["applicability"] == "REVIEW_NEEDED"


def test_different_issue_dates_produce_distinct_versions(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    first = verifier(adapter).verify_citations([statute()], case_date="2020-01-01", incident_date="2018-01-01")
    second = verifier(adapter).verify_citations([statute()], case_date="2023-01-01", incident_date="2018-01-01")
    assert first.data["verdicts"][0]["review"]["version"]["version_id"] == "100"
    assert second.data["verdicts"][0]["review"]["version"]["version_id"] == "200"
    assert len(first.source_records) == len(second.source_records) == 3


def test_missing_reference_date_keeps_temporal_unverified(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_statute(statute(), incident_date="2020-01-01")
    assert result.levels["temporal"] == "UNVERIFIED"
    assert result.review["dates"]["reference_date"] is None
    assert result.review["version"]["date_basis"] == "CURRENT_ONLY"
    assert result.status != VerificationStatus.VERIFIED


@pytest.mark.parametrize("case", ["missing_article_date", "future_article_date", "partial", "enforcement_note", "transitional", "missing_supplement"])
def test_article_enforcement_and_transition_uncertainty(adapter, monkeypatch, case):
    body = law_body()
    article = body["법령"]["조문"]["조문단위"][0]
    if case == "missing_article_date":
        del article["조문시행일자"]
    if case == "future_article_date":
        article["조문시행일자"] = "20250101"
    if case == "partial":
        body["법령"]["부칙"]["부칙단위"]["부칙내용"] = "다만, 제10조의2 제1항은 2025년부터 시행한다."
    if case == "enforcement_note":
        body["법령"]["기본정보"]["조문시행일자문자열"] = "특정 조문의 시행 시점은 별도 확인이 필요함"
    if case == "transitional":
        body["법령"]["부칙"]["부칙단위"]["부칙내용"] = "제2조(경과조치) 종전의 규정에 따른다."
    if case == "missing_supplement":
        del body["법령"]["부칙"]
    install_law(monkeypatch, adapter, body=body)
    result = verifier(adapter).verify_statute(statute(), as_of="2020-01-01")
    assert result.levels["temporal"] == "UNVERIFIED"
    assert result.status != VerificationStatus.VERIFIED
    assert result.review["advisory_only"]
    if case == "transitional":
        assert result.review["transitional_review_needed"]


def test_missing_subitem_does_not_fall_back_to_whole_article(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_statute(statute(raw_text="검증법 제10조의2 제1항 제1호 다목"), as_of="2020-01-01")
    assert result.status == VerificationStatus.UNVERIFIED
    assert result.levels["provision"] == "UNVERIFIED"


def test_quote_compared_only_with_selected_subitem(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_statute(
        statute(quoted_text="두 번째 항에만 있는 독립 문언이다."), as_of="2020-01-01")
    assert result.status == VerificationStatus.CONTRADICTED
    assert result.levels["content"] == "CONTRADICTED"
    assert result.findings[0].source_record_ids


def test_missing_date_prevents_current_quote_false_contradiction(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_statute(statute(quoted_text="존재하지 않는 오래된 문언을 여기 인용하였다."))
    assert result.status != VerificationStatus.CONTRADICTED
    assert result.levels["content"] == "UNVERIFIED"


def test_headings_are_not_articles_and_duplicates_remain_ambiguous():
    body = law_body()
    body["법령"]["조문"]["조문단위"].append({"조문번호": "99", "조문여부": "전문", "조문내용": "장 제목"})
    selected = _normalize_law_payload({"LawSearch": {"law": history_row()}})[0]
    law = parse_law_body(body, selected)
    assert "99" not in law["articles"]
    law["provisions"].append(deepcopy(law["provisions"][0]))
    assert select_provision(law, "10의2")["status"] == "UNVERIFIED"


def test_implicit_unnumbered_paragraph_item_is_supported():
    body = law_body()
    first = body["법령"]["조문"]["조문단위"][0]
    first["항"] = {"호": [{"호번호": "1.", "호내용": "번호 없는 항 아래 첫 호의 본문"}]}
    selected = _normalize_law_payload({"LawSearch": {"law": history_row()}})[0]
    law = parse_law_body(body, selected)
    assert select_provision(law, "10의2", item="1")["status"] == "VERIFIED"
    assert select_provision(law, "10의2", paragraph="1", item="1")["status"] == "UNVERIFIED"


def test_deleted_provision_is_not_treated_as_operative_text(adapter, monkeypatch):
    install_law(monkeypatch, adapter)
    citation = Citation.create(CitationType.STATUTE, "검증법 제11조", law_name="검증법", article="11")
    result = verifier(adapter).verify_statute(citation, as_of="2020-01-01")
    assert result.levels["provision"] == "DELETED"
    assert result.status == VerificationStatus.UNVERIFIED
    assert result.review["provision"]["text"] == "제11조(삭제) 삭제"


@pytest.mark.parametrize("text,kind,number", [
    ("법제처 법령해석례 20-0001", CitationType.INTERPRETATION, "20-0001"),
    ("법제처 2020. 2. 3. 회신 20-0001 해석례", CitationType.INTERPRETATION, "20-0001"),
    ("중앙행정심판위원회 2020. 2. 3. 2020-12345 재결", CitationType.ADMIN_APPEAL, "2020-12345"),
])
def test_decision_citations_extracted_with_correct_kind(text, kind, number):
    found = [c for c in extract_from_text(text) if c.type == kind]
    assert len(found) == 1 and found[0].case_number == number


def test_extractor_preserves_subitem_raw_locator_and_quote():
    citation = next(c for c in extract_from_text(
        '검증법 제10조의2 제1항 제1호 가목 "원문에서 정확히 확인하는 첫 번째 조건이다."') if c.type == CitationType.STATUTE)
    assert citation.raw_text.endswith("가목")
    assert citation.quoted_text == "원문에서 정확히 확인하는 첫 번째 조건이다."


def decision_payloads(target):
    if target == "expc":
        listed = {"법령해석례일련번호": "300", "안건번호": "20-0001", "안건명": "시험 해석례",
                  "회신기관명": "법제처", "회신일자": "20200203"}
        detail = {"법령해석례일련번호": "300", "안건번호": "20-0001", "안건명": "시험 해석례",
                  "해석기관명": "법제처", "해석일자": "20200203",
                  "질의요지": "가상의 질의 요지이다.", "회답": "법률의 조건을 검토해야 한다.", "이유": "가상의 판단 이유이다."}
        text = "법제처 2020. 2. 3. 회신 20-0001 해석례"
    else:
        listed = {"행정심판재결례일련번호": "400", "사건번호": "2020-12345", "사건명": "시험 재결례",
                  "재결청": "중앙행정심판위원회", "의결일자": "20200203"}
        detail = {"행정심판례일련번호": "400", "사건번호": "2020-12345", "사건명": "시험 재결례",
                  "재결청": "중앙행정심판위원회", "의결일자": "20200203", "처분일자": "20200101",
                  "주문": "청구를 기각한다.", "청구취지": "처분의 취소를 구한다.", "이유": "가상의 판단 이유이다."}
        text = "중앙행정심판위원회 2020. 2. 3. 2020-12345 재결"
    return listed, detail, text


@pytest.mark.parametrize("target", ["expc", "decc"])
def test_official_decision_list_detail_routing(adapter, monkeypatch, target):
    listed, detail, text = decision_payloads(target)
    calls = []
    def request(url, *, params):
        calls.append(params)
        assert params["target"] == target
        payload = {target.title() + "Service": detail} if "ID" in params else {
            target.title() + "Search": {"totalCnt": 1, "page": 1, target: listed}}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(adapter, "_http_get", request)
    result = verifier(adapter).verify_citations(extract_from_text(text))
    verdict = result.data["verdicts"][0]
    assert verdict["status"] == "PARTIALLY_VERIFIED"
    assert verdict["levels"]["full_text"] == "VERIFIED"
    assert verdict["levels"]["metadata"] == "VERIFIED"
    assert len(result.source_records) == 2
    assert calls[-1]["ID"] == ("300" if target == "expc" else "400")
    if target == "expc":
        assert calls[0]["itmno"] == "200001" and "query" not in calls[0]


@pytest.mark.parametrize("target", ["expc", "decc"])
@pytest.mark.parametrize("failure", ["wrong_id", "wrong_number", "missing_body", "missing_date", "duplicate"])
def test_decision_ambiguity_and_incomplete_fulltext_fail_closed(adapter, monkeypatch, target, failure):
    listed, detail, text = decision_payloads(target)
    if failure == "wrong_id":
        detail["법령해석례일련번호" if target == "expc" else "행정심판례일련번호"] = "999"
    if failure == "wrong_number":
        detail["안건번호" if target == "expc" else "사건번호"] = "wrong"
    if failure == "missing_body":
        del detail["이유"]
    if failure == "missing_date":
        del detail["해석일자" if target == "expc" else "의결일자"]
    def request(url, *, params):
        payload = {target.title() + "Service": detail} if "ID" in params else {
            target.title() + "Search": {"totalCnt": 2 if failure == "duplicate" else 1, "page": 1,
                                      target: [listed, dict(listed)] if failure == "duplicate" else listed}}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(adapter, "_http_get", request)
    result = verifier(adapter).verify_citations(extract_from_text(text))
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
    assert result.unverified_items


def test_transport_exception_does_not_leak_oc(adapter, monkeypatch):
    def request(*args, **kwargs):
        raise httpx.ReadTimeout("URL ?OC=TEST_SECRET_OC")
    monkeypatch.setattr(adapter, "_http_get", request)
    result = adapter.search_interpretation("20-0001")
    assert result.status == AdapterStatus.TIMEOUT
    assert "TEST_SECRET_OC" not in result.message


def test_other_ministry_interpretation_is_not_bound_to_expc(adapter, monkeypatch):
    calls = install_law(monkeypatch, adapter)
    result = verifier(adapter).verify_citations(extract_from_text("법무부 법령해석례 20-0001"))
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
    assert not calls


def test_incomplete_decision_citation_is_visible_as_unverified(adapter):
    result = verifier(adapter).verify_citations(extract_from_text("법제처 법령해석례 참조"))
    assert result.data["citation_count"] == 1
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
    assert result.unverified_items


def test_unknown_target_is_not_searched_as_precedent(adapter, monkeypatch):
    calls = install_law(monkeypatch, adapter)
    response = adapter.search("test", target="unsupported")
    assert response.status == AdapterStatus.ERROR and not calls


def test_mirror_missing_dates_and_overlap_do_not_verify(registry):
    mirror = registry.law.mirror
    mirror._laws = [{"law_name": "검증법", "article": "10의2", "articles": ["10의2"]}]
    result = LegalVerifier(registry).verify_statute(statute(), as_of="2020-01-01")
    assert result.levels["temporal"] == "UNVERIFIED"
    mirror._laws = [{**mirror._laws[0], "effective_from": "2019-01-01", "effective_to": "2022-12-31"}] * 2
    result = LegalVerifier(registry).verify_statute(statute(), as_of="2020-01-01")
    assert result.levels["temporal"] == "UNVERIFIED"


def test_case_applicability_requires_source_anchors_and_never_concludes():
    citation = Citation.create(CitationType.CASE, "판결 인용", case_number="2020다12345", context="문서 주장")
    review = case_applicability_review(citation, {"full_text": "계약 사실. 단서 조건. 결론."},
        source_record_ids=["SRC_1"], extracted={
            "facts": [{"excerpt": "계약 사실."}], "conditions": [{"excerpt": "단서 조건."}],
            "rules": [{"excerpt": "공식 원문에 없는 규칙"}],
            "subsequent_treatment": [{"excerpt": "폐기된 판례라고 단정"}]})
    assert review["sections"]["facts"][0]["span"] == [0, 6]
    assert review["sections"]["rules"] == [] and len(review["rejected_excerpts"]) == 2
    assert review["applies_to_case"] is None and review["precedential_effect"] == "NOT_DETERMINED"
    assert review["advisory_only"] and review["status"] == "REVIEW_NEEDED"


@pytest.mark.parametrize("raw", [None, "", "20260230", "2026-13-01", "on 2026-01-01"])
def test_strict_legal_dates(raw):
    assert legal_date(raw) is None


def test_pipeline_keeps_each_issue_date_and_full_snapshots(adapter, monkeypatch, registry):
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext, VerificationPipeline, VerificationRunResult
    from packages.common.enums import JobState
    from packages.report_engine.exporters import to_json

    install_law(monkeypatch, adapter)
    registry.legal[0] = adapter
    pipeline = VerificationPipeline(registry=registry)
    document = DocumentResult("D", "sample")
    context = ProjectContext("P", case_date="2020-01-01",
                             issue_dates={"contract": "2020-01-01", "disposition": "2023-01-01"})
    pipeline._legal_reviews(document, [statute()], context)
    reviews = document.engine_data["legal_reviews"]
    assert [r["review_id"] for r in reviews] == ["incident", "issue:contract", "issue:disposition"]
    assert [r["verdicts"][0]["review"]["version"]["version_id"] for r in reviews] == ["100", "100", "200"]
    assert all(r["incident_date"] == "2020-01-01" for r in reviews)
    assert all(r["source_record_ids"] for r in reviews)
    assert len(document.source_records) == 9
    assert {u["review_id"] for u in document.unverified_items} == {r["review_id"] for r in reviews}
    run = VerificationRunResult("R", "P", JobState.PARTIAL_COMPLETED, "test", documents=[document])
    exported = json.loads(to_json(run))
    persisted = exported["documents"][0]["source_records"]
    assert len(persisted) == 9
    for record in persisted:
        snapshot = record["payload"]["snapshot"]
        assert hashlib.sha256(snapshot["canonical_json"].encode("utf-8")).hexdigest() == snapshot["sha256"]
        assert response_hash(record["payload"]) == record["response_hash"]


def test_pipeline_invalid_issue_date_is_not_replaced_by_incident(adapter, monkeypatch, registry):
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext, VerificationPipeline
    install_law(monkeypatch, adapter)
    registry.legal[0] = adapter
    pipeline = VerificationPipeline(registry=registry)
    document = DocumentResult("D", "sample")
    pipeline._legal_reviews(document, [statute()],
                            ProjectContext("P", case_date="2020-01-01", issue_dates={"bad": ""}))
    issue = document.engine_data["legal_reviews"][1]
    assert issue["reference_date"] == ""
    assert issue["verdicts"][0]["status"] == "UNVERIFIED"
    assert issue["verdicts"][0]["review"]["dates"]["reference_date"] == ""
    assert not issue["source_record_ids"]


def test_pipeline_case_review_is_not_repeated_for_each_statute_date(registry):
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext, VerificationPipeline
    pipeline = VerificationPipeline(registry=registry)
    document = DocumentResult("D", "sample")
    citations = extract_from_text("대법원 2099. 1. 15. 선고 2099도99999 판결")
    pipeline._legal_reviews(document, citations, ProjectContext(
        "P", issue_dates={"first": "2020-01-01", "second": "2023-01-01"}))
    assert len(document.engine_data["case_applicability_reviews"]) == 1
    review = document.engine_data["case_applicability_reviews"][0]
    assert review["status"] == "REVIEW_NEEDED" and review["applies_to_case"] is None
    assert review["source_record_ids"]
    assert not document.engine_data["legal_reviews"][1]["citation_ids"]


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, text="<html>오류</html>", headers={"content-type": "text/html"}), "JSON이 아님(content-type text/html"),
    (httpx.Response(200, json={"Law": "사용자 정보 검증에 실패"}), "형식이 예상과 다름"),
    (httpx.Response(500, text="x"), "HTTP 500"),
])
def test_case_full_text_failures_say_why(adapter, monkeypatch, response, expected):
    """전문 조회가 실패하면 의미·적용 검토(세 모델 교차검증)가 건너뛰어진다.

    배포 점검에서 사건번호 조회는 되는데 전문 조회만 매번 '연결 또는 응답 처리
    실패' 한 문장으로 끝나, 무엇이 문제인지 알 수 없었다.
    """
    monkeypatch.setattr(adapter, "_http_get", lambda url, *, params: response)
    result = adapter.fetch_case({"case_number": "2011모1839", "source_id": "1"})
    assert result.status != "READY" and expected in result.message
    assert "OC" not in result.message


def test_case_full_text_without_wrapper_is_still_read(adapter, monkeypatch):
    body = {"사건번호": "2011모1839", "판례내용": "재항고를 기각한다."}
    monkeypatch.setattr(adapter, "_http_get", lambda url, *, params: httpx.Response(200, json=body))
    result = adapter.fetch_case({"case_number": "2011모1839", "source_id": "1"})
    assert result.records and "재항고를 기각한다" in result.records[0].get("full_text", "")
