"""Evaluator synthetic lossless-JSON numeric gates; never calls a real provider."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import ExternalAIPolicy, LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse


POSITIVES = ["010-9627-4831", "010-8471-6293", "010-5738-1946",
             "850425-1647293", "920613-2146385", "790821-1346927"]
CONTROLS = ["서원 연구소", "민법 제398조", "2025. 3. 4."]
PENDING = pytest.mark.xfail(strict=True, raises=AssertionError,
                            reason="TK55 lossless duplicate JSON leaf inspection pending evaluator promotion")


def _request(value, position, escaped, nested):
    encoded = ('"' + ''.join(f"\\u{ord(char):04x}" for char in value) + '"'
               if escaped else json.dumps(value, ensure_ascii=False))
    # A normal last-value dict parse loses the mandatory numeric identifier.
    leaf = '{"contact":' + encoded + ',"contact":"일반 기록"}'
    if nested:
        leaf = json.dumps({"items": [{"note": leaf}]}, ensure_ascii=False)
    outer = json.dumps({"note": leaf}, ensure_ascii=False)
    kwargs = {"system": "synthetic system", "user": "synthetic document"}
    if position in ("system", "user"):
        kwargs[position] = outer
    elif position == "schema":
        kwargs[position] = {"type": "object", "default": {"note": leaf}}
    else:
        kwargs[position] = {"note": leaf}
    return LLMRequest(**kwargs)


def _route(monkeypatch, request):
    sent, reserved = [], []
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="synthetic", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="synthetic failure")

    def reserve(*args, **kwargs):
        reserved.append(True)
        return SimpleNamespace(id="synthetic-reservation", amount=Decimal("0.01"))

    ledger = SimpleNamespace(reserve=reserve, dispatch=lambda *a, **k: None)
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request, policy=ExternalAIPolicy.MASKED))
    return result, sent, reserved


@PENDING
@pytest.mark.parametrize("value", POSITIVES)
@pytest.mark.parametrize("position", ["system", "user", "schema", "metadata"])
@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_every_duplicate_numeric_value_is_inspected_before_budget(monkeypatch, value, position, escaped, nested):
    request = _request(value, position, escaped, nested)
    original = (request.system, request.user, json.dumps(request.schema), json.dumps(request.metadata))
    report = privacy.inspect_request(request)
    result, sent, reserved = _route(monkeypatch, request)
    assert report["status"] == "BLOCKED" and report["failure_code"] == "PII_INPUT_BLOCKED"
    assert not sent and not reserved
    assert result.executions[0].cost_status == "NOT_SENT"
    assert value not in json.dumps(report, ensure_ascii=False)
    assert original == (request.system, request.user, json.dumps(request.schema), json.dumps(request.metadata))


@pytest.mark.parametrize("value", CONTROLS)
@pytest.mark.parametrize("position", ["system", "user", "schema", "metadata"])
@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_benign_duplicate_json_remains_supported(monkeypatch, value, position, escaped, nested):
    request = _request(value, position, escaped, nested)
    assert privacy.inspect_request(request)["status"] == "PASSED"
    _, sent, reserved = _route(monkeypatch, request)
    assert len(sent) == len(reserved) == 1
