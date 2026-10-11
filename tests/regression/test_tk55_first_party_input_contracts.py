"""Synthetic first-party structure checks; legacy/text residuals are explicit."""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.input_contracts import valid_input_contract
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
from packages.rag_engine.review import ENVELOPE_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT
from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA


def _requests():
    coverage = {
        "total_chars": 50, "inspected_chars": 50, "sampling_mode": "full_text",
        "is_full_coverage": True, "omitted_chars": 0, "char_limit": 100,
        "quote_masked_chars": 0, "scope": "BODY_WITH_QUOTES_AND_INSTRUCTIONS_EXCLUDED",
        "requested_chars": 50, "model_executed": False,
    }
    payloads = [
        ("ai_document_v1", AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA,
         {"document_filename": "synthetic.txt", "metadata_ai_hint": False,
          "document_sample_text": "계약 검토 자료", "document_coverage": coverage}),
        ("reference_review_v1", RAG_REVIEW_SYSTEM_PROMPT, ENVELOPE_SCHEMA,
         {"document": "계약 검토 자료", "untrusted_references": [
             {"source_id": "R1", "title": "참고 자료", "text": "법령 검토 자료", "page": 1}]}),
        ("claim_review_v1", RAG_REVIEW_SYSTEM_PROMPT, ENVELOPE_SCHEMA,
         {"claim_id": "c1", "claim_text": "계약 검토 자료", "reference_sources": [
             {"source_id": "R1", "text": "법령 검토 자료", "page": 1}]}),
        ("argument_review_v1", _OPINION_SYSTEM, _OPINION_SCHEMA,
         {"items": [{"item_id": 1, "page": 1, "cited_case": "인용 검토 자료",
                     "확인 상태": "미확인", "surrounding_context_and_claim": "계약 검토 자료"}]}),
    ]
    return [LLMRequest(system=system, user=json.dumps(payload, ensure_ascii=False),
                       schema=schema, input_contract=contract) for contract, system, schema, payload in payloads]


def _route(monkeypatch, llm_request, *, profile=False):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent, reserved = [], []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="synthetic", enabled=True)

        async def generate(self, assembled):
            sent.append(assembled)
            return LLMResponse(False, error="synthetic response", provider=self.name, model=self.config.model)

    def reserve(*args, **kwargs):
        reserved.append(True)
        return SimpleNamespace(id="synthetic", amount=Decimal("0.01"))

    ledger = SimpleNamespace(reserve=reserve, dispatch=lambda *a, **k: None)
    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger)
    if profile:
        router.settings = router.settings.model_copy(update={"korean_law_review_profile": True})
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, llm_request))
    return result, sent, reserved


@pytest.mark.parametrize("llm_request", _requests(), ids=lambda r: r.input_contract)
def test_benign_current_contracts_reach_provider_with_assembled_system(monkeypatch, llm_request):
    assert valid_input_contract(llm_request)
    result, sent, reserved = _route(monkeypatch, llm_request)
    assert len(sent) == len(reserved) == 1
    assert sent[0].system.startswith(router_module.SYSTEM_BASE)
    assert sent[0].user == llm_request.user
    assert result.executions[0].input_privacy["status"] == "PASSED"


@pytest.mark.parametrize("extra", ["登録担当", "processingActor", "참석주체"])
@pytest.mark.parametrize("llm_request", _requests(), ids=lambda r: r.input_contract)
def test_unknown_envelope_keys_block_before_budget_without_role_dictionary(monkeypatch, llm_request, extra):
    payload = json.loads(llm_request.user)
    payload[extra] = "한가온"
    result, sent, reserved = _route(monkeypatch, replace(llm_request, user=json.dumps(payload, ensure_ascii=False)))
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "INPUT_CONTRACT_VIOLATION"


