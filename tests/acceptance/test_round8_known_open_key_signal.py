"""[평가 에이전트 소관] TK-55 3절 — 이름 접미가 없는 역할 명사 키 아래의 실명(알려진 미해결, strict xfail).

사용자 결정(2026-10-04 '좁게 + 스키마 고정'): 키 의미를 추측하는 방식을 더 넓히지 않는다. 키 신호가 없는 유형은
알려진 미해결로 고정하고, F1/F3 설계에서 자유 텍스트를 실을 수 있는 키의 허용 목록(스키마 고정)으로 구조적으로 막는다.
현재 앱의 LLM 요청 키는 코드가 정한 고정 이름이라 지금 경로에서는 이런 키가 생기지 않는다.

751fb50에서 모두 공급자에 도달한다(유출). 해소되면 strict XPASS로 알려지고, 평가 측이 표시를 지운다.
실제 `LLMRouter.run`에 가짜 공급자만 붙이고 외부 네트워크는 쓰지 않는다. 입력은 평가 측 비공개 점검과 다른 키·이름이다.
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

NAMES = ["도하람", "채윤오"]
ROLE_NOUN_KEYS = ["수강생", "세입자", "민원인", "tenant", "student", "requester"]


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


POSITIONS = {
    "user": lambda k, n: dict(system="s", user=json.dumps({k: n}, ensure_ascii=False)),
    "system": lambda k, n: dict(system=json.dumps({k: n}, ensure_ascii=False), user="u"),
}


@pytest.mark.xfail(strict=True, reason="TK-55 3절 알려진 미해결: 키 신호 없는 역할 명사 키(F1/F3 스키마 고정으로 해결)")
@pytest.mark.parametrize("position", sorted(POSITIONS))
@pytest.mark.parametrize("key", ROLE_NOUN_KEYS)
@pytest.mark.parametrize("name", NAMES)
def test_role_noun_key_name_is_not_sent(monkeypatch, name, key, position):
    sent = _route(monkeypatch, **POSITIONS[position](key, name))
    assert not any(name in payload for payload in sent)
