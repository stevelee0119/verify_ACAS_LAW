"""Duplicate-key JSON must retain all values for inspection, not transmission."""
from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse


NUMBERS = [
    "010-1379-2468", "02-2486-1357", "070-3591-2468",
    "760425-2345689", "790613-3456791", "820928-4567892",
]


def _duplicate_json(value, *, escape_digits=False, escape_all=False):
    encoded = json.dumps(value, ensure_ascii=False)
    if escape_all:
        encoded = '"' + ''.join("\\u%04x" % ord(char) for char in value) + '"'
    elif escape_digits:
        encoded = re.sub(r"\d", lambda m: "\\u%04x" % ord(m.group()), encoded)
    return '{"contact":' + encoded + ',"contact":"일반 기록"}'


def _form(value, form):
    duplicate = _duplicate_json(value, escape_digits=form == "escaped",
                                escape_all=form in {"fully_escaped", "quoted_fully_escaped"})
    if form in {"quoted", "quoted_fully_escaped"}:
        return json.dumps(duplicate, ensure_ascii=False)
    if form == "array":
        return '[' + duplicate + ',"일반 기록"]'
    if form == "nested":
        return '{"evidence":[' + duplicate + ']}'
    if form == "encoded":
        return json.dumps({"evidence": duplicate}, ensure_ascii=False)
    if form == "twice_encoded":
        return json.dumps({"evidence": json.dumps({"record": duplicate}, ensure_ascii=False)}, ensure_ascii=False)
    return duplicate


def _route(monkeypatch, request):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent, reserved = [], []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="synthetic", enabled=True)

        async def generate(self, assembled):
            sent.append(assembled)
            return LLMResponse(False, error="synthetic response", provider=self.name, model=self.config.model)

    def reserve(*a, **k):
        reserved.append(True)
        return SimpleNamespace(id="synthetic", amount=Decimal("0.01"))

    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=SimpleNamespace(
        reserve=reserve, dispatch=lambda *a, **k: None))
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    return result, sent, reserved


@pytest.mark.parametrize("value", NUMBERS)
@pytest.mark.parametrize("form", ["plain", "array", "nested", "encoded", "twice_encoded", "escaped",
                                 "fully_escaped", "quoted", "quoted_fully_escaped"])
@pytest.mark.parametrize("position", ["user", "system", "structured_user", "structured_system"])
def test_every_duplicate_number_value_blocks_actual_router_before_budget(monkeypatch, value, form, position):
    text = _form(value, form)
    if position.startswith("structured"):
        text = json.dumps({"evidence": text}, ensure_ascii=False)
    request = (LLMRequest(system=text, user="일반 기록") if position.endswith("system")
               else LLMRequest(system="일반 기록", user=text))
    result, sent, reserved = _route(monkeypatch, request)
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"
    assert set(result.executions[0].input_privacy["detected_types"]) & {"PHONE", "RRN"}


@pytest.mark.parametrize("text", [
    '{"name":"국립해양연구원","name":"세종특별자치시"}',
    '{"document":{"date":"2094. 3. 6.","date":"2095. 4. 7."}}',
    '{"identifier":"법률 제99999호","identifier":"법인등록번호 999999-9999999"}',
    '{"피고":"대한민국","피고":"서울특별시"}',
    '{"자료":[{"사건명":"계약 검토 자료","사건명":"법령 검토 자료"}]}',
    '{"holder":"공공행정기관","holder":"업무총괄부서"}',
])
@pytest.mark.parametrize("position", ["user", "system", "structured_user", "structured_system"])
def test_benign_duplicate_objects_keep_payload_and_provider_compatibility(monkeypatch, text, position):
    if position.startswith("structured"):
        text = json.dumps({"evidence": text}, ensure_ascii=False)
    request = (LLMRequest(system=text, user="일반 기록") if position.endswith("system")
               else LLMRequest(system="일반 기록", user=text))
    result, sent, reserved = _route(monkeypatch, request)
    assert len(sent) == len(reserved) == 1
    assert result.executions[0].input_privacy["status"] == "PASSED"
    assert sent[0].user == request.user
    assert sent[0].system == f"{router_module.SYSTEM_BASE}\n[역할] {LLMRole.PRIMARY_REASONER}\n{request.system}"


def test_all_duplicate_occurrences_and_original_context_are_walked():
    text = '{"contact":"010-1379-2468","contact":"02-2486-1357","contact":"070-3591-2468"}'
    values = [value for path, value in privacy._walk_fields(text, "evidence") if path == "evidence.contact"]
    assert values == NUMBERS[:3]
    names = '{"plaintiff":"안시온","plaintiff":"일반 기록"}'
    result = privacy.inspect_request(LLMRequest(system="일반 기록", user=names))
    assert result["failure_code"] == "PII_INPUT_BLOCKED"


def test_duplicate_pairs_keep_sibling_label_context_without_new_labels():
    text = '{"role":"원고","value":"한가온","value":"일반 기록"}'
    result = privacy.inspect_request(LLMRequest(system="일반 기록", user=text))
    assert result["failure_code"] == "PII_INPUT_BLOCKED"


def test_unknown_role_residual_is_not_promoted_to_new_person_inference(monkeypatch):
    text = '{"registrationActor":"임하늘","registrationActor":"일반 기록"}'
    result, sent, reserved = _route(monkeypatch, LLMRequest(system="일반 기록", user=text))
    assert len(sent) == len(reserved) == 1
    assert result.executions[0].input_privacy["status"] == "PASSED"


@pytest.mark.parametrize("value", ["사업자등록번호 010-00-00000", "010-00-00000"])
def test_business_number_keeps_existing_auxiliary_kind_policy(value):
    single = privacy.inspect_request(LLMRequest(system="일반 기록", user=value))
    duplicate = privacy.inspect_request(LLMRequest(system="일반 기록", user=_duplicate_json(value)))
    assert single["status"] == duplicate["status"] == "BLOCKED"
    assert set(single["detected_types"]) == set(duplicate["detected_types"]) == {"BUSINESS_REGISTRATION"}


@pytest.mark.parametrize("value", NUMBERS)
def test_outer_contracted_duplicates_do_not_hide_pii_failure_precedence(monkeypatch, value):
    from packages.rag_engine.review import ENVELOPE_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT
    text = '{"document":' + json.dumps(value) + ',"document":"일반 기록","untrusted_references":[]}'
    request = LLMRequest(system=RAG_REVIEW_SYSTEM_PROMPT, user=text, schema=ENVELOPE_SCHEMA,
                         input_contract="reference_review_v1")
    result, sent, reserved = _route(monkeypatch, request)
    assert sent == reserved == []
    assert result.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"


@pytest.mark.parametrize("value", NUMBERS)
def test_actual_reference_review_producer_request_blocks_duplicate_text_pii_before_budget(monkeypatch, value):
    from korean_law_profile.test_review_path import inputs, make_router, pii_engine
    from packages.rag_engine.review import review_document
    router, providers = make_router(False, ("anthropic",))
    result, library, context = inputs()
    review_document(result, library, router, context, pii_engine())
    assembled = providers["anthropic"].requests[0]
    payload = json.loads(assembled.user)
    payload["document"] = _duplicate_json(value)
    from packages.rag_engine.review import RAG_REVIEW_SYSTEM_PROMPT
    from dataclasses import replace
    request = replace(assembled, system=RAG_REVIEW_SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False))
    routed, sent, reserved = _route(monkeypatch, request)
    assert request.input_contract == "reference_review_v1"
    assert sent == reserved == []
    assert routed.executions[0].input_privacy["failure_code"] == "PII_INPUT_BLOCKED"
