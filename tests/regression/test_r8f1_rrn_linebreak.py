"""Regression coverage for unlabelled RRNs split at a hyphen and line break."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine import detector


RRN_HYPHEN_LINEBREAKS = [
    pytest.param("730428-\n2345678", id="hyphen-before-break"),
    pytest.param("820911\n−3456789", id="minus-after-break"),
]

NON_RRN_LINEBREAK_CONTROLS = [
    "사건번호 2026가-\n1234 확인",
    "작성일 2034-\n07-12",
    "청구액 4,250-\n000원",
]


def _router_with_fake_provider(monkeypatch, sent):
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(True, text="확인", provider=self.name, model=self.config.model)

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id="reservation", amount=Decimal("0.01")),
        dispatch=lambda *args, **kwargs: None,
        settle=lambda *args, **kwargs: None,
    )
    return router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)


def _request_for(value, position):
    if position == "user":
        return LLMRequest(system="일반 검토", user=f"입력 {value} 확인")
    if position == "system":
        return LLMRequest(system=f"입력 {value} 확인", user="검토 요청")
    structured = json.dumps({"details": {"identifier": value}}, ensure_ascii=False)
    return LLMRequest(system="일반 검토", user=structured)


@pytest.mark.parametrize("rrn", RRN_HYPHEN_LINEBREAKS)
def test_unlabelled_rrn_with_hyphen_at_linebreak_is_detected_in_original_span(rrn):
    text = f"입력 {rrn} 확인"

    match = next(match for match in detector.detect(text) if match.kind == "RRN")

    assert text[match.start:match.end] == rrn


@pytest.mark.parametrize("rrn", RRN_HYPHEN_LINEBREAKS)
@pytest.mark.parametrize("position", ["user", "system", "structured"])
def test_unlabelled_rrn_with_hyphen_at_linebreak_never_reaches_provider(monkeypatch, rrn, position):
    sent = []
    router = _router_with_fake_provider(monkeypatch, sent)

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, _request_for(rrn, position)))

    assert sent == []


def test_unlabelled_rrn_without_separator_at_linebreak_stays_unmatched_and_transmittable(monkeypatch):
    text = "입력 910322\n5678901 확인"
    assert all(match.kind != "RRN" for match in detector.detect(text))

    sent = []
    router = _router_with_fake_provider(monkeypatch, sent)
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(system="일반 검토", user=text)))

    assert len(sent) == 1


@pytest.mark.parametrize("text", NON_RRN_LINEBREAK_CONTROLS)
def test_non_rrn_hyphen_linebreak_controls_are_not_masked_and_transmit(monkeypatch, text):
    assert all(match.kind != "RRN" for match in detector.detect(text))

    sent = []
    router = _router_with_fake_provider(monkeypatch, sent)
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(system="검토", user=text)))

    assert len(sent) == 1
