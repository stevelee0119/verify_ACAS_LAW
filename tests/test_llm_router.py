

def test_anthropic_retries_without_temperature_when_the_model_rejects_it():
    """일부 모델은 temperature를 받지 않는다.

    실제 배포에서 이 한 가지 때문에 Anthropic 호출이 전부 HTTP 400으로 실패했고,
    검증은 그동안 규칙 기반으로만 돌았다. 모델 목록을 코드에 새기는 대신,
    거절당하면 그 사실을 기억해 다음부터 빼고 보낸다.
    """
    import asyncio

    import httpx

    from packages.common.config import ProviderConfig
    from packages.llm_router.providers import AnthropicProvider, LLMRequest

    sent = []

    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, *, headers=None, json=None):
            sent.append(json)
            if "temperature" in json:
                return httpx.Response(400, json={"error": {
                    "message": "`temperature` is deprecated for this model."}})
            return httpx.Response(200, json={
                "content": [{"text": "{}"}], "usage": {"input_tokens": 1, "output_tokens": 1}})

    import os

    from packages.common import config

    previous = (os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("LV_ALLOW_NETWORK"))
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["LV_ALLOW_NETWORK"] = "1"
    config.reset_settings()
    provider = AnthropicProvider(ProviderConfig(
        name="anthropic", enabled=True, api_key_env="ANTHROPIC_API_KEY",
        model="claude-sonnet-5", base_url="https://api.anthropic.com/v1", kind="cloud"))
    assert provider.available, "시험 전제: 키가 있어야 호출 경로로 들어간다"
    original, httpx.AsyncClient = httpx.AsyncClient, _Client
    try:
        result = asyncio.run(provider.generate(LLMRequest(system="s", user="u")))
        assert result.ok, result.error
        assert len(sent) == 2 and "temperature" in sent[0] and "temperature" not in sent[1]
        sent.clear()
        # 두 번째 호출은 처음부터 temperature 없이 보낸다.
        assert asyncio.run(provider.generate(LLMRequest(system="s", user="u"))).ok
        assert len(sent) == 1 and "temperature" not in sent[0]
    finally:
        httpx.AsyncClient = original
        AnthropicProvider._omit_temperature = False
        for name, value in zip(("ANTHROPIC_API_KEY", "LV_ALLOW_NETWORK"), previous):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_settings()


def test_semantic_review_says_when_the_model_never_ran():
    """모델이 실행되지 않은 것을 "근거 미확인"으로 적으면 안 된다.

    공급자 키·모델 ID가 잘못되어 AI가 아무 일도 하지 않는 동안에도
    "검토했으나 채택하지 않았다"로 읽혔다. 실제로 세 공급자가 모두 실패하는
    동안 그렇게 기록되고 있었다.
    """
    from packages.verification_engine.pipeline import VerificationPipeline

    # 자격증명 조각은 결과에 남기지 않는다(보고서로 나간다).
    leaked = 'HTTP 401: Incorrect API key provided: sk-proj-abcdefghijklmnopqrstuvwxyz012345'
    cleaned = VerificationPipeline._provider_reason(leaked)
    assert "sk-proj-abcdefghij" not in cleaned and "[REDACTED]" in cleaned
    assert "HTTP 401" in cleaned, "원인 자체는 남아야 조치할 수 있다"
    assert VerificationPipeline._provider_reason("") == "사유 미기재"


def test_anthropic_is_the_primary_reasoner_and_is_reachable():
    """Anthropic이 주 분석 역할이다. 그 경로가 끊기면 검토의 본체가 사라진다.

    모델 ID는 공급자 사정으로 바뀌므로 값 자체를 고정하지는 않는다. 다만
    비어 있거나 역할 배정에서 빠지면 AI 검토가 통째로 다른 공급자에게
    넘어가거나 아예 수행되지 않는다.
    """
    import json
    import os
    from pathlib import Path

    from packages.common import config
    from packages.common.enums import LLMRole
    from packages.llm_router.router import ROLE_PREFERENCE, LLMRouter

    assert ROLE_PREFERENCE[LLMRole.PRIMARY_REASONER][0] == "anthropic"
    assert ROLE_PREFERENCE[LLMRole.JUDGE][0] == "anthropic"

    providers = json.loads(Path("config/providers.json").read_text(encoding="utf-8"))
    assert providers["anthropic"]["enabled"] is True
    assert providers["anthropic"]["model"].strip(), "모델이 비어 있으면 호출이 성립하지 않는다"
    assert providers["anthropic"]["api_key_env"] == "ANTHROPIC_API_KEY"

    previous = (os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("LV_ALLOW_NETWORK"))
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["LV_ALLOW_NETWORK"] = "1"
    config.reset_settings()
    try:
        picked = LLMRouter().pick(LLMRole.PRIMARY_REASONER)
        assert picked is not None and picked.name == "anthropic", \
            "키가 있는데도 Anthropic이 선택되지 않으면 주 분석이 대체 공급자로 넘어간다"
    finally:
        for name, value in zip(("ANTHROPIC_API_KEY", "LV_ALLOW_NETWORK"), previous):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_settings()


