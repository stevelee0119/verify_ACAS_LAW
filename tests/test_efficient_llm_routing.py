"""Synthetic transport/ledger tests; these do not measure legal review quality."""
import asyncio
import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.common.config import Settings
from packages.common.enums import ExternalAIPolicy, LLMRole
from packages.llm_router.budget import BudgetAccount, BudgetLedger, BudgetReservation, usage_cost
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.llm_router.router import LLMRouter
from packages.llm_router.routing import sampled


@pytest.fixture
def transport(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "synthetic-test-key")
    settings = Settings(allow_network=True, storage_root=tmp_path, llm_review_sample_percent=0,
                        llm_cross_check="auto", llm_efficient_routing=True)
    requests, responses = [], {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, **kwargs):
            requests.append((url, json))
            family = "anthropic" if "anthropic" in url else "gemini" if "googleapis" in url else "openai"
            value = responses.get(family, {"status": "VERIFIED", "rationale": "synthetic", "evidence_quotes": ["source"]})
            if isinstance(value, int):
                return httpx.Response(value, json={"error": "synthetic rejection"})
            text = __import__("json").dumps(value)
            if family == "anthropic":
                body = {"content": [{"text": text}], "usage": {"input_tokens": 100, "output_tokens": 10}}
            elif family == "gemini":
                body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 5}}
            else:
                body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
            return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    engine = create_engine("sqlite:///:memory:")
    BudgetAccount.metadata.create_all(engine, tables=[BudgetAccount.__table__, BudgetReservation.__table__])
    ledger = BudgetLedger(sessionmaker(engine))
    router = LLMRouter(settings=settings, ledger=ledger)
    return router, requests, responses


def test_model_tiers_do_not_mutate_shared_provider(transport):
    router, requests, _ = transport
    original = router.providers["anthropic"].config.model
    request = LLMRequest("system", "synthetic text")
    for role, req in ((LLMRole.PRIMARY_REASONER, request), (LLMRole.INDEPENDENT_CRITIC, request),
                      (LLMRole.PRIMARY_REASONER, replace(request, model_tier="escalation"))):
        assert asyncio.run(router.run(role, req)).used
    assert [body["model"] for _, body in requests] == ["claude-sonnet-5-5", "gpt-6.1-sol", "claude-opus-5-5"]
    assert router.providers["anthropic"].config.model == original


def test_duplicate_reuses_only_after_policy_checks_and_clear_starts_new_scope(transport):
    router, requests, _ = transport
    request = LLMRequest("system", "synthetic text")
    first = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    second = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert first.total_cost > 0 and second.total_cost == 0
    assert second.executions[0].reused and second.executions[0].cost_status == "CACHED"
    assert len(requests) == 1
    router.provider_guard = lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("revoked"))
    blocked = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert not blocked.used and blocked.executions[0].cost_status == "NOT_SENT"
    router.provider_guard = None
    router.clear_result_cache()
    assert asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request)).used
    assert len(requests) == 2


def test_policy_and_input_are_part_of_cache_identity(transport):
    router, requests, _ = transport
    for text, policy in (("one", ExternalAIPolicy.MASKED), ("two", ExternalAIPolicy.MASKED),
                         ("one", ExternalAIPolicy.ORIGINAL)):
        assert asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", text), policy=policy)).used
    assert len(requests) == 3
    assert not asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "one"),
                                     policy=ExternalAIPolicy.LOCAL_ONLY)).used
    assert len(requests) == 3


@pytest.mark.parametrize("status", ["VERIFIED", "CONTRADICTED", "UNVERIFIED"])
def test_auto_legal_review_has_two_independent_models_even_at_high_confidence(transport, status):
    router, requests, responses = transport
    for family in ("anthropic", "openai", "gemini"):
        responses[family] = {"status": status, "rationale": "synthetic", "confidence": 1,
                             "evidence_quotes": ["source"]}
    result = asyncio.run(router.cascade(question="synthetic question", evidence={"official": {"full_text": "source"}}))
    assert len(requests) == 2
    critic = next(body for url, body in requests if "openai" in url)
    assert '"confidence": 1' not in critic["messages"][1]["content"]
    assert {e.provider for e in result.executions} == {"anthropic", "openai"}


