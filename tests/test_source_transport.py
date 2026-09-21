"""Source outages must finish as UNVERIFIED, not stall a verification run."""
import asyncio
from dataclasses import replace
import time

import httpx
import pytest

from packages.common.enums import AdapterStatus
from packages.source_adapters import transport


def install_mock(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def test_http_cache_is_run_local_and_keeps_parameter_boundaries(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"version": request.url.params["MST"]})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120) as scope:
        first = transport.source_get("law", "https://source.test/body", params={"MST": "1", "OC": "secret"})
        again = transport.source_get("law", "https://source.test/body", params={"OC": "secret", "MST": "1"})
        other = transport.source_get("law", "https://source.test/body", params={"MST": "2", "OC": "secret"})
        assert again is first and other.json() != first.json()
        assert len(requests) == 2
        assert all("secret" not in key for key in scope.cache)
    assert not scope.cache and scope.cache_bytes == 0
    with transport.source_lookup_session(120):
        transport.source_get("law", "https://source.test/body", params={"MST": "1", "OC": "secret"})
    assert len(requests) == 3


def test_consecutive_timeouts_stop_requests_but_next_run_can_retry(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("sensitive-url-must-not-leak", request=request)
    install_mock(monkeypatch, handler)
    from packages.source_adapters.law_go_kr import LawGoKrAdapter
    from packages.source_adapters.local_mirror import LocalLegalMirror
    adapter = LawGoKrAdapter(mirror=LocalLegalMirror(root="/no-mirror"))
    adapter.settings = replace(adapter.settings, allow_network=True, law_go_kr_oc="test-only")
    with transport.source_lookup_session(120):
        responses = [adapter.search_case(f"2024다{index + 100}") for index in range(46)]
    assert len(requests) == 2
    assert all(response.status == AdapterStatus.TIMEOUT for response in responses)
    assert all("sensitive-url" not in response.message for response in responses)
    assert "반복 장애" in responses[-1].message
    with transport.source_lookup_session(120):
        adapter.search_case("2024다100")
    assert len(requests) == 3


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_http_failures_trip_circuit_without_hiding_successful_sources(monkeypatch, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status if request.url.host == "bad.test" else 200, json={})
    install_mock(monkeypatch, handler)
    attempts = 2 if status == 503 else 1
    with transport.source_lookup_session(120):
        for _ in range(attempts):
            transport.source_get("bad", "https://bad.test/")
        with pytest.raises(transport.SourceRequestStopped):
            transport.source_get("bad", "https://bad.test/another")
        assert transport.source_get("good", "https://good.test/").is_success
    assert len(requests) == attempts + 1


def test_total_budget_is_shared_across_sources_and_caps_next_request(monkeypatch):
    now = [0.0]
    timeouts = []
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    async def fetch(url, *, timeout, **kwargs):
        timeouts.append(timeout)
        now[0] += timeout
        return httpx.Response(200, json={}, request=httpx.Request("GET", url))
    monkeypatch.setattr(transport, "_fetch_with_deadline", fetch)
    with transport.source_lookup_session(1):
        transport.source_get("one", "https://source.test/one", timeout=0.6)
        transport.source_get("two", "https://source.test/two", timeout=0.6)
        with pytest.raises(transport.SourceRequestStopped, match="시간 한도"):
            transport.source_get("three", "https://source.test/three")
        # Previously acquired evidence remains usable after the outbound budget is exhausted.
        assert transport.source_get("one", "https://source.test/one").is_success
    assert timeouts == pytest.approx([0.6, 0.4])


def test_wall_clock_timeout_cancels_slow_response_body_and_closes_stream(monkeypatch):
    class Trickle(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b"x"
        async def aclose(self):
            self.closed = True
    stream = Trickle()
    install_mock(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    started = time.monotonic()
    with pytest.raises(transport.SourceRequestStopped):
        transport.source_get("law", "https://source.test/", timeout=0.06)
    assert time.monotonic() - started < 2
    assert stream.closed


def test_oversized_response_is_rejected_and_cache_size_is_bounded(monkeypatch):
    monkeypatch.setattr(transport, "MAX_RESPONSE_BYTES", 20)
    monkeypatch.setattr(transport, "MAX_CACHE_BYTES", 16)
    install_mock(monkeypatch, lambda request: httpx.Response(200, content=b"x" * int(request.url.path[1:])))
    with transport.source_lookup_session(120) as scope:
        for size in (8, 9, 10):
            transport.source_get("law", f"https://source.test/{size}")
        assert scope.cache_bytes <= 16 and len(scope.cache) == 1
        with pytest.raises(transport.SourceRequestStopped, match="크기 한도"):
            transport.source_get("law", "https://source.test/21")


def test_cancel_check_runs_even_for_cached_responses(monkeypatch):
    from apps.api.job_control import JobOwnershipLost
    stopped = [False]
    def check():
        if stopped[0]:
            raise JobOwnershipLost("cancelled")
    install_mock(monkeypatch, lambda request: httpx.Response(200, json={}))
    with transport.source_lookup_session(120, check=check):
        transport.source_get("law", "https://source.test/")
        stopped[0] = True
        with pytest.raises(JobOwnershipLost):
            transport.source_get("law", "https://source.test/")
