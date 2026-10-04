"""R8-E checks for prefixed person signals and bounded name-value handling."""
from __future__ import annotations

import json
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse


def _inspect_payload(payload):
    request = LLMRequest(system="합성 검토 요청", user=json.dumps(payload, ensure_ascii=False))
    return privacy.inspect_request(request)


@pytest.mark.parametrize(
    ("key", "value", "label"),
    [
        ("기관피고", "도윤서", "피고"),
        ("행정부문Witness", "나세림", "witness"),
        ("분류기준 plaintiffName", "하연우", "plaintiff"),
    ],
)
def test_person_label_survives_a_preceding_nonperson_word(key, value, label):
    assert privacy._person_label_for_key(key) == label
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "value",
    [
        "가람들 물순환 사업본부",
        "초람군 민생지원 행정청",
        "동해안 공정관리 직무",
    ],
)
def test_multiword_nonperson_structure_under_role_label_is_not_contextualized(value):
    collected = privacy._collect_texts_from_value({"피고": value})
    assert ("피고", value) in collected
    assert all(text != f"피고: {value}" for _, text in collected)
    assert _inspect_payload({"피고": value})["status"] == "PASSED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("residentName", "문 서윤"),
        ("contactName", "차도윤과 배하린"),
        ("applicantName", "진가람 감정인"),
        ("attendeeName", "강시우 외 2명"),
        ("defendantName", "노다은께는"),
    ],
)
@pytest.mark.xfail(strict=True, reason="TK-56 알려진 미해결: 8C 수렴(사용자 결정 2026-10-04)")
def test_explicit_person_name_fields_keep_fail_closed_value_shapes(key, value):
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


def test_generic_unmarked_role_noun_remains_outside_key_inference():
    assert privacy._person_label_for_key("등록참여자") is None


@pytest.mark.parametrize(
    "position",
    [
        pytest.param("user", marks=pytest.mark.xfail(strict=True, reason="TK-56 알려진 미해결: 8C 수렴(사용자 결정 2026-10-04)")),
        pytest.param("original_system", marks=pytest.mark.xfail(strict=True, reason="TK-56 알려진 미해결: 8C 수렴(사용자 결정 2026-10-04)")),
    ],
)
def test_name_field_fail_closed_blocks_actual_router_send_in_both_positions(monkeypatch, position):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent = []

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="unused")

    ledger = SimpleNamespace(
        reserve=lambda *a, **k: SimpleNamespace(id="reservation", amount=Decimal("0.01")),
        dispatch=lambda *a, **k: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    structured_name = json.dumps({"contactName": "박 초원"}, ensure_ascii=False)
    request = (
        LLMRequest(system="합성 검토", user=structured_name)
        if position == "user"
        else LLMRequest(system=structured_name, user="일반 요청")
    )

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))

    assert sent == []
