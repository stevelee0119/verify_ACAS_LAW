

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


def test_live_check_reports_every_provider_in_the_real_cascade(monkeypatch):
    """배포 점검이 공급자를 따로 부르는 데서 그치지 않고, 실제 분석 경로에서
    세 모델이 모두 참여했는지와 근거 인용이 공식 전문에 있는지를 보고한다."""
    import asyncio
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from packages.llm_router import router as module
    from packages.llm_router.router import ModelExecution

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import live_source_check

    source = "재항고를 기각한다. 원심의 판단에 법리오해의 위법이 없다."
    order = ["anthropic", "openai", "gemini"]

    async def fake_run(self, role, request, *, policy=None, exclude=None, expected_task=""):
        name = next(n for n in order if n not in (exclude or []))
        quote = "원심의 판단에 법리오해의 위법이 없다" if name != "gemini" else "지어낸 문구"
        return SimpleNamespace(used=True, note="", text="",
                               parsed={"status": "VERIFIED", "confidence": 0.9, "evidence_quotes": [quote]},
                               executions=[ModelExecution(role=str(role), provider=name, model="m", ok=True)])

    monkeypatch.setattr(module.LLMRouter, "run", fake_run)
    from packages.common.config import get_settings

    # 앞선 테스트가 공유 설정 객체를 바꿔 두므로 여기서 명시한다.
    monkeypatch.setattr(get_settings(), "llm_cross_check", "all")
    law = SimpleNamespace(
        search_case=lambda n: SimpleNamespace(status="READY", records=[{"case_number": "2011모1839", "source_id": "1"}]),
        fetch_case=lambda record: SimpleNamespace(records=[{"full_text": source}]))
    rows = asyncio.run(live_source_check.check_cascade(True, SimpleNamespace(law=law)))
    by_name = {row.name: row for row in rows}
    assert by_name["cascade:참여 공급자"].ok, by_name["cascade:참여 공급자"].detail
    assert "anthropic, gemini, openai" in by_name["cascade:참여 공급자"].detail
    assert "일치 1건" in by_name["cascade:stage2:primary"].detail
    assert "일치 0건" in by_name["cascade:stage4:grounder"].detail


def test_gemini_empty_reply_is_a_failure_with_its_reason(monkeypatch):
    """본문 없는 응답을 성공으로 넘기면 뒤에서 '응답 형식 오류'로만 남아,
    생각 토큰이 출력 한도를 다 쓴 것인지 차단된 것인지 알 수 없다."""
    import asyncio

    import httpx

    from packages.common import config
    from packages.common.config import ProviderConfig
    from packages.llm_router.providers import GeminiProvider, LLMRequest

    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, *, params=None, json=None):
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 0, "thoughtsTokenCount": 8}})

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")
    config.reset_settings()
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    try:
        provider = GeminiProvider(ProviderConfig(
            name="gemini", enabled=True, api_key_env="GEMINI_API_KEY", model="gemini-3.8-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta", kind="cloud"))
        result = asyncio.run(provider.generate(LLMRequest(system="s", user="u", max_tokens=8)))
        assert not result.ok
        assert "EMPTY_RESPONSE" in result.error and "MAX_TOKENS" in result.error and "thinking 8" in result.error
    finally:
        monkeypatch.undo()
        config.reset_settings()


def test_consult_all_asks_every_available_provider_once(monkeypatch):
    module, used, asyncio = _fake_router(monkeypatch, {})
    router = module.LLMRouter()
    monkeypatch.setattr(module.LLMRouter, "available_providers",
                        lambda self, *, policy=None: ["anthropic", "openai", "gemini"])
    results = asyncio.run(router.consult_all(module.LLMRole.PRIMARY_REASONER,
                                             module.LLMRequest(system="s", user="u")))
    assert sorted(used) == ["anthropic", "gemini", "openai"]
    assert sorted(r.executions[0].provider for r in results) == ["anthropic", "gemini", "openai"]