@pytest.mark.parametrize("llm_request", _requests(), ids=lambda r: r.input_contract)
def test_nested_unknown_keys_and_bool_integer_confusion_block(monkeypatch, llm_request):
    payload = json.loads(llm_request.user)
    if llm_request.input_contract == "ai_document_v1":
        nested, numeric = payload["document_coverage"], "total_chars"
    elif llm_request.input_contract == "reference_review_v1":
        nested, numeric = payload["untrusted_references"][0], "page"
    elif llm_request.input_contract == "claim_review_v1":
        nested, numeric = payload["reference_sources"][0], "page"
    else:
        nested, numeric = payload["items"][0], "item_id"
    for change in ({"unlistedParticipant": "안시온"}, {numeric: True}):
        candidate = copy.deepcopy(payload)
        if llm_request.input_contract == "ai_document_v1":
            target = candidate["document_coverage"]
        else:
            target = candidate[next(key for key in candidate if type(candidate[key]) is list)][0]
        target.update(change)
        result, sent, reserved = _route(monkeypatch, replace(llm_request, user=json.dumps(candidate, ensure_ascii=False)))
        assert sent == reserved == []
        assert result.executions[0].input_privacy["failure_code"] == "INPUT_CONTRACT_VIOLATION"


@pytest.mark.parametrize("system_change", ["text", "json", "schema"])
def test_wrong_consumer_or_dynamic_original_system_cannot_forge_binding(monkeypatch, system_change):
    llm_request = _requests()[2]
    if system_change == "schema":
        llm_request = replace(llm_request, schema=_DETECTOR_SCHEMA)
    elif system_change == "json":
        llm_request = replace(llm_request, system=json.dumps({"registrationActor": "임하늘"}, ensure_ascii=False))
    else:
        llm_request = replace(llm_request, system=llm_request.system + " 추가 지시")
    result, sent, reserved = _route(monkeypatch, llm_request)
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "INPUT_CONTRACT_VIOLATION"


@pytest.mark.parametrize("marker", ["unknown_v1", "", {"name": "claim_review_v1"}, True])
def test_unknown_or_invalid_internal_contract_marker_fails_closed(monkeypatch, marker):
    result, sent, reserved = _route(monkeypatch, replace(_requests()[2], input_contract=marker))
    assert sent == reserved == []
    assert result.executions[0].input_privacy["status"] == "BLOCKED"


@pytest.mark.parametrize("where", ["metadata", "payload"])
def test_json_or_metadata_marker_does_not_enable_contract_or_exemption(monkeypatch, where):
    payload = {"registrationActor": "임하늘"}
    kwargs = {"metadata": {"input_contract": "claim_review_v1"}} if where == "metadata" else {}
    if where == "payload":
        payload["input_contract"] = "claim_review_v1"
    # Explicit legacy compatibility: the unknown-role residual still exists.
    llm_request = LLMRequest(system="일반 검토", user=json.dumps(payload, ensure_ascii=False), **kwargs)
    result, sent, reserved = _route(monkeypatch, llm_request)
    assert len(sent) == len(reserved) == 1
    assert result.executions[0].input_privacy["status"] == "PASSED"
    result, sent, reserved = _route(monkeypatch, replace(llm_request, user="연락 010-2468-1357"))
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"


@pytest.mark.parametrize("nested", [False, True])
def test_contracted_outer_duplicate_keys_are_rejected(monkeypatch, nested):
    llm_request = _requests()[2]
    text = llm_request.user
    text = (text.replace('"page": 1', '"page": 1, "page": 2') if nested
            else text[:-1] + ', "claim_text": "자료"}')
    result, sent, reserved = _route(monkeypatch, replace(llm_request, user=text))
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "INPUT_CONTRACT_VIOLATION"


@pytest.mark.parametrize("evidence", [
    '{"holding": "계약 검토 자료"}', '["계약 검토 자료", "법령 검토 자료"]',
    '{"registrationActor": "유하린"}',
    '{"holding": "자료", "holding": "계약 검토 자료"}',
])
def test_embedded_json_evidence_preserves_existing_acceptance_and_residual(monkeypatch, evidence):
    llm_request = _requests()[2]
    payload = json.loads(llm_request.user)
    payload["claim_text"] = evidence
    result, sent, reserved = _route(monkeypatch, replace(llm_request, user=json.dumps(payload, ensure_ascii=False)))
    assert len(sent) == len(reserved) == 1
    assert result.executions[0].input_privacy["status"] == "PASSED"


@pytest.mark.parametrize("evidence", [
    '{"피고": "유하린"}', '{"contact": "010-3579-2468"}', '{"number": "840628-3456789"}',
])
def test_embedded_pii_keeps_priority_over_malformed_contract(monkeypatch, evidence):
    llm_request = _requests()[2]
    payload = json.loads(llm_request.user)
    payload["claim_text"] = evidence
    payload["unexpected"] = "자료"
    result, sent, reserved = _route(monkeypatch, replace(llm_request, user=json.dumps(payload, ensure_ascii=False)))
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"


