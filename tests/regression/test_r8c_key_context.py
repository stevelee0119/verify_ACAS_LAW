"""8C regression coverage for normalized person-name keys and value-gated context."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse


def _inspect_user_payload(payload):
    request = LLMRequest(system="검토 요청", user=json.dumps(payload, ensure_ascii=False))
    return privacy.inspect_request(request)


@pytest.mark.parametrize(
    "key,value",
    [
        ("피고인 추가 정보", "한지율"),
        ("신청인 성명", "도유찬"),
        ("원 고 (대리인 이름)", "임서후"),
        ("담당자명", "선우아린"),
        ("plaintiffName", "권시온"),
        ("full_name", "김라온"),
        ("name", "류가은"),
        ("대표자 (성 명)", "한지율 (변호사)"),
        ("증인 이름", "도유찬 씨"),
    ],
)
def test_normalized_person_name_keys_block_unmasked_names(key, value):
    result = _inspect_user_payload({key: value})
    assert result["status"] == "BLOCKED", key
    assert result["failure_code"] == "PII_INPUT_BLOCKED"


@pytest.mark.parametrize("key", ["사건명", "법원명", "회사명", "기관 이름"])
def test_non_person_name_keys_do_not_add_person_context(key):
    value = "한지율"
    collected = privacy._collect_texts_from_value({key: value})
    assert (key, f"{key}: {value}") not in collected
    assert _inspect_user_payload({key: value})["status"] == "PASSED"


@pytest.mark.parametrize("key,value", [("피고", "광장시장"), ("담당자", "업무총괄")])
def test_non_name_shaped_place_and_job_values_get_no_name_context(key, value):
    collected = privacy._collect_texts_from_value({key: value})
    assert (key, value) in collected
    assert all(text != f"{key}: {value}" for _, text in collected)
    assert _inspect_user_payload({key: value})["status"] == "PASSED"


@pytest.mark.parametrize("value", ["새봄기술 법인", "세종특별자치시", "국립해양연구원"])
def test_corporate_and_institution_values_are_not_given_name_context(value):
    key = "피고인"
    collected = privacy._collect_texts_from_value({key: value})
    assert (key, value) in collected
    assert all(text != f"{key}: {value}" for _, text in collected)
    assert _inspect_user_payload({key: value})["status"] == "PASSED"


@pytest.mark.parametrize(
    "payload",
    [
        {"역할": "원고", "참여자": "강민재"},
        ["증인", "차예린"],
    ],
)
def test_sibling_and_array_name_context_remains_blocked(payload):
    assert _inspect_user_payload(payload)["status"] == "BLOCKED"


def test_key_classifier_exception_blocks_before_provider_send(monkeypatch):
    monkeypatch.setattr(privacy, "_person_label_for_key", lambda key: (_ for _ in ()).throw(RuntimeError("inspection error")))
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))
    sent = []

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="unused")

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id="reservation", amount=Decimal("0.01")),
        dispatch=lambda *args, **kwargs: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    request = LLMRequest(system="검토", user=json.dumps({"피고": "강민재"}, ensure_ascii=False))

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert sent == []
