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
    with transport.source_lookup_session(120, max_attempts=1):
        responses = [adapter.search_case(f"2024다{index + 100}") for index in range(46)]
    assert len(requests) == 2
    assert all(response.status == AdapterStatus.TIMEOUT for response in responses)
    assert all("sensitive-url" not in response.message for response in responses)
    assert "반복 장애" in responses[-1].message
    with transport.source_lookup_session(120, max_attempts=1):
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
    with transport.source_lookup_session(120, max_attempts=1):
        for _ in range(attempts):
            if status in (429, 503):
                with pytest.raises(transport.SourceRequestStopped):
                    transport.source_get("bad", "https://bad.test/")
            else:
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


@pytest.mark.parametrize("failure", ["timeout", "connection", 408, 429, 500, 503])
def test_transient_error_is_retried_and_success_is_cached(monkeypatch, failure):
    requests, messages = [], []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("SECRET_URL", request=request)
            if failure == "connection":
                raise httpx.ConnectError("SECRET_URL", request=request)
            return httpx.Response(failure, json={})
        return httpx.Response(200, json={"evidence": "official"})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0, notify=messages.append):
        with transport.source_lookup_trace() as trace:
            response = transport.source_get("law", "https://source.test/", params={"OC": "SECRET"})
            assert transport.source_get("law", "https://source.test/", params={"OC": "SECRET"}) is response
        assert not trace.retryable
        assert trace.summary()["http_attempts"] == 2
        assert trace.summary()["cache_hits"] == 1
    assert len(requests) == 2
    assert any("2/3" in message for message in messages)
    assert "SECRET" not in str(trace.summary()) + str(messages)


def test_retry_deadline_increases_but_remains_bounded(monkeypatch):
    timeouts = []
    async def fetch(url, *, timeout, **kwargs):
        timeouts.append(timeout)
        if len(timeouts) < 3:
            raise httpx.ReadTimeout("test")
        return httpx.Response(200, json={})
    monkeypatch.setattr(transport, "_fetch_with_deadline", fetch)
    with transport.source_lookup_session(120, retry_backoff=0):
        transport.source_get("law", "https://source.test/", timeout=12)
    assert timeouts == [12, 24, 36]


def test_retry_after_cannot_be_bypassed_by_recovery_or_next_document(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(10, retry_backoff=0):
        with pytest.raises(transport.SourceRequestStopped):
            transport.source_get("law", "https://source.test/")
        with transport.source_recovery():
            with pytest.raises(transport.SourceRequestStopped):
                transport.source_get("law", "https://source.test/")
        transport.prepare_source_document(1)
        with pytest.raises(transport.SourceRequestStopped):
            transport.source_get("law", "https://source.test/next")
    assert len(requests) == 1


def test_retry_after_wait_is_respected_and_recovery_reserve_is_once(monkeypatch):
    waits, requests = [], []
    monkeypatch.setattr(transport, "_wait", lambda session, delay: waits.append(delay))
    def handler(request):
        requests.append(request)
        return httpx.Response(503, headers={"Retry-After": "2"}) if len(requests) == 1 else httpx.Response(200)
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, retry_backoff=0) as session:
        assert transport.source_get("law", "https://source.test/").is_success
        assert not session.blocked
        with transport.source_recovery():
            assert session.budget_seconds == 240
        with transport.source_recovery():
            assert session.budget_seconds == 240
    assert waits == [2]


def test_document_allowance_resets_without_discarding_acquired_evidence(monkeypatch):
    install_mock(monkeypatch, lambda request: httpx.Response(200, json={}))
    with transport.source_lookup_session(120) as session:
        transport.prepare_source_document(2)
        original = transport.source_get("law", "https://source.test/")
        session.spent_seconds = session.budget_seconds
        transport.prepare_source_document(10)
        assert session.budget_seconds == 300 and session.spent_seconds == 0
        assert transport.source_get("law", "https://source.test/") is original
        transport.prepare_source_document(10000)
        assert session.budget_seconds == 900


def test_cancel_interrupts_retry_wait(monkeypatch):
    from apps.api.job_control import JobOwnershipLost
    stopped, requests = [False], []
    def check():
        if stopped[0]:
            raise JobOwnershipLost("cancelled")
    def handler(request):
        requests.append(request)
        stopped[0] = True
        raise httpx.ReadTimeout("test", request=request)
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, check=check):
        with pytest.raises(JobOwnershipLost):
            transport.source_get("law", "https://source.test/")
    assert len(requests) == 1


def test_cancel_interrupts_inflight_request_and_closes_stream(monkeypatch):
    from apps.api.job_control import JobOwnershipLost
    stopped = [False]
    class Hanging(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            stopped[0] = True
            await asyncio.sleep(60)
            yield b"test"
        async def aclose(self):
            self.closed = True
    def check():
        if stopped[0]:
            raise JobOwnershipLost("cancelled")
    stream = Hanging()
    install_mock(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    started = time.monotonic()
    with transport.source_lookup_session(120, check=check):
        with pytest.raises(JobOwnershipLost):
            transport.source_get("law", "https://source.test/", timeout=45)
    assert stream.closed and time.monotonic() - started < 5


def test_hanging_response_is_cancelled_before_retry(monkeypatch):
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            await asyncio.sleep(60)
        return httpx.Response(200, json={"evidence": "test"})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(1, retry_backoff=0):
        assert transport.source_get("law", "https://source.test/", timeout=0.05).is_success
    assert len(calls) == 2


def test_circuit_can_recover_without_a_new_run(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) <= 2:
            raise httpx.ReadTimeout("test")
        return httpx.Response(200, json={})
    install_mock(monkeypatch, handler)
    with transport.source_lookup_session(120, max_attempts=1) as session:
        for i in range(2):
            with pytest.raises(transport.SourceRequestStopped):
                transport.source_get("law", f"https://source.test/{i}")
        assert session.blocked
        session.blocked_until["law"] = time.monotonic() - 1
        assert transport.source_get("law", "https://source.test/0").is_success
        assert not session.blocked


def test_cancel_during_backoff_does_not_wait_for_delay():
    from apps.api.job_control import JobOwnershipLost
    checks = []
    def check():
        checks.append(True)
        if len(checks) == 2:
            raise JobOwnershipLost("cancelled")
    with transport.source_lookup_session(120, check=check) as session:
        started = time.monotonic()
        with pytest.raises(JobOwnershipLost):
            transport._wait(session, 30)
        assert time.monotonic() - started < 2


def test_retry_after_http_date_and_invalid_values():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60), usegmt=True)
    assert 58 < transport._retry_after(httpx.Response(503, headers={"Retry-After": date})) <= 60
    for value in ("", "bad", "NaN", "Infinity", "-1"):
        assert transport._retry_after(httpx.Response(503, headers={"Retry-After": value})) == 0


def test_session_uses_frozen_request_timeout(monkeypatch):
    timeouts = []
    async def fetch(url, *, timeout, **kwargs):
        timeouts.append(timeout)
        return httpx.Response(200)
    monkeypatch.setattr(transport, "_fetch_with_deadline", fetch)
    with transport.source_lookup_session(120, request_timeout=6):
        transport.source_get("law", "https://source.test/", timeout=12)
    assert timeouts == [6]