def _fake_router(monkeypatch, answers):
    """공급자 셋을 흉내내어 캐스케이드가 몇 곳을 거치는지 본다."""
    import asyncio
    from dataclasses import dataclass

    from packages.llm_router import router as module

    used = []

    @dataclass
    class _Exec:
        provider: str

    class _Result:
        def __init__(self, name, verdict):
            self.used, self.note, self.text = True, "", ""
            self.parsed = verdict
            self.executions = [_Exec(provider=name)]

    order = ["anthropic", "openai", "gemini"]

    async def fake_run(self, role, request, *, policy=None, exclude=None, expected_task=""):
        remaining = [n for n in order if n not in (exclude or [])]
        if not remaining:
            class _Empty:
                used, note, text, parsed, executions = False, "남은 공급자 없음", "", {}, []
            return _Empty()
        name = remaining[0]
        used.append(name)
        return _Result(name, answers.get(name, {"status": "VERIFIED", "confidence": 0.95}))

    monkeypatch.setattr(module.LLMRouter, "run", fake_run)
    return module, used, asyncio


def test_cross_check_all_uses_every_available_provider(monkeypatch):
    """한 모델 의견만으로 법률 판단을 뒷받침하지 않는다.

    예전에는 1차 신뢰도가 높으면 거기서 끝났고(SINGLE_MODEL_OPINION),
    제3 모델은 DEEP_VERIFY이면서 의견이 갈릴 때만 돌았다.
    """
    module, used, asyncio = _fake_router(monkeypatch, {})
    router = module.LLMRouter()
    router.settings.llm_cross_check = "all"
    outcome = asyncio.run(router.cascade(question="q", evidence={"a": 1}))
    assert used == ["anthropic", "openai", "gemini"], used
    assert outcome.winning_source == "MULTIPLE_MODEL_AGREEMENT"


def test_cross_check_off_keeps_a_single_opinion(monkeypatch):
    module, used, asyncio = _fake_router(monkeypatch, {})
    router = module.LLMRouter()
    router.settings.llm_cross_check = "off"
    outcome = asyncio.run(router.cascade(question="q", evidence={"a": 1}))
    assert used == ["anthropic"], used
    assert outcome.winning_source == "SINGLE_MODEL_OPINION"


def test_a_third_model_disagreeing_is_not_treated_as_agreement(monkeypatch):
    """1차·2차만 비교하면 제3 모델이 다른 답을 내도 합의로 처리된다."""
    module, used, asyncio = _fake_router(monkeypatch, {
        "anthropic": {"status": "VERIFIED", "confidence": 0.95},
        "openai": {"status": "VERIFIED", "confidence": 0.95},
        "gemini": {"status": "CONTRADICTED", "confidence": 0.9},
    })
    router = module.LLMRouter()
    router.settings.llm_cross_check = "all"
    outcome = asyncio.run(router.cascade(question="q", evidence={"a": 1}))
    assert used == ["anthropic", "openai", "gemini"]
    assert outcome.disagreement is True
    assert str(outcome.status) == "UNVERIFIED", "엇갈리면 다수결로 정하지 않는다"


def test_a_failing_provider_falls_through_to_the_next(monkeypatch):
    """공급자 하나의 장애로 AI 검토를 통째로 포기하지 않는다.

    실제 배포에서 Anthropic 키가 없고 OpenAI 잔액이 없자, Gemini가 멀쩡한데도
    캐스케이드가 2단계에서 끝나 검토가 수행되지 않았다.
    """
    import asyncio
    from dataclasses import dataclass

    from packages.llm_router import router as module

    called = []

    @dataclass
    class _Exec:
        provider: str

    class _Res:
        def __init__(self, name, ok):
            self.used = ok
            self.note = "" if ok else f"{name} 호출 실패"
            self.text, self.parsed = "", {"status": "VERIFIED", "confidence": 0.95} if ok else {}
            self.executions = [_Exec(provider=name)]

    order = ["anthropic", "openai", "gemini"]
    healthy = {"gemini"}

    async def fake_run(self, role, request, *, policy=None, exclude=None, expected_task=""):
        remaining = [n for n in order if n not in (exclude or [])]
        if not remaining:
            class _Empty:
                used, note, text, parsed, executions = False, "남은 공급자 없음", "", {}, []
            return _Empty()
        name = remaining[0]
        called.append(name)
        return _Res(name, name in healthy)

    monkeypatch.setattr(module.LLMRouter, "run", fake_run)
    router = module.LLMRouter()
    router.settings.llm_cross_check = "off"      # 1단계만 보면 충분하다
    outcome = asyncio.run(router.cascade(question="q", evidence={"a": 1}))

    assert called == ["anthropic", "openai", "gemini"], called
    assert str(outcome.status) != "UNVERIFIED", "멀쩡한 공급자가 있으면 검토가 수행되어야 한다"
    assert outcome.winning_source == "SINGLE_MODEL_OPINION"


def test_all_providers_failing_still_reports_why(monkeypatch):
    import asyncio

    from packages.llm_router import router as module

    async def fake_run(self, role, request, *, policy=None, exclude=None, expected_task=""):
        class _Empty:
            used, note, text, parsed, executions = False, "사용 가능한 Provider가 없어 이 단계는 수행하지 않았다.", "", {}, []
        return _Empty()

    monkeypatch.setattr(module.LLMRouter, "run", fake_run)
    outcome = asyncio.run(module.LLMRouter().cascade(question="q", evidence={"a": 1}))
    assert str(outcome.status) == "UNVERIFIED"
    assert outcome.rationale, "왜 수행하지 못했는지 남아야 한다"
