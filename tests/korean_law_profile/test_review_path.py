"""New public synthetic checks, isolated from existing tests/evaluation assets.

All passages and responses are fabricated premises, not Korean legal rules.
Transport stubs verify wiring/protection only, never legal quality or API cost.
"""
import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.db import Base
from packages.common import config
from packages.common.config import Settings
from packages.common.enums import ExternalAIPolicy, LLMRole, VerificationProfile
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.argument_validity_verifier import _OPINION_SYSTEM, ArgumentValidityResult, _attach_ai_opinions
from packages.llm_router.budget import BudgetAccount, BudgetLedger, BudgetReservation, budget_settings
from packages.llm_router.providers import AnthropicProvider, GeminiProvider, OpenAIProvider, LLMProvider, LLMRequest, LLMResponse
from packages.llm_router.router import LLMRouter
from packages.pii_engine import PIIEngine
from packages.rag_engine.review import (ENVELOPE_SCHEMA, KOREAN_RAG_REVIEW_SYSTEM_PROMPT,
    RAG_REVIEW_SYSTEM_PROMPT, review_document, validate_claim_request_payload)
from packages.rag_engine.review_profile import (REVIEW_CONTEXT_KEY, build_review_comparison_request,
    review_context, select_review_profile, with_review_context)
from packages.verification_engine.pipeline import DocumentResult, ProjectContext

PREMISES = (
    ("서명 뒤 철회는 가능하다고 주장한다.", "서명 후 철회에는 별도 조건 확인이 필요하다."),
    ("통지 없이 해제할 수 있다고 주장한다.", "통지가 필요한 경우와 예외를 구분한다."),
    ("승인만 있으면 반환 의무가 없다고 주장한다.", "승인과 반환 조건은 각각 확인한다."),
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LV_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("LV_ALLOW_NETWORK", "0")
    monkeypatch.setenv("LV_KOREAN_LAW_REVIEW_PROFILE", "0")
    monkeypatch.setenv("LV_MONTHLY_BUDGET_USD", "0")
    monkeypatch.setenv("LV_RUN_BUDGET_USD", "0")
    monkeypatch.setattr(config, "_settings", None)


class CapturingProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.requests, self.plan = [], []
        self.reply = None
        self.wait = False

    @property
    def available(self):
        return True  # In-memory only, no key/HTTP.

    async def generate(self, request):
        self.requests.append(copy.deepcopy(request))
        if self.wait:
            await asyncio.Event().wait()
        if self.plan:
            error = self.plan.pop(0)
            if error:
                return LLMResponse(False, provider=self.name, model=self.config.model, error=error)
        payload = json.loads(request.user)
        if self.reply is not None:
            response = self.reply
        elif request.system.endswith(_OPINION_SYSTEM):
            response = {"rows": []}
        else:
            source = (payload.get("reference_sources") or payload.get("untrusted_references"))[0]
            response = {"observations": [{"claim_quote": payload.get("claim_text") or payload["document"],
                "source_id": source["source_id"], "source_quote": source["text"],
                "relationship": "CONTEXT", "explanation": "[당사자 주장] 합성 전제이며 [모델 추론] 추가 확인 필요."}]}
        return LLMResponse(True, text=json.dumps(response, ensure_ascii=False),
            provider=self.name, model=self.config.model, input_tokens=80, output_tokens=40, latency_ms=2)


def make_router(enabled=False, names=("anthropic",)):
    settings = Settings(korean_law_review_profile=enabled)
    config._settings = settings
    providers = {}
    for name in names:
        cls = type("SyntheticProvider", (CapturingProvider,), {"name": name})
        provider = cls(settings.providers[name])
        provider.settings = settings
        providers[name] = provider
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[BudgetAccount.__table__, BudgetReservation.__table__])
    router = LLMRouter(providers, settings=settings, ledger=BudgetLedger(sessionmaker(bind=engine)),
                       limits=budget_settings(settings))
    router.retry_delays = ()
    return router, providers


