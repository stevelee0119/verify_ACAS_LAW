"""Regression coverage for normalized phone and resident-number detection."""
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


CONTACT_RRN_VARIANTS = [
    pytest.param("연락처: ０１０ - ００００ - ００００", "０１０ - ００００ - ００００", "PHONE", id="fullwidth-and-spaced"),
    pytest.param("전화: (010)\u202f0000—0001", "(010)\u202f0000—0001", "PHONE", id="parenthetical-and-dash"),
    pytest.param("전화 010\n0000\t0002", "010\n0000\t0002", "PHONE", id="line-break-and-tabs"),
    pytest.param("연락 ０２·００００·０００３", "０２·００００·０００３", "PHONE", id="unicode-separators"),
    pytest.param("주민번호：００００００－１００００００", "００００００－１００００００", "RRN", id="fullwidth-rrn"),
    pytest.param("주민등록번호 000000\u00a0–\n1 000 000", "000000\u00a0–\n1 000 000", "RRN", id="rrn-whitespace-and-line-break"),
    pytest.param("식별번호 000000·1·000·000", "000000·1·000·000", "RRN", id="rrn-other-symbols"),
]


FALSE_POSITIVE_CONTROLS = [
    "사건번호 2099가00001 검토",
    "선고일자 2099. 1. 1.",
    "청구 금액은 1,000,000원이다.",
    "사업자등록번호 010-00-00000",
    "법인등록번호 999999-9999999",
    "법률 제99999호에 따른다.",
]
TRANSMIT_CONTROLS = [text for text in FALSE_POSITIVE_CONTROLS if not text.startswith("사업자등록번호")]


def _fake_router(monkeypatch, sent):
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


@pytest.mark.parametrize(("text", "expected", "kind"), CONTACT_RRN_VARIANTS)
def test_contact_and_rrn_spans_map_back_to_original_characters(text, expected, kind):
    match = next(match for match in detector.detect(text) if match.kind == kind)

    assert text[match.start:match.end] == expected
    engine = PIIEngine(SimpleNamespace(pseudonym_for=lambda match_kind, value: f"MASKED_{match_kind}"))
    masked = engine._mask_matches(text, [match]).masked_text
    assert masked == text[:match.start] + f"[MASKED_{kind}]" + text[match.end:]
    assert expected not in masked


@pytest.mark.parametrize(("text", "expected", "kind"), CONTACT_RRN_VARIANTS)
@pytest.mark.parametrize("position", ["user", "system", "structured"])
def test_contact_and_rrn_notation_variants_never_reach_provider(monkeypatch, text, expected, kind, position):
    sent = []
    router = _fake_router(monkeypatch, sent)
    value = f"등록 {text} 확인"
    if position == "user":
        request = LLMRequest(system="일반 검토", user=value)
    elif position == "system":
        request = LLMRequest(system=value, user="검토 요청")
    else:
        request = LLMRequest(system="일반 검토", user=json.dumps({"details": {"identifier": value}}, ensure_ascii=False))

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))

    assert sent == []


@pytest.mark.parametrize("text", FALSE_POSITIVE_CONTROLS)
def test_legal_and_business_number_controls_are_not_phone_or_rrn(text):
    assert all(match.kind not in {"PHONE", "RRN"} for match in detector.detect(text))


@pytest.mark.parametrize("text", TRANSMIT_CONTROLS)
def test_legal_and_business_number_controls_still_reach_provider(monkeypatch, text):
    sent = []
    router = _fake_router(monkeypatch, sent)

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(system="검토", user=text)))

    assert len(sent) == 1
