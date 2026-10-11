"""Synthetic boundary coverage; international kinds remain outside this fix."""
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
from packages.pii_engine.engine import PIIEngine


INTERNATIONAL_NUMBERS = [
    "(+82)10-2468-1357",
    "(+44)20-3579-2468",
    "(+1)212-468-3579",
    "(＋８２)０１０－５７９２－４６８１",
    "+82(010)6813-5792",
    "( +49 ) 30-7924-6813",
]


def _route(monkeypatch, request):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent = []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="synthetic", enabled=True)

        async def generate(self, assembled):
            sent.append(assembled)
            return LLMResponse(True, text="확인", provider=self.name, model=self.config.model)

    ledger = SimpleNamespace(
        reserve=lambda *a, **k: SimpleNamespace(id="synthetic", amount=Decimal("0.01")),
        dispatch=lambda *a, **k: None,
        settle=lambda *a, **k: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger)
    return asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request)), sent


@pytest.mark.parametrize("number", INTERNATIONAL_NUMBERS)
def test_complete_international_span_maps_and_masks_without_kind_change(monkeypatch, number):
    text = "연락 " + number + " 확인"
    matches = detector.detect(text)
    assert len(matches) == 1
    match = matches[0]
    assert text[match.start:match.end] == number
    engine = PIIEngine(SimpleNamespace(pseudonym_for=lambda kind, raw: "MASKED"))
    assert engine._mask_matches(text, matches).masked_text == "연락 [MASKED] 확인"
    monkeypatch.setattr(detector, "_extend_international_prefix_spans", lambda *a: None)
    baseline = detector.detect(text)
    assert [(m.kind, m.confidence, m.end) for m in matches] == [
        (m.kind, m.confidence, m.end) for m in baseline
    ]


@pytest.mark.parametrize("number", INTERNATIONAL_NUMBERS)
@pytest.mark.parametrize("position", ["user", "system", "structured_user", "structured_system"])
def test_international_identifiers_block_actual_assembled_router(monkeypatch, number, position):
    value = json.dumps({"details": number}, ensure_ascii=False) if position.startswith("structured") else number
    request = (LLMRequest(system=value, user="확인") if position.endswith("system")
               else LLMRequest(system="일반 검토", user=value))
    result, sent = _route(monkeypatch, request)
    assert sent == []
    assert result.executions[0].input_privacy["status"] == "BLOCKED"


@pytest.mark.parametrize("prefix", [
    "(+82) 설명 ",
    "(+44)\n",
    "(+1 ",
    "(82) ",
    "(+82) 7 ",
    "(+82)( ",
])
def test_unattached_or_unbalanced_prefix_stays_outside_subscriber_mask(monkeypatch, prefix):
    number = "010-8246-7135"
    text = prefix + number
    matches = detector.detect(text)
    monkeypatch.setattr(detector, "_extend_international_prefix_spans", lambda *a: None)
    baseline = detector.detect(text)
    assert matches
    assert [(m.kind, m.start, m.end) for m in matches] == [(m.kind, m.start, m.end) for m in baseline]


@pytest.mark.parametrize("text", [
    "(+82) 사업자등록번호 010-00-00000",
    "(+44) 선고일자 2098. 2. 3.",
    "(+1) 사건번호 2097가00002 검토",
    "(+49) 법인등록번호 999999-9999999",
    "(+81) 법률 제99999호",
])
def test_business_date_and_legal_controls_gain_no_numeric_detection(text):
    assert not any(m.kind in {"PHONE", "RRN", "ACCOUNT", "PII"} for m in detector.detect(text))


@pytest.mark.parametrize("text", [
    "(+44) 선고일자 2098. 2. 3.",
    "(+1) 사건번호 2097가00002 검토",
    "(+81) 법률 제99999호",
])
def test_non_pii_controls_reach_provider_with_assembled_system(monkeypatch, text):
    result, sent = _route(monkeypatch, LLMRequest(system="일반 검토", user=text))
    assert result.used
    assert len(sent) == 1
    assert router_module.SYSTEM_BASE in sent[0].system
    assert sent[0].user == text


def test_mapped_prefix_extension_cannot_cross_legal_guard():
    text = "(+82)10-2468-1357"
    match = detector.PIIMatch("ACCOUNT", text[5:], 5, len(text))
    detector._extend_international_prefix_spans(text, [match], [(0, 4)])
    assert match.start == 5


@pytest.mark.parametrize("kind", ["PHONE", "ACCOUNT", "RRN", "PII"])
def test_extension_preserves_preexisting_numeric_kind(kind):
    text = "(+82)10-2468-1357"
    match = detector.PIIMatch(kind, text[5:], 5, len(text), confidence=0.8)
    detector._extend_international_prefix_spans(text, [match], [])
    assert (match.kind, match.confidence, match.text) == (kind, 0.8, text)