def test_disagreement_keeps_abstention_and_opus_is_not_an_extra_vote(transport):
    router, requests, responses = transport
    responses["openai"] = {"status": "CONTRADICTED", "rationale": "synthetic", "evidence_quotes": ["source"]}
    result = asyncio.run(router.cascade(question="q", evidence={"official": {"full_text": "source"}}))
    assert str(result.status) == "UNVERIFIED" and result.disagreement
    assert any(body.get("model") == "claude-opus-5-5" for _, body in requests)
    extra = next(s for s in result.stages if s["name"] == "escalation")
    assert extra["advisory_only"] and "verdict" not in extra


def test_failed_primary_falls_back_and_retains_failure_record(transport):
    router, requests, responses = transport
    responses["anthropic"] = 401
    result = asyncio.run(router.run_any(LLMRole.PRIMARY_REASONER, LLMRequest("system", "synthetic text")))
    assert result.used and [e.provider for e in result.executions] == ["anthropic", "openai"]
    assert not result.executions[0].ok
    assert requests[-1][1]["model"] == "gpt-6.1-sol"


def test_gemini_thinking_is_settled_from_reported_usage(transport):
    router, _, _ = transport
    result = asyncio.run(router.run(LLMRole.WEB_GROUNDER, LLMRequest("system", "synthetic text")))
    execution = result.executions[0]
    assert execution.output_tokens == 15 and execution.thinking_tokens == 5
    assert execution.cost_status == "REPORTED"
    assert Decimal(str(execution.cost_usd)) == Decimal("0.00013125")


def test_cache_tokens_are_charged_at_their_own_rates():
    reply = LLMResponse(True, input_tokens=1000, output_tokens=100, cache_read_tokens=600, cache_write_tokens=200)
    cost, status = usage_cost(reply, (Decimal(2), Decimal(10)), Decimal(1),
        pricing={"cache_read": .1, "cache_write": 2.5})
    assert status == "REPORTED" and cost == Decimal("0.00196")
    reply.usage_complete = False
    assert usage_cost(reply, (Decimal(2), Decimal(10)), Decimal(1))[1] == "ESTIMATED"


def test_routing_changes_invalidate_reusable_run_identity(transport):
    router, _, _ = transport
    first = router.settings.model_config_version()
    router.settings.llm_routing["openai_review"] = "alternative-test-model"
    assert router.settings.model_config_version() != first
    router.settings.llm_cross_check = "all"
    assert router.settings.model_config_version() != first


def test_sampling_is_stable_and_endpoints_are_exact():
    request = LLMRequest("system", "synthetic text")
    assert not sampled(request, 0) and sampled(request, 100)
    assert sampled(request, 10) == sampled(replace(request), 10)


def authorship_request(hint=False):
    from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA
    coverage = {"total_chars": 20, "inspected_chars": 20, "sampling_mode": "full_text",
                "is_full_coverage": True, "omitted_chars": 0, "char_limit": 24000,
                "quote_masked_chars": 0, "scope": "BODY_WITH_QUOTES_AND_INSTRUCTIONS_EXCLUDED",
                "requested_chars": 20, "model_executed": False}
    return LLMRequest(AI_DETECTOR_SYSTEM_PROMPT, json.dumps({"document_filename": "synthetic.txt",
        "metadata_ai_hint": hint, "document_sample_text": "synthetic review text", "document_coverage": coverage}),
        schema=_DETECTOR_SCHEMA, input_contract="ai_document_v1")


@pytest.mark.parametrize("verdict,hint,sample,count", [
    ("UNCERTAIN", False, 0, 1), ("HUMAN_AUTHORED_LIKELY", False, 0, 1),
    ("AI_PARTIAL_GENERATION", False, 0, 2), ("AI_FULL_GENERATION_LIKELY", False, 0, 2),
    ("UNCERTAIN", True, 0, 2), ("UNCERTAIN", False, 100, 2),
])
def test_authorship_uses_luna_and_adds_independent_review_for_signal_or_sample(transport, verdict, hint, sample, count):
    router, requests, responses = transport
    router.settings.llm_review_sample_percent = sample
    for family in ("anthropic", "openai", "gemini"):
        responses[family] = {"verdict": verdict}
    answers = asyncio.run(router.consult_all(LLMRole.PRIMARY_REASONER, authorship_request(hint)))
    assert len(requests) == count and all(a.used for a in answers)
    assert requests[0][1]["model"] == "gpt-6-luna"