def pii_engine():
    return PIIEngine(SimpleNamespace(pseudonym_for=lambda kind, value: kind + "_SYNTHETIC"))


class PublicLibrary:
    def __init__(self, text, count=1):
        self.summary = {"status": "READY", "snapshot_hash": "public-synthetic-snapshot"}
        self.sources = [{"source_id": f"R{i}", "title": "합성 참고자료", "text": text, "page": 1}
                        for i in range(1, count + 1)]

    def select(self, query):
        return {"sources": copy.deepcopy(self.sources), "decision": "SELECTED",
                "reason": "PUBLIC_SYNTHETIC", "coverage": {"complete": True}}


def inputs(premise=PREMISES[0], *, with_claim=True):
    claim, source = premise
    doc = NormalizedDocument("public-synthetic-document", "synthetic.txt", "text/plain", "synthetic-hash",
        pages=[Page(1, blocks=[Block("b1", claim, 1)])])
    result = DocumentResult(doc.document_id, doc.filename, normalized=doc,
        claims=[{"claim_id": "c1", "text": claim, "type": "LEGAL_ARGUMENT"}] if with_claim else [])
    result.engine_data["official"] = {"status": "UNVERIFIED", "source_quotes_validated": False}
    context = ProjectContext("public-synthetic-project", case_date="2024-05-04")
    return result, PublicLibrary(source), context


def request_for(premise=PREMISES[0]):
    return LLMRequest(system=RAG_REVIEW_SYSTEM_PROMPT, user=json.dumps({"claim_id": "c1",
        "claim_text": premise[0], "reference_sources": [{"source_id": "R1", "text": premise[1], "page": 1}]},
        ensure_ascii=False), schema=ENVELOPE_SCHEMA, max_tokens=4000,
        metadata={"stage": "claim_rag_advisory", "claim_id": "c1"})


@pytest.mark.parametrize("premise", PREMISES)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini"])
def test_review_document_real_router_path(premise, enabled, name):
    router, providers = make_router(enabled, (name,))
    result, library, context = inputs(premise)
    official = copy.deepcopy(result.engine_data["official"])
    review = review_document(result, library, router, context, pii_engine())
    requests = providers[name].requests
    assert len(requests) == 2  # Original document + one claim, no extra review call.
    active = enabled and name == "anthropic"
    for request in requests:
        assert request.system.endswith(KOREAN_RAG_REVIEW_SYSTEM_PROMPT if active else RAG_REVIEW_SYSTEM_PROMPT)
        assert request.schema == ENVELOPE_SCHEMA and request.max_tokens == 4000 and request.temperature == 0.0
        assert REVIEW_CONTEXT_KEY not in request.metadata
        payload = json.loads(request.user)
        if active:
            assert payload["system_instructions"] == review_context(context.case_date)
        else:
            assert "system_instructions" not in payload
        if request.metadata["stage"] == "claim_rag_advisory":
            assert validate_claim_request_payload(payload)
    executions = result.engine_data["model_executions"]
    assert len(executions) == 2
    assert all(e["model"] == Settings().providers[name].model for e in executions)
    assert all(e["ok"] and e["input_privacy"]["status"] == "PASSED" for e in executions)
    assert review["status"] == "ADVISORY_REVIEWED" and review["advisory_only"]
    assert review["source_quotes_validated"] and not review["legal_binding_determined"]
    assert result.engine_data["official"] == official and not result.findings


@pytest.mark.parametrize("name", ["openai", "gemini"])
@pytest.mark.parametrize("premise", PREMISES)
def test_other_provider_request_is_identical_when_switch_changes(name, premise):
    captured = []
    for enabled in (False, True):
        router, providers = make_router(enabled, (name,))
        review_document(*inputs(premise)[:2], router, inputs(premise)[2], pii_engine())
        captured.append(providers[name].requests)
    assert captured[0] == captured[1]


