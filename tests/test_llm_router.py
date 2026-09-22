

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