def test_consult_all_respects_the_cross_check_cost_switch(monkeypatch):
    module, used, asyncio = _fake_router(monkeypatch, {})
    router = module.LLMRouter()
    monkeypatch.setattr(router.settings, "llm_cross_check", "off")
    monkeypatch.setattr(module.LLMRouter, "available_providers",
                        lambda self, *, policy=None: ["gemini", "openai", "anthropic"])
    asyncio.run(router.consult_all(module.LLMRole.PRIMARY_REASONER, module.LLMRequest(system="s", user="u")))
    assert used == ["anthropic"], "off면 역할 1순위 공급자 한 곳만"


def test_transient_overload_is_retried_but_request_errors_are_not(monkeypatch):
    """Gemini가 503(high demand)으로 한 번에 탈락해 교차검증에서 빠졌다."""
    import asyncio

    from types import SimpleNamespace

    from packages.llm_router import router as module
    from packages.llm_router.providers import LLMResponse

    class _Provider:
        name = "gemini"
        available = True
        config = SimpleNamespace(kind="local", model="m", name="gemini")

        def __init__(self, replies):
            self.replies, self.calls = list(replies), 0

        async def generate(self, request):
            self.calls += 1
            return self.replies.pop(0)

    overloaded = LLMResponse(False, provider="gemini", error='HTTP 503: {"message": "high demand"}')
    fine = LLMResponse(True, provider="gemini", text='{"status": "VERIFIED", "rationale": "r"}')
    provider = _Provider([overloaded, overloaded, fine])
    router = module.LLMRouter(providers={"gemini": provider})
    router.retry_delays = (0.0, 0.0)
    result = asyncio.run(router.run(module.LLMRole.PRIMARY_REASONER, module.LLMRequest(system="s", user="u")))
    assert result.used and provider.calls == 3

    denied = _Provider([LLMResponse(False, provider="gemini", error="HTTP 401: invalid key")] * 3)
    router = module.LLMRouter(providers={"gemini": denied})
    router.retry_delays = (0.0, 0.0)
    result = asyncio.run(router.run(module.LLMRole.PRIMARY_REASONER, module.LLMRequest(system="s", user="u")))
    assert not result.used and denied.calls == 1

    still = _Provider([overloaded] * 3)
    router = module.LLMRouter(providers={"gemini": still})
    router.retry_delays = (0.0, 0.0)
    result = asyncio.run(router.run(module.LLMRole.PRIMARY_REASONER, module.LLMRequest(system="s", user="u")))
    assert module.describe_failure(result.executions[0].error) == "공급자 일시 과부하(HTTP 503) — 재시도 후에도 실패"


def test_truncated_answers_are_failures_with_a_clear_reason(monkeypatch):
    """한도에서 잘린 JSON이 '형식 오류'로만 남아 Anthropic이 빠진 이유가 가려졌다."""
    import asyncio

    import httpx

    from packages.common import config
    from packages.common.config import ProviderConfig
    from packages.llm_router.providers import AnthropicProvider, LLMRequest
    from packages.llm_router.router import describe_failure

    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, *, headers=None, json=None):
            return httpx.Response(200, json={"content": [{"text": '{"verdict": "UNCER'}],
                                             "stop_reason": "max_tokens", "usage": {"input_tokens": 9, "output_tokens": 8}})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")
    config.reset_settings()
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    try:
        provider = AnthropicProvider(ProviderConfig(name="anthropic", enabled=True, api_key_env="ANTHROPIC_API_KEY",
                                                    model="claude-sonnet-5", base_url="https://x", kind="cloud"))
        result = asyncio.run(provider.generate(LLMRequest(system="s", user="u", max_tokens=8)))
        assert not result.ok and result.error.startswith("OUTPUT_TRUNCATED")
        assert describe_failure(result.error) == "응답이 출력 한도에서 잘림"
    finally:
        monkeypatch.undo()
        config.reset_settings()