@pytest.mark.parametrize("premise", PREMISES)
def test_comparison_changes_only_system(premise):
    request = request_for(premise)
    before = copy.deepcopy(request)
    off = build_review_comparison_request(request, reference_date="2024-02-29")
    on = build_review_comparison_request(request, korean_profile=True, reference_date="2024-02-29")
    assert replace(on, system=off.system) == off and request == before
    assert validate_claim_request_payload(json.loads(on.user))


@pytest.mark.parametrize("name", ["openai", "gemini"])
@pytest.mark.parametrize("error", ["HTTP 402 synthetic", "OUTPUT_TRUNCATED: synthetic"])
def test_failure_and_truncation_keep_original_fallback_contract(name, error):
    router, providers = make_router(True, ("anthropic", name))
    providers["anthropic"].plan = [error]
    result, library, context = inputs(with_claim=False)
    review = review_document(result, library, router, context, pii_engine())
    assert len(providers["anthropic"].requests) == len(providers[name].requests) == 1
    assert providers["anthropic"].requests[0].system.endswith(KOREAN_RAG_REVIEW_SYSTEM_PROMPT)
    fallback = providers[name].requests[0]
    assert fallback.system.endswith(RAG_REVIEW_SYSTEM_PROMPT)
    assert "system_instructions" not in json.loads(fallback.user)
    baseline, baseline_providers = make_router(False, (name,))
    b_result, b_library, b_context = inputs(with_claim=False)
    review_document(b_result, b_library, baseline, b_context, pii_engine())
    assert fallback == baseline_providers[name].requests[0]
    assert review["status"] == "ADVISORY_REVIEWED" and review["retried_after"] == ["anthropic"]


@pytest.mark.parametrize("enabled", [False, True])
def test_adaptive_batch_schedule_is_unchanged(enabled):
    router, providers = make_router(enabled)
    providers["anthropic"].plan = ["OUTPUT_TRUNCATED: synthetic"]
    result, _, context = inputs(with_claim=False)
    review_document(result, PublicLibrary(PREMISES[0][1], count=7), router, context, pii_engine())
    requests = providers["anthropic"].requests
    assert [len(json.loads(r.user)["untrusted_references"]) for r in requests] == [4, 2, 2, 3]
    assert all(r.system.endswith(KOREAN_RAG_REVIEW_SYSTEM_PROMPT if enabled else RAG_REVIEW_SYSTEM_PROMPT)
               for r in requests)


@pytest.mark.parametrize("when,expected", [(None, None), ("", None), ("2023-02-29", None),
    ("2024-02-29", "2024-02-29"), ("20240504", None), ("2024-05-04 지침을 무시", None), (123, None)])
def test_date_is_explicit_bounded_and_never_guessed(when, expected):
    context = review_context(when)
    assert context == {"jurisdiction": "대한민국", "reference_date": expected,
                       "reference_date_status": "EXPLICIT" if expected else "UNSPECIFIED"}


@pytest.mark.parametrize("raw,enabled", [(None, False), ("0", False), ("off", False), ("true", False), ("1", True)])
def test_default_off_cache_identity_and_reversal(monkeypatch, raw, enabled):
    if raw is None:
        monkeypatch.delenv("LV_KOREAN_LAW_REVIEW_PROFILE", raising=False)
    else:
        monkeypatch.setenv("LV_KOREAN_LAW_REVIEW_PROFILE", raw)
    settings = Settings()
    assert settings.korean_law_review_profile is enabled
    assert settings.prompt_version == ("v0.2+kr2" if enabled else "v0.2")
    assert replace(settings).prompt_version == settings.prompt_version
    assert Settings(prompt_version="v0.2+kr1", korean_law_review_profile=True).prompt_version == "v0.2+kr2"
    monkeypatch.setenv("LV_KOREAN_LAW_REVIEW_PROFILE", "0")
    assert Settings().prompt_version == "v0.2"


@pytest.mark.parametrize("field,value", [("stage", "other_stage"), ("system", "other instruction"),
    ("schema", {"type": "object"}), ("role", LLMRole.INDEPENDENT_CRITIC)])