@pytest.mark.parametrize("kept", [[], [1], [2]])
def test_partial_argument_rows_do_not_skip_third_provider(transport, kept):
    from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
    router, requests, responses = transport
    for family in ("anthropic", "openai"):
        responses[family] = {"rows": [{"item_id": i, "validity_verdict": "판단 불가"} for i in kept]}
    responses["gemini"] = {"rows": [{"item_id": i, "validity_verdict": "판단 불가"} for i in (1, 2)]}
    request = LLMRequest(_OPINION_SYSTEM, json.dumps({"items": [
        {"item_id": i, "page": 1, "cited_case": "synthetic reference", "확인 상태": "미확인",
         "surrounding_context_and_claim": "synthetic argument"} for i in (1, 2)]}),
        schema=_OPINION_SCHEMA, input_contract="argument_review_v1")
    answers = asyncio.run(router.consult_all(LLMRole.PRIMARY_REASONER, request))
    assert len(requests) == 3 and {e.provider for a in answers for e in a.executions} == {"anthropic", "openai", "gemini"}


def test_explicit_operator_model_is_not_silently_overridden(transport, monkeypatch):
    router, requests, _ = transport
    router.providers["openai"].config.model = "operator-selected-model"
    assert asyncio.run(router.run(LLMRole.INDEPENDENT_CRITIC, LLMRequest("system", "synthetic text"))).used
    assert requests[-1][1]["model"] == "operator-selected-model"


def test_gemini_promotion_expiry_changes_pricing_without_mutating_table(transport):
    from packages.llm_router.budget import effective_pricing
    router, _, _ = transport
    provider = router.providers["gemini"]
    assert effective_pricing(router.settings, provider, today="2026-12-31")["input"] == .75
    assert effective_pricing(router.settings, provider, today="2027-01-01")["input"] == 1.5
    assert router.settings.pricing["gemini-3.8-flash"]["input"] == .75


def test_explicit_default_model_has_distinct_identity_and_routing_is_frozen(transport, monkeypatch):
    from packages.llm_router.routing import task_provider
    router, _, _ = transport
    monkeypatch.delenv("LV_OPENAI_MODEL", raising=False)
    initial = Settings(storage_root=router.settings.storage_root)
    monkeypatch.setenv("LV_OPENAI_MODEL", initial.providers["openai"].model)
    explicit = Settings(storage_root=router.settings.storage_root)
    assert initial.model_config_version() != explicit.model_config_version()
    request = authorship_request()
    provider = router.providers["openai"]
    assert task_provider(provider, LLMRole.PRIMARY_REASONER, request, initial).config.model == "gpt-6-luna"
    assert task_provider(provider, LLMRole.PRIMARY_REASONER, request, explicit).config.model == "gpt-6.1-sol"
    monkeypatch.delenv("LV_OPENAI_MODEL")
    assert task_provider(provider, LLMRole.PRIMARY_REASONER, request, explicit).config.model == "gpt-6.1-sol"


def test_old_queue_snapshot_cannot_silently_use_new_routing(transport, monkeypatch):
    from apps.api.job_control import execution_settings_snapshot
    from apps.worker import runtime
    router, _, _ = transport
    monkeypatch.setattr(runtime, "get_settings", lambda: router.settings)
    snapshot = {"execution": execution_settings_snapshot()}
    snapshot["execution"]["settings"].pop("llm_routing")
    with pytest.raises(runtime.ExecutionSettingsChanged, match="routing snapshot missing"):
        runtime.snapshot_settings(snapshot)


def test_provider_cache_writes_require_explicit_opt_in(transport):
    router, requests, _ = transport
    assert not router.settings.llm_prompt_caching
    request = LLMRequest("system", "synthetic text")
    assert asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request)).used
    assert "cache_control" not in requests[-1][1]
    router.settings.llm_prompt_caching = True
    router.clear_result_cache()
    assert asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request)).used
    assert requests[-1][1]["cache_control"] == {"type": "ephemeral"}
