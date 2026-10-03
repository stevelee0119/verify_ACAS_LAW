"""[평가 에이전트 소관] TK-51 구조화(JSON) 요청의 개인정보 경계 — 라벨이 키, 이름이 값일 때 실명이 공급자에 도달하지 않아야 한다.

7adf43f·4da3910·b26754e·61ef12f 모두 같은 공백(기존 결함, 회귀 아님). 평문 요청 경계(R6-01·R7-12)와 별개다.
실제 `LLMRouter.run`에 가짜 공급자만 붙이고 외부 네트워크는 쓰지 않는다. 지금은 strict xfail(알려진 미해결)이며
해소되면 XPASS → 평가 측이 표시를 지운다. 입력은 평가 측 비공개 재현과 다른 이름·형식이다.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse

NAMES = ["편하람", "어진우"]
LABELS = ["원고", "담당자", "증인"]


def _route(monkeypatch, **request_kwargs):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent = []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="HTTP 400")

    ledger = SimpleNamespace(reserve=lambda *a, **k: SimpleNamespace(id="r", amount=Decimal("0.01")),
                             dispatch=lambda *a, **k: None)
    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger)
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(**request_kwargs)))
    return [json.dumps({"system": r.system, "user": r.user, "schema": r.schema}, ensure_ascii=False, default=str)
            for r in sent]


SHAPES = {
    "user-key": lambda L, n: dict(system="s", user=json.dumps({"사건": {L: n}}, ensure_ascii=False)),
    "user-pair": lambda L, n: dict(system="s", user=json.dumps({"관계인": [{"역할": L, "이름값": n}]}, ensure_ascii=False)),
    "system-key": lambda L, n: dict(system=json.dumps({L: n}, ensure_ascii=False), user="u"),
    "schema-key": lambda L, n: dict(system="s", user="u", schema={"type": "object", "default": {L: n}}),
}


@pytest.mark.xfail(strict=True, reason="TK-51 알려진 미해결: 구조화 요청에서 라벨-값 쌍의 실명이 전송 전 검사를 통과한다(7adf43f부터)")
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_structured_request_does_not_deliver_a_labelled_name(monkeypatch, shape):
    leaked = []
    for label in LABELS:
        for name in NAMES:
            bodies = _route(monkeypatch, **SHAPES[shape](label, name))
            if any(name in body for body in bodies):
                leaked.append((label, name))
    assert not leaked, f"{shape}: 실명이 공급자에 도달 {len(leaked)}/{len(LABELS) * len(NAMES)}"
