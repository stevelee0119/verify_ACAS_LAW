"""Offline regression cases. Synthetic inputs are not real-world quality evidence."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.claim_engine import (
    AllocatedPayment, EvidenceItem, InterestAssumptions, RatePeriod, analyze_timeline,
    calculate_segmented_interest, claim_contradictions, cross_document_contradictions,
    extract_claims, extract_events, extract_evidence_references, match_evidence_references,
    resolve_entities, search_claim_candidates, structure_claim_text,
)
from packages.claim_engine.calculation import parse_amounts
from packages.common.enums import ClaimType, EntityType, VerificationStatus
from packages.common.schemas import Block, Claim, Entity, Event, NormalizedDocument, Page
from packages.evaluation import LabelRecord, PredictionRecord, evaluate_quality, load_jsonl, validate_case_splits

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "analysis_completion"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("External network access is forbidden in these tests")
    monkeypatch.setattr(socket, "create_connection", fail)


def document(text, document_id="doc"):
    return NormalizedDocument(document_id, "synthetic.txt", "text/plain", "synthetic-hash",
                              pages=[Page(2, blocks=[Block("b1", text, 2)])])


def assumptions(**kwargs):
    values = dict(day_count_convention="ACT/365F", include_start=True, include_end=False,
                  rounding="ROUND_HALF_UP", rounding_quantum=D("0.01"), rounding_stage="FINAL",
                  payment_timing="START_OF_DAY", allocation_policy="EXPLICIT", principal_source="synthetic principal",
                  period_source="synthetic dates", convention_source="synthetic confirmed arithmetic choices",
                  confirmed_by="synthetic-reviewer", user_confirmed=True)
    return InterestAssumptions(**{**values, **kwargs})


def calculate(*, principal="36500", start=date(2024, 1, 1), end=date(2024, 1, 11),
              rate="10", rates=None, payments=None, **settings):
    return calculate_segmented_interest(
        principal=D(principal), start_date=start, end_date=end,
        rate_periods=rates if rates is not None else [RatePeriod(start, max(end, date(2024, 2, 1)), D(rate), "synthetic rate")],
        payments=payments or [], assumptions=assumptions(**settings))


def test_old_schema_constructors_and_serialization():
    claim = Claim.create(ClaimType.FACT, "legacy")
    assert claim.project_id is None and claim.stance == "UNSPECIFIED"
    assert claim.to_dict()["evidence_references"] == []
    assert Event.create(None, "legacy").to_dict()["date"] is None
    assert Entity.create(EntityType.PERSON, "legacy").explicit_identifiers == {}


def test_structured_claim_sources_ids_and_exhibit_branches():
    text = "원고는 피고에게 계약번호 T-1 지급번호 PAY-1 speaker_id=S target_id=T 2024. 1. 3. 1억 5천만 원을 지급하였다 (갑 제12호증의 2, 3~5쪽)."
    claims = extract_claims(document(text), project_id="P", source_run_id="run1")
    assert len(claims) == 1
    claim = claims[0]
    assert (claim.transaction_id, claim.event_identity, claim.speaker_id, claim.target_id) == ("T-1", "PAY-1", "S", "T")
    assert claim.speaker_text == "원고" and claim.target_text == "피고"
    assert claim.amount == "150000000" and claim.asserted_date == "2024-01-03"
    assert claim.status == VerificationStatus.UNVERIFIED and claim.extraction_confidence is None
    ref = claim.evidence_references[0]
    assert ref["key"] == "갑:12:2" and ref["branches"] == [2]
    assert (ref["page_start"], ref["page_end"], ref["page"]) == (3, 5, 2)
    assert text[slice(*ref["span"])] == ref["raw_text"]
    assert ref["source_run_id"] == "run1" and claim.source_document_sha256 == "synthetic-hash"
    event = extract_events(document(text), project_id="P", source_run_id="run1")[0]
    assert event.transaction_id == "T-1" and event.evidence_references == claim.evidence_references


@pytest.mark.parametrize("text,flag,stance", [
    ("원고는 대금을 지급하지 않았다.", "negated", "DENIED"),
    ("피고는 대금을 지급했다고 주장하였다.", "hearsay", "REPORTED"),
    ('원고는 "지급하지 않았다"라는 주장을 인용하였다.', "quoted", "QUOTED"),
    ("만약 계약이 유효하다면 대금을 지급한다.", "conditional", "CONDITIONAL"),
    ("예비적으로 대금의 반환을 청구한다.", "alternative", "ALTERNATIVE"),
])
def test_stance_does_not_become_fact(text, flag, stance):
    result = structure_claim_text(text)
    assert result[flag] and result["stance"] == stance


def test_ambiguous_multiple_events_are_not_collapsed():
    fields = structure_claim_text("계약번호 A 계약번호 B 2024. 1. 1. 지급하고 2024. 2. 1. 지급했다.")
    assert fields["transaction_id"] is None and fields["asserted_date"] is None
    assert fields["stance"] == "AMBIGUOUS"


def test_reference_matching_only_locates_same_project_exact_branch_and_pages():
    claim = extract_claims(document("갑 제1호증의 2, 3~5쪽 및 별첨 2, 1쪽을 제출하였다."), project_id="P", source_run_id="citing-run")[0]
    items = [EvidenceItem("P", "갑:1:2", "evidence", "source-run", "hash", (3, 4, 5)),
             EvidenceItem("Q", "별첨:2", "foreign", "foreign-run", "hash2", (1,))]
    matches = match_evidence_references([claim], items, project_id="P")
    assert [m.status for m in matches] == ["REFERENCE_LOCATED", "REFERENCE_MISSING"]
    assert matches[0].candidates[0].source_run_id == "source-run"
    assert all(m.relationship == "UNASSESSED" and m.advisory_only for m in matches)
    assert claim.status == VerificationStatus.UNVERIFIED and claim.evidence == []
    partial = replace(items[0], available_pages=(3, 5))
    assert match_evidence_references([claim], [partial], project_id="P")[0].status == "PAGE_NOT_AVAILABLE"
    assert match_evidence_references([claim], [replace(items[0], reference_key="갑:1")], project_id="P")[0].status == "REFERENCE_MISSING"
    assert match_evidence_references([claim], [items[0], replace(items[0], source_run_id="other")], project_id="P")[0].status == "AMBIGUOUS_REFERENCE"


def test_invalid_page_range_is_not_verified():
    assert extract_evidence_references("을 제3호증의 1의 2, 8~3쪽")[0]["parse_status"] == "AMBIGUOUS"


def test_entities_need_explicit_identity_and_same_project():
    first = Entity.create(EntityType.PERSON, "Kim", project_id="P", explicit_identifiers={"party_id": "1"})
    alias = Entity.create(EntityType.PERSON, "K. Kim", project_id="P", explicit_identifiers={"party_id": "1"})
    unrelated = Entity.create(EntityType.PERSON, "Kim", project_id="Q", explicit_identifiers={"party_id": "1"})
    result = resolve_entities([first, alias, unrelated])
    assert len(result) == 2 and first.name == "Kim" and first.aliases == []
    assert [e.entity_id for e in result] == [e.entity_id for e in resolve_entities([unrelated, alias, first])]
    assert len(resolve_entities([Entity.create(EntityType.PERSON, "Kim", project_id="P"),
                                 Entity.create(EntityType.PERSON, "Kim", project_id="P")])) == 2
    assert len(resolve_entities([replace(first, project_id=None), replace(alias, project_id=None)])) == 2
    with pytest.raises(ValueError, match="project"):
        resolve_entities([unrelated], project_id="P")


def test_explicit_aliases_and_conflicting_alias_groups():
    first = Entity.create(EntityType.COMPANY, "Acme Ltd", project_id="P", explicit_aliases=["Acme"])
    second = Entity.create(EntityType.COMPANY, "Acme", project_id="P")
    assert len(resolve_entities([first, second])) == 1
    assert len(resolve_entities([replace(first, explicit_aliases=[], aliases=["Acme"]), second])) == 2
    first.explicit_identifiers = {"registration": "1"}
    second.explicit_identifiers = {"registration": "2"}
    unresolved = resolve_entities([first, second])
    assert len(unresolved) == 2 and all(e.needs_user_confirmation for e in unresolved)


def test_search_is_lexical_and_project_scoped():
    own = Claim.create(ClaimType.FACT, "payment P-1 made", project_id="P", source_run_id="r")
    foreign = replace(own, claim_id="foreign", project_id="Q")
    candidates = search_claim_candidates(own.text, [foreign, own], project_id="P")
    assert len(candidates) == 1 and candidates[0].claim_id == own.claim_id
    assert candidates[0].score == 1 and "lexical" in candidates[0].method


def payment_event(doc, **changes):
    fields = dict(event_kind="PAYMENT", document_id=doc, project_id="P", transaction_id="T",
                  event_identity="PAY-1", speaker_id="payer", target_id="payee", amount="100", currency="KRW", amount_scope="PARTIAL")
    return Event.create(date(2024, 1, 1), "지급하였다", **{**fields, **changes})


def test_like_event_date_and_amount_conflicts_keep_source_locations():
    first = payment_event("a", source_run_id="run-a", source_document_sha256="hash-a", page=2)
    second = replace(payment_event("b", amount="200"), date=date(2024, 1, 2))
    result = cross_document_contradictions({"a": [first], "b": [second]})
    assert len(result) == 1 and result[0].advisory_only
    assert set(result[0].confidence_features["differences"]) == {"date", "amount"}
    assert result[0].confidence_features["sources"][0]["source_run_id"] == "run-a"
    assert result[0].status == VerificationStatus.UNVERIFIED


@pytest.mark.parametrize("changes", [
    {"project_id": "Q"}, {"transaction_id": "OTHER"}, {"event_identity": "PAY-2"},
    {"speaker_id": "other-payer"}, {"target_id": "other-payee"}, {"negated": True},
    {"hearsay": True}, {"quoted": True}, {"conditional": True}, {"alternative": True},
])
def test_different_payments_and_nonassertions_do_not_conflict(changes):
    first = payment_event("a")
    second = replace(payment_event("b", **changes), date=date(2024, 1, 2), amount="200")
    assert cross_document_contradictions({"a": [first], "b": [second]}) == []


def test_payments_without_individual_identity_and_shared_exhibits_do_not_conflict():
    first = payment_event("a", event_identity=None)
    second = replace(payment_event("b", event_identity=None), date=date(2024, 2, 1))
    assert cross_document_contradictions({"a": [first], "b": [second]}) == []
    events = [Event.create(date(2020, 5, 1), "갑 제1호증 회사 설립", event_kind="INCORPORATION"),
              Event.create(date(2019, 3, 1), "갑 제1호증 계약 체결", event_kind="CONTRACT")]
    assert analyze_timeline(events) == []


def test_claim_comparison_adapter_and_legacy_quoted_denial():
    common = dict(project_id="P", transaction_id="T", event_identity="PAY-1", action="PAYMENT",
                  speaker_id="S", target_id="T", amount="100", currency="KRW", stance="ASSERTED")
    a = Claim.create(ClaimType.FACT, "지급하였다", document_id="a", asserted_date="2024-01-01", **common)
    b = replace(a, claim_id="b", document_id="b", asserted_date="2024-01-02")
    assert len(claim_contradictions([a, b], project_id="P")) == 1
    denial = replace(payment_event("b"), description='"지급하지 않았다"라고 주장하였다.', date=date(2024, 2, 1))
    assert cross_document_contradictions({"a": [payment_event("a")], "b": [denial]}) == []


def test_rate_changes_and_explicit_partial_payment_audit():
    rates = [RatePeriod(date(2024, 1, 1), date(2024, 1, 3), D(10), "rate1"),
             RatePeriod(date(2024, 1, 3), date(2024, 1, 5), D(20), "rate2")]
    payment = AllocatedPayment("p1", date(2024, 1, 3), D(18270), D(18250), D(20), "receipt p2")
    result = calculate(end=date(2024, 1, 5), rates=rates, payments=[payment])
    assert result.accrued_interest == D(40) and result.remaining_interest == D(20)
    assert result.remaining_principal == D(18250) and result.total_due == D(18270)
    assert [row.kind for row in result.schedule] == ["ACCRUAL", "PAYMENT", "ACCRUAL"]
    assert [row.days for row in result.schedule] == [2, 0, 2]
    assert result.to_dict()["payments"][0]["amount"] == "18270"
    assert result.to_dict()["assumptions"]["user_confirmed"] is True


@pytest.mark.parametrize("include_start,include_end,days", [(True, False, 1), (False, False, 0), (False, True, 1), (True, True, 2)])
def test_date_endpoint_conventions(include_start, include_end, days):
    result = calculate(end=date(2024, 1, 2), include_start=include_start, include_end=include_end)
    assert result.days == days and result.accrued_interest == D(10 * days)


@pytest.mark.parametrize("convention,expected", [("ACT/365F", "50.14"), ("ACT/360", "50.83"), ("ACT/ACT", "50.00")])
def test_leap_year_day_bases(convention, expected):
    result = calculate(principal="1000", rate="5", end=date(2025, 1, 1), day_count_convention=convention)
    assert result.days == 366 and result.accrued_interest == D(expected)


def test_actual_actual_splits_year_and_isolated_decimal_context():
    result = calculate(start=date(2023, 12, 31), end=date(2024, 1, 2), day_count_convention="ACT/ACT")
    assert [row.year_denominator for row in result.schedule if row.kind == "ACCRUAL"] == [365, 366]
    assert result.schedule[-1].kind == "ROUNDING"
    assert result.schedule[-1].interest_balance == result.remaining_interest
    assert sum((row.posted_interest for row in result.schedule), D(0)) == result.accrued_interest
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.traps[Inexact] = True
        isolated = calculate(start=date(2023, 12, 31), end=date(2024, 1, 2), day_count_convention="ACT/ACT")
    assert isolated == result and result.accrued_interest == D("19.97")


def test_rounding_stage_and_payment_timing_are_material_inputs():
    rates = [RatePeriod(date(2024, 1, 1), date(2024, 1, 2), D(100), "r1"),
             RatePeriod(date(2024, 1, 2), date(2024, 1, 3), D(100), "r2")]
    assert calculate(principal="182.5", end=date(2024, 1, 3), rates=rates, rounding_quantum=D(1), rounding_stage="SEGMENT").accrued_interest == 2
    assert calculate(principal="182.5", end=date(2024, 1, 3), rates=rates, rounding_quantum=D(1)).accrued_interest == 1
    payment = AllocatedPayment("p", date(2024, 1, 1), D(36500), D(36500), D(0), "receipt")
    assert calculate(payments=[payment]).accrued_interest == 0
    assert calculate(payments=[payment], payment_timing="END_OF_DAY").accrued_interest == 10
    assert calculate(payments=[replace(payment, paid_on=date(2024, 1, 11))]).accrued_interest == 100


def test_zero_days_and_multiple_same_day_payments():
    assert calculate(end=date(2024, 1, 1), rates=[]).days == 0
    payments = [AllocatedPayment("p1", date(2024, 1, 1), D(100), D(100), D(0), "r1"),
                AllocatedPayment("p2", date(2024, 1, 1), D(200), D(200), D(0), "r2")]
    assert calculate(payments=payments).remaining_principal == D(36200)


@pytest.mark.parametrize("changes", [{"user_confirmed": False}, {"confirmed_by": " "},
    {"principal_source": ""}, {"day_count_convention": "LEGAL_DEFAULT"}, {"rounding_quantum": D("0.05")},
    {"rounding": "UNKNOWN"}, {"allocation_policy": "INTEREST_FIRST"}, {"include_start": 1}])
def test_unconfirmed_or_unsupported_assumptions_rejected(changes):
    with pytest.raises(ValueError):
        calculate(**changes)


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D(-1), 100.0, D("1e40")])
def test_invalid_principals_rejected(value):
    with pytest.raises(ValueError):
        calculate_segmented_interest(principal=value, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2),
                                     rate_periods=[], payments=[], assumptions=assumptions())


def test_rate_gaps_overlaps_and_payment_overallocations_rejected():
    rates = [RatePeriod(date(2024, 1, 1), date(2024, 1, 3), D(10), "r1"),
             RatePeriod(date(2024, 1, 4), date(2024, 1, 11), D(10), "r2")]
    with pytest.raises(ValueError, match="gap"):
        calculate(rates=rates)
    with pytest.raises(ValueError, match="overlap"):
        calculate(rates=[rates[0], replace(rates[1], start_date=date(2024, 1, 2))])
    bad = AllocatedPayment("bad", date(2024, 1, 1), D(1), D(0), D(1), "r")
    for payment in (bad, replace(bad, amount=D(40000), principal=D(40000), interest=D(0)),
                    replace(bad, amount=D(9)), replace(bad, paid_on=date(2023, 1, 1))):
        with pytest.raises(ValueError):
            calculate(payments=[payment])
    good = replace(bad, principal=D(1), interest=D(0))
    with pytest.raises(ValueError, match="Duplicate"):
        calculate(payments=[good, good])


def api_payload():
    result = calculate()
    return {key: result.to_dict()[key] for key in ("principal", "start_date", "end_date", "rate_periods", "payments", "assumptions")}


def test_segmented_api_roundtrip_and_rejects_unconfirmed_float_and_invalid_period():
    from apps.api.routers.calculations import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        payload = api_payload()
        response = client.post("/api/calculations/interest/segmented", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["accrued_interest"] == "100.00"
        assert response.json()["schedule"][0]["source"] == "synthetic rate"
        for bad in ({**payload, "principal": 1.5}, {**payload, "principal": "NaN"},
                    {**payload, "end_date": "2023-01-01"}, {**payload, "unexpected": True},
                    {**payload, "assumptions": {**payload["assumptions"], "user_confirmed": False}}):
            assert client.post("/api/calculations/interest/segmented", json=bad).status_code == 422


def dataset():
    return (load_jsonl(FIXTURES / "labels.jsonl", LabelRecord),
            load_jsonl(FIXTURES / "predictions.jsonl", PredictionRecord),
            load_jsonl(FIXTURES / "baseline.jsonl", PredictionRecord))


def test_quality_metrics_denominators_case_intervals_and_paired_resource_deltas():
    labels, predictions, baseline = dataset()
    result = evaluate_quality(labels, predictions, baseline=baseline, bootstrap_samples=100, seed=7)
    metrics = result["metrics"]
    assert (metrics["true_positives"], metrics["false_positives"], metrics["false_negatives"]) == (1, 1, 2)
    assert metrics["precision"] == .5 and metrics["recall"] == pytest.approx(1 / 3)
    assert metrics["false_verified"] == 1 and metrics["verified_predictions"] == 2
    assert metrics["false_verified_rate"] == .5 and metrics["coverage"] == .8
    assert result["uncertainty"]["independent_case_families"] == 4
    assert result["baseline"]["paired_resource_delta"]["latency_ms"]["mean_delta"] == -100
    assert result["baseline"]["paired_resource_delta"]["review_seconds"]["mean_delta"] == -46
    assert result["quality_claim"] == "SYNTHETIC_TOOLING_DEMONSTRATION_ONLY" and not result["real_world_quality_proof"]
    assert result == evaluate_quality(labels, predictions, baseline=baseline, bootstrap_samples=100, seed=7)


def test_missing_predictions_and_empty_denominators_never_inflate_scores():
    labels, _, _ = dataset()
    result = evaluate_quality(labels, [], bootstrap_samples=100)
    assert result["metrics"]["missing_predictions"] == 5
    assert result["metrics"]["coverage"] == 0 and result["metrics"]["recall"] == 0
    assert result["metrics"]["precision"] is None and result["metrics"]["false_verified_rate"] is None
    assert result["resources"]["latency_ms"]["n"] == 0
    assert result["uncertainty"]["unsafe_case_family_wilson_95"]["upper"] > 0


@pytest.mark.parametrize("link", ["case_id", "case_family_id", "input_text", "source_hashes"])
def test_split_leakage_guards_before_test_filtering(link):
    labels, predictions, _ = dataset()
    changes = {link: labels[1].model_dump()[link]}
    if link == "source_hashes":
        labels[1] = labels[1].model_copy(update={"source_hashes": ["shared-content-hash"]})
        changes = {link: ["shared-content-hash"]}
    labels[0] = labels[0].model_copy(update=changes)
    with pytest.raises(ValueError, match="leakage|case family"):
        evaluate_quality(labels, predictions, bootstrap_samples=100)


def test_label_schema_attorney_provenance_duplicates_and_nonfinite_measurements():
    labels, predictions, _ = dataset()
    data = labels[1].model_dump()
    with pytest.raises(ValidationError, match="two qualified"):
        LabelRecord.model_validate({**data, "origin": "ATTORNEY_LABELED"})
    with pytest.raises(ValueError, match="Duplicate"):
        validate_case_splits([*labels, labels[0]])
    with pytest.raises(ValueError, match="Duplicate prediction"):
        evaluate_quality(labels, [*predictions, predictions[0]], bootstrap_samples=100)
    with pytest.raises(ValidationError):
        PredictionRecord.model_validate({**predictions[0].model_dump(), "latency_ms": float("nan")})
    assert "case_family_id" in LabelRecord.model_json_schema()["required"]


def test_synthetic_and_attorney_cohorts_must_not_be_pooled():
    labels, predictions, _ = dataset()
    data = labels[1].model_dump()
    data["origin"] = "ATTORNEY_LABELED"
    data["annotation"].update(reviewer_ids=["reviewer-a", "reviewer-b"], qualifications_confirmed=True)
    labels[1] = LabelRecord.model_validate(data)
    with pytest.raises(ValueError, match="pool"):
        evaluate_quality(labels, predictions, bootstrap_samples=100)
    assert evaluate_quality(labels, predictions, origin="SYNTHETIC", bootstrap_samples=100)["metrics"]["items"] == 4


def test_quality_cli_offline_reproducibility(tmp_path):
    output = tmp_path / "quality.json"
    command = [sys.executable, str(ROOT / "scripts" / "evaluate_quality.py"),
               "--labels", str(FIXTURES / "labels.jsonl"), "--predictions", str(FIXTURES / "predictions.jsonl"),
               "--baseline", str(FIXTURES / "baseline.jsonl"), "--bootstrap-samples", "100", "--seed", "7", "--output", str(output)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    first = output.read_bytes()
    assert json.loads(first)["metrics"]["false_verified_rate"] == .5
    assert subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60).returncode == 0
    assert output.read_bytes() == first


@pytest.mark.parametrize("text,value", [("1억 5천만 원", "150000000"), ("1.5억 원", "150000000"), ("-100원", "-100")])
def test_existing_amount_parsing_is_preserved(text, value):
    assert [amount.value for amount in parse_amounts(text)] == [D(value)]


@pytest.mark.parametrize("text", ["1,23원", "1조 5천만 원", "1천 2백 3원", "USD 100원"])
def test_ambiguous_money_is_not_silently_reinterpreted(text):
    assert parse_amounts(text) == []


def test_calculation_workbench_browser_desktop_mobile_and_exact_payload(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from apps.api.routers.calculations import SegmentedInterestRequest, calculate_segmented_interest_endpoint

    static = ROOT / "apps" / "web" / "static"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.abort())
        page.expose_function("calculateOffline", lambda payload: calculate_segmented_interest_endpoint(SegmentedInterestRequest.model_validate(payload)))
        page.set_content('<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body><main style="padding:16px;min-width:0"><section data-panel="calculations"></section></main></body></html>')
        page.add_style_tag(content=static.joinpath("styles.css").read_text(encoding="utf-8"))
        page.add_script_tag(content=static.joinpath("vendor", "lucide.min.js").read_text(encoding="utf-8"))
        page.add_script_tag(content="""
            const state={project:{id:'test-project'}};
            const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=String(text);if(cls)e.className=cls;return e};
            const action=fn=>async event=>{try{await fn(event)}catch(error){throw error}};
            const button=(text,click,cls)=>{const b=node('button',text,cls);b.type='button';b.addEventListener('click',action(click));return b};
            const iconButton=(icon,title,click)=>{const b=button(null,click,'icon');b.title=title;b.setAttribute('aria-label',title);const i=node('i');i.dataset.lucide=icon;b.append(i);return b};
            const icons=()=>lucide.createIcons();
            window.sent=[];window.requestSignals=[];
            const api=async(path,options)=>{window.sent.push({path,body:options.body});window.requestSignals.push(options.signal);const result=await calculateOffline(options.body);if(window.delayResponse)await new Promise((resolve,reject)=>{window.releaseCalculation=resolve;window.rejectCalculation=reject});return result};
        """)
        page.add_script_tag(content=static.joinpath("workflow.js").read_text(encoding="utf-8"))
        page.add_script_tag(content=static.joinpath("calculation-workbench.js").read_text(encoding="utf-8"))
        assert page.evaluate("calculationWorkbench.sync()") is False
        page.evaluate("calculationWorkbench.init(); calculationWorkbench.init()")
        assert page.locator(".calculation-workbench").count() == 1
        root = page.locator(".calculation-workbench")
        for name, value in {"principal": "36500.00", "start_date": "2024-01-01", "end_date": "2024-01-05",
                            "principal_source": "synthetic p1", "period_source": "synthetic p2",
                            "rounding_quantum": "0.01", "convention_source": "synthetic choices", "confirmed_by": "synthetic reviewer"}.items():
            root.locator(f'[name="{name}"]').fill(value)
        for name, value in {"include_start": "true", "include_end": "false", "day_count_convention": "ACT/365F",
                            "rounding": "ROUND_HALF_UP", "rounding_stage": "FINAL", "payment_timing": "START_OF_DAY", "allocation_policy": "EXPLICIT"}.items():
            root.locator(f'[name="{name}"]').select_option(value)
        first = root.locator('[data-row-kind="rate"]').first
        for label, value in [("구간 시작일 (포함)", "2024-01-01"), ("구간 종료일 (불포함)", "2024-01-03"),
                             ("연 이율 (%)", "10"), ("이율 근거: 문서·쪽수·적용 전제", "synthetic rate 1")]:
            first.get_by_label(label, exact=True).fill(value)
        root.get_by_role("button", name="이율 구간 추가", exact=True).click()
        second = root.locator('[data-row-kind="rate"]').last
        for label, value in [("구간 시작일 (포함)", "2024-01-03"), ("구간 종료일 (불포함)", "2024-01-05"),
                             ("연 이율 (%)", "20"), ("이율 근거: 문서·쪽수·적용 전제", "synthetic rate 2")]:
            second.get_by_label(label, exact=True).fill(value)
        root.get_by_role("button", name="변제 추가", exact=True).click()
        payment = root.locator('[data-row-kind="payment"]')
        for label, value in [("변제 식별자", "p1"), ("변제일", "2024-01-03"), ("변제 총액", "18270"),
                             ("원금 충당액", "18250"), ("이자 충당액", "20"), ("변제·충당 근거: 문서·쪽수·확인 내용", "synthetic receipt")]:
            payment.get_by_label(label, exact=True).fill(value)
        root.locator('[name="user_confirmed"]').check()
        root.get_by_role("button", name="계산", exact=True).click()
        expect(root.locator('[role="status"]')).to_have_text("계산 완료")
        sent = page.evaluate("window.sent[0]")
        assert sent["path"] == "/calculations/interest/segmented" and sent["body"]["principal"] == "36500.00"
        assert sent["body"]["payments"][0]["interest"] == "20" and sent["body"]["assumptions"]["include_end"] is False
        expect(root.locator("tbody tr")).to_have_count(3)
        expect(root.locator(".calc-summary")).to_contain_text("18,270.00")
        with page.expect_download() as download_info:
            root.get_by_role("button", name="계산 감사표 JSON 내려받기").click()
        path = tmp_path / "interest-schedule.json"
        download_info.value.save_as(path)
        assert json.loads(path.read_text(encoding="utf-8"))["remaining_interest"] == "20.00"
        root.locator("summary").click()
        for width in (1440, 768, 390):
            page.set_viewport_size({"width": width, "height": 960})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow at {width}"
            assert root.locator("input,select").evaluate_all("els => els.every(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().right <= innerWidth)")
            assert root.locator(".calc-convention-grid select").evaluate_all("""els => els.every(el => {
                const context=document.createElement('canvas').getContext('2d');context.font=getComputedStyle(el).font;
                return context.measureText(el.selectedOptions[0].textContent).width <= el.clientWidth - 40;
            })""")
            page.screenshot(path=str(tmp_path / f"calculation-{width}.png"), full_page=True)
        root.locator('[name="principal"]').fill("40000")
        expect(root.locator('[name="user_confirmed"]')).not_to_be_checked()
        expect(root.get_by_role("button", name="계산 감사표 JSON 내려받기")).to_be_disabled()
        root.get_by_role("button", name="변제 삭제", exact=True).click()
        expect(root.locator('[data-row-kind="payment"]')).to_have_count(0)
        root.get_by_role("button", name="이율 구간 삭제", exact=True).last.click()
        expect(root.locator('[data-row-kind="rate"]')).to_have_count(1)
        # A changed input must invalidate even a response already in flight.
        first.get_by_label("구간 종료일 (불포함)", exact=True).fill("2024-01-05")
        root.locator('[name="user_confirmed"]').check()
        root.get_by_role("button", name="계산", exact=True).click()
        expect(root.locator('[role="status"]')).to_have_text("계산 완료")
        expect(root.locator("tbody tr")).to_have_count(2)
        expect(root.locator("tbody")).to_contain_text("단수 처리")
        page.evaluate("window.delayResponse=true")
        root.get_by_role("button", name="계산", exact=True).click()
        page.wait_for_function("typeof window.releaseCalculation === 'function'")
        root.locator('[name="principal"]').fill("50000")
        page.evaluate("window.releaseCalculation()")
        expect(root.locator('[role="status"]')).to_contain_text("계산 중 입력 또는 사건이 변경")
        expect(root.get_by_role("button", name="계산 감사표 JSON 내려받기")).to_be_disabled()
        # Switch while visible and while a request is pending. The test API
        # deliberately ignores AbortSignal, so the serial guard is also tested.
        page.evaluate("window.releaseCalculation=null")
        root.locator('[name="user_confirmed"]').check()
        root.get_by_role("button", name="계산", exact=True).click()
        page.wait_for_function("typeof window.releaseCalculation === 'function'")
        page.evaluate("window.releaseOldCalculation=window.releaseCalculation; window.releaseCalculation=null; state.project={id:'other-project'}; document.dispatchEvent(new CustomEvent('acas-project-changed',{bubbles:true}))")
        assert page.evaluate("window.requestSignals.at(-1).aborted") is True
        expect(root.locator('[name="principal"]')).to_have_value("")
        expect(root.locator('[name="principal_source"]')).to_have_value("")
        expect(root.locator('[name="day_count_convention"]')).to_have_value("")
        expect(root.locator('[name="user_confirmed"]')).not_to_be_checked()
        expect(root.locator('[data-calculation-output]')).to_be_empty()
        expect(root.get_by_role("button", name="계산", exact=True)).to_be_enabled()
        expect(root.locator('[data-row-kind="rate"]')).to_have_count(1)
        expect(root.locator('[data-row-kind="rate"] input')).to_have_count(4)
        assert root.locator('[data-row-kind="rate"] input').evaluate_all("els=>els.every(el=>el.value==='')")
        root.locator('[name="principal"]').fill("777")
        assert page.evaluate("calculationWorkbench.onProjectChange()") is False
        page.evaluate("calculationWorkbench.init(); window.dispatchEvent(new CustomEvent('acas-project-changed'))")
        expect(root.locator('[name="principal"]')).to_have_value("777")
        page.evaluate("""() => {
            const body=window.sent.at(-1).body, form=document.querySelector('.calculation-workbench form');
            const fill=(el,value)=>{el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}))};
            for(const name of ['principal','start_date','end_date'])fill(form.elements.namedItem(name),body[name]);
            for(const [name,value] of Object.entries(body.assumptions))if(name!=='user_confirmed')fill(form.elements.namedItem(name),value);
            const row=form.querySelector('[data-row-kind=rate]');
            for(const [name,value] of Object.entries(body.rate_periods[0]))fill(row.querySelector('[name$="_'+name+'"]'),value);
        }""")
        root.locator('[name="user_confirmed"]').check()
        root.get_by_role("button", name="계산", exact=True).click()
        page.wait_for_function("typeof window.releaseCalculation === 'function'")
        page.evaluate("async()=>{window.releaseOldCalculation();await new Promise(resolve=>setTimeout(resolve,0))}")
        expect(root.locator('[data-calculation-output]')).to_be_empty()
        expect(root.locator('[role="status"]')).to_have_text("계산 중")
        expect(root.get_by_role("button", name="계산", exact=True)).to_be_disabled()
        page.evaluate("window.releaseCalculation()")
        expect(root.locator('[role="status"]')).to_have_text("계산 완료")
        expect(root.locator('.calc-summary')).to_contain_text("50,000")
        # Late errors must not resurrect a previous project's status either.
        page.evaluate("window.releaseCalculation=null")
        root.get_by_role("button", name="계산", exact=True).click()
        page.wait_for_function("typeof window.releaseCalculation === 'function'")
        page.evaluate("state.project=null; window.dispatchEvent(new CustomEvent('acas-project-changed'))")
        page.evaluate("async()=>{window.rejectCalculation(new Error('old case error'));await new Promise(resolve=>setTimeout(resolve,0))}")
        expect(root.locator('[role="status"]')).to_be_empty()
        expect(root.locator('[name="principal"]')).to_have_value("")
        expect(root.locator('[data-calculation-output]')).to_be_empty()
        root.locator('[name="principal"]').fill("123")
        assert page.evaluate("state.project={id:'third-project'}; calculationWorkbench.sync()") is True
        expect(root.locator('[name="principal"]')).to_have_value("")
        assert errors == []
        browser.close()