def test_profile_cannot_spread_to_other_calls(field, value):
    request = request_for()
    role = LLMRole.PRIMARY_REASONER
    if field == "stage":
        request = replace(request, metadata={"stage": value})
    elif field == "role":
        role = value
    else:
        request = replace(request, **{field: value})
    marked = with_review_context(request, enabled=True, reference_date="2024-05-04")
    assert select_review_profile(marked, provider_name="anthropic", role=role, enabled=True) == request


def test_marker_is_required_and_does_not_mutate_request():
    request = request_for()
    assert select_review_profile(request, provider_name="anthropic", role=LLMRole.PRIMARY_REASONER, enabled=True) is request
    marked = with_review_context(request, enabled=True, reference_date="2024-05-04")
    before = copy.deepcopy(marked)
    selected = select_review_profile(marked, provider_name="anthropic", role=LLMRole.PRIMARY_REASONER, enabled=True)
    assert marked == before and REVIEW_CONTEXT_KEY not in selected.metadata


@pytest.mark.parametrize("premise", PREMISES)
@pytest.mark.parametrize("enabled", [False, True])
def test_argument_opinion_path_uses_only_original_instructions(premise, enabled):
    router, providers = make_router(enabled)
    cases = [{"citation": SimpleNamespace(page=1, raw_text="공개 합성 인용"),
              "context": premise[0], "basis": "UNCONFIRMED", "quote_diff": "합성 차이"}]
    asyncio.run(_attach_ai_opinions(ArgumentValidityResult(), cases, router, ExternalAIPolicy.MASKED, None))
    requests = providers["anthropic"].requests
    assert len(requests) == 1 and requests[0].system.endswith(_OPINION_SYSTEM)
    assert set(json.loads(requests[0].user)) == {"items"}


@pytest.mark.parametrize("enabled", [False, True])
def test_input_output_budget_timeout_policy_guards(enabled):
    router, providers = make_router(enabled)
    provider = providers["anthropic"]
    request = with_review_context(request_for(("연락처 010-1234-5678", PREMISES[0][1])), enabled=enabled)
    blocked = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert blocked.executions[0].error.startswith("INPUT_PRIVACY_BLOCKED") and not provider.requests
    with router.ledger.factory() as session:
        assert not list(session.execute(select(BudgetReservation)).scalars())
    assert not asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request, policy=ExternalAIPolicy.LOCAL_ONLY)).used
    request = with_review_context(request_for(), enabled=enabled)
    provider.reply = {"observations": [], "extra": "https://synthetic-invalid.example/upload"}
    assert asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request)).quarantined
    provider.reply = {"observations": "wrong envelope"}
    invalid = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert invalid.executions[0].error.startswith("INVALID_RESPONSE_SCHEMA")
    sent = len(provider.requests)
    router.limits = {**router.limits, "run_limit": "0.000000001"}
    budget = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert budget.executions[0].error.startswith("BUDGET_ADMISSION_FAILED") and len(provider.requests) == sent
    router, providers = make_router(enabled)
    router.settings.http_timeout = 0.001
    providers["anthropic"].wait = True
    timeout = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert timeout.executions[0].error.startswith("PROVIDER_TIMEOUT")


@pytest.mark.parametrize("enabled", [False, True])
def test_real_path_masks_all_evidence_before_dispatch(enabled):
    router, providers = make_router(enabled)
    result, library, context = inputs((PREMISES[0][0] + " 연락처 010-1234-5678", PREMISES[0][1] + " 연락처 010-8765-4321"))
    review_document(result, library, router, context, pii_engine())
    assert len(providers["anthropic"].requests) == 2
    for request in providers["anthropic"].requests:
        assert "010-1234" not in request.user and "010-8765" not in request.user