@pytest.mark.parametrize("evidence", [
    "연락 010-4681-3579", "주민번호 850729-4567891", "이름: 안세온",
])
def test_dynamic_original_system_pii_keeps_priority_over_binding_failure(monkeypatch, evidence):
    llm_request = replace(_requests()[2], system=evidence)
    result, sent, reserved = _route(monkeypatch, llm_request)
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"


def test_shape_registry_is_immutable():
    from packages.llm_router.input_contracts import _SHAPES
    with pytest.raises(TypeError):
        _SHAPES["new_v1"] = _SHAPES["claim_review_v1"]
    with pytest.raises(AttributeError):
        _SHAPES["claim_review_v1"].fields = ()


@pytest.mark.parametrize("long_sample", [False, True])
def test_actual_ai_builder_sampling_contracts_are_valid(monkeypatch, long_sample):
    from packages.common.schemas import Block, NormalizedDocument, Page
    from packages.verification_engine import ai_document_detector as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(authorship_max_chars=120))
    text = "계약 검토 자료. " * (30 if long_sample else 3)
    doc = NormalizedDocument("synthetic-contract", "synthetic.txt", "text/plain", "synthetic-hash",
                             pages=[Page(1, blocks=[Block("b1", text, 1)])])
    requests = []

    class Capture:
        def has_available_provider(self, **kwargs):
            return True

        async def consult_all(self, role, llm_request, **kwargs):
            requests.append(llm_request)
            return []

    asyncio.run(module.detect_ai_document(doc, [], router=Capture()))
    assert len(requests) == 1
    llm_request = requests[0]
    assert llm_request.input_contract == "ai_document_v1"
    assert valid_input_contract(llm_request)
    mode = json.loads(llm_request.user)["document_coverage"]["sampling_mode"]
    assert mode == ("head_middle_tail" if long_sample else "full_text")
    _, sent, _ = _route(monkeypatch, llm_request)
    assert len(sent) == 1


@pytest.mark.parametrize("reference_date", ["2024-05-04", None, "invalid-date"])
@pytest.mark.parametrize("profile", [False, True])
def test_actual_rag_and_claim_builders_preserve_profile_context(reference_date, profile):
    from korean_law_profile.test_review_path import inputs, make_router, pii_engine
    from packages.rag_engine.review import KOREAN_RAG_REVIEW_SYSTEM_PROMPT, review_document
    router, providers = make_router(profile, ("anthropic",))
    result, library, context = inputs()
    context.case_date = reference_date
    review_document(result, library, router, context, pii_engine())
    requests = providers["anthropic"].requests
    assert [llm_request.input_contract for llm_request in requests] == ["reference_review_v1", "claim_review_v1"]
    for llm_request in requests:
        original_system = KOREAN_RAG_REVIEW_SYSTEM_PROMPT if profile else RAG_REVIEW_SYSTEM_PROMPT
        assert valid_input_contract(llm_request, original_system=original_system)


def test_actual_argument_batch_and_retry_builders_keep_contract(monkeypatch):
    from packages.legal_engine.argument_validity_verifier import _attach_ai_opinions, _retry_truncated_singly
    captured = []

    class Capture:
        async def consult_all(self, role, llm_request, **kwargs):
            captured.append(llm_request)
            return []

        async def run(self, role, llm_request, **kwargs):
            captured.append(llm_request)
            return SimpleNamespace(used=False, executions=[])

    items = [{"citation": SimpleNamespace(page=1, raw_text="합성 인용 검토 자료"),
              "context": "계약 검토 자료", "quote_diff": "원문 대조 자료"} for _ in range(3)]
    asyncio.run(_attach_ai_opinions(SimpleNamespace(rows=[]), items, Capture(), None, None))
    batch = json.loads(captured[0].user)["items"]
    truncated = SimpleNamespace(used=False, executions=[SimpleNamespace(provider="anthropic", error="OUTPUT_TRUNCATED")])
    asyncio.run(_retry_truncated_singly(Capture(), [truncated], batch, None))
    assert [len(json.loads(llm_request.user)["items"]) for llm_request in captured] == [2, 1, 1, 1]
    for llm_request in captured:
        assert llm_request.input_contract == "argument_review_v1"
        assert valid_input_contract(llm_request)
        _, sent, _ = _route(monkeypatch, llm_request)
        assert len(sent) == 1