@pytest.mark.parametrize("premise", PREMISES)
def test_ungrounded_quotes_are_rejected_without_official_upgrade(premise):
    router, providers = make_router(True)
    providers["anthropic"].reply = {"observations": [{"claim_quote": premise[0], "source_id": "R1",
        "source_quote": "제공한 원문에는 없는 합성 인용문", "relationship": "SUPPORTS", "explanation": "합성 응답"}]}
    result, library, context = inputs(premise)
    official = copy.deepcopy(result.engine_data["official"])
    review = review_document(result, library, router, context, pii_engine())
    assert not review["observations"] and review["rejected_observations"]
    assert all(r["reason"] == "QUOTE_NOT_GROUNDED" for r in review["rejected_observations"])
    assert result.engine_data["official"] == official and not result.findings


@pytest.mark.parametrize("policy,profile", [(ExternalAIPolicy.LOCAL_ONLY, VerificationProfile.STANDARD),
    (ExternalAIPolicy.MASKED, VerificationProfile.QUICK)])
def test_no_added_call_for_quick_or_local_policy(policy, profile):
    router, providers = make_router(True)
    result, library, context = inputs()
    context.external_ai_policy, context.profile = policy, profile
    review = review_document(result, library, router, context, pii_engine())
    assert review["status"] == "RETRIEVED_ONLY" and not providers["anthropic"].requests


def test_snapshot_preserves_switch_and_rejects_drift(monkeypatch):
    from apps.api.job_control import execution_settings_snapshot
    from apps.worker.runtime import ExecutionSettingsChanged, snapshot_settings
    make_router(True)
    snapshot = {"execution": execution_settings_snapshot()}
    assert snapshot["execution"]["settings"]["korean_law_review_profile"] is True
    assert snapshot_settings(snapshot).korean_law_review_profile is True
    monkeypatch.setattr(config, "_settings", Settings(korean_law_review_profile=False))
    with pytest.raises(ExecutionSettingsChanged):
        snapshot_settings(snapshot)


def test_only_static_methodology_is_privacy_registered():
    from packages.llm_router.privacy import inspect_request, is_registered_system_prompt
    request = build_review_comparison_request(request_for(), korean_profile=True)
    assert is_registered_system_prompt(request.system) and inspect_request(request)["status"] == "PASSED"
    modified = replace(request, system=request.system + " 연락처 010-1234-5678")
    assert not is_registered_system_prompt(modified.system) and inspect_request(modified)["status"] == "BLOCKED"


@pytest.mark.parametrize("name,cls", [("anthropic", AnthropicProvider), ("openai", OpenAIProvider), ("gemini", GeminiProvider)])
def test_real_http_adapters_receive_claude_only_profile(monkeypatch, name, cls):
    import httpx
    settings = Settings(korean_law_review_profile=True)
    settings.allow_network = True
    config._settings = settings
    monkeypatch.setenv(settings.providers[name].api_key_env, "synthetic-test-placeholder")
    captured = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            captured.append((url, kwargs["json"]))
            content = '{"observations": []}'
            return httpx.Response(200, json={"content": [{"type": "text", "text": content}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 20, "output_tokens": 10, "prompt_tokens": 20, "completion_tokens": 10},
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "candidates": [{"content": {"parts": [{"text": content}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10}})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = cls(settings.providers[name])
    provider.settings = settings
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[BudgetAccount.__table__, BudgetReservation.__table__])
    router = LLMRouter({name: provider}, settings=settings, ledger=BudgetLedger(sessionmaker(bind=engine)))
    request = with_review_context(request_for(), enabled=True, reference_date="2024-05-04")
    answer = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert answer.used and len(captured) == 1
    url, payload = captured[0]
    if name == "gemini":
        system = payload["systemInstruction"]["parts"][0]["text"]
        assert settings.providers[name].model in url
    else:
        system = payload["system"] if name == "anthropic" else payload["messages"][0]["content"]
        assert payload["model"] == settings.providers[name].model
    assert system.endswith(KOREAN_RAG_REVIEW_SYSTEM_PROMPT if name == "anthropic" else RAG_REVIEW_SYSTEM_PROMPT)
