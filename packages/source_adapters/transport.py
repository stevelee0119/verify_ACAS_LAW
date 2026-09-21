"""Run-local, bounded official-source requests. Never cache across projects or runs."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import httpx

from packages.common.enums import AdapterStatus

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_CACHE_ENTRIES = 64
FAILURE_THRESHOLD = 2


class SourceRequestStopped(httpx.RequestError):
    def __init__(self, message, status=AdapterStatus.TIMEOUT, *, retryable=None):
        super().__init__(message)
        self.status = status
        self.retryable = status == AdapterStatus.TIMEOUT if retryable is None else retryable


@dataclass
class LookupTrace:
    requests: dict = field(default_factory=dict)

    def record(self, key, adapter, attempts, status, retryable, cache_hit=False):
        prior = self.requests.get(key, {})
        self.requests[key] = {"adapter": adapter, "attempts": attempts + prior.get("attempts", 0),
                              "status": str(status), "retryable": retryable,
                              "cache_hit": int(cache_hit) + prior.get("cache_hit", 0)}

    @property
    def retryable(self):
        return any(item["retryable"] for item in self.requests.values())

    def summary(self):
        return {"http_attempts": sum(r["attempts"] for r in self.requests.values()),
                "cache_hits": sum(r["cache_hit"] for r in self.requests.values()),
                "retryable": self.retryable,
                "requests": list(self.requests.values())}


@dataclass
class LookupSession:
    budget_seconds: float
    check: Optional[Callable[[], None]] = None
    spent_seconds: float = 0.0
    failures: dict = field(default_factory=dict)
    blocked: dict = field(default_factory=dict)
    cache: OrderedDict = field(default_factory=OrderedDict)
    cache_bytes: int = 0
    max_attempts: int = 3
    request_timeout: Optional[float] = None
    retry_backoff: float = 1.0
    cooldown_seconds: float = 15.0
    notify: Optional[Callable[[str], None]] = None
    blocked_until: dict = field(default_factory=dict)
    recovery_seconds: float = 120.0
    recovery_used: bool = False
    recovering: bool = False
    recovery_probes: set = field(default_factory=set)

    def remaining(self):
        return max(0.0, self.budget_seconds - self.spent_seconds)

    def check_active(self):
        if self.check:
            self.check()

    def message(self, text):
        self.check_active()
        if self.notify:
            self.notify(text)

    def remember(self, key, response):
        size = len(response.content)
        if size > MAX_CACHE_BYTES or not 200 <= response.status_code < 300:
            return
        while self.cache and (len(self.cache) >= MAX_CACHE_ENTRIES or self.cache_bytes + size > MAX_CACHE_BYTES):
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= len(old.content)
        if key in self.cache:
            self.cache_bytes -= len(self.cache.pop(key).content)
        self.cache[key] = response
        self.cache_bytes += size


_session = ContextVar("source_lookup_session", default=None)
_trace = ContextVar("source_lookup_trace", default=None)


@contextmanager
def source_lookup_session(budget_seconds, *, check=None, notify=None, max_attempts=3,
                          retry_backoff=1.0, cooldown_seconds=15.0, request_timeout=None):
    session = LookupSession(max(0.01, float(budget_seconds)), check=check, notify=notify,
                            max_attempts=max(1, min(5, int(max_attempts))),
                            request_timeout=request_timeout,
                            retry_backoff=max(0, float(retry_backoff)),
                            cooldown_seconds=max(0, float(cooldown_seconds)))
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)
        session.cache.clear()
        session.cache_bytes = 0


def prepare_source_document(citation_count, *, base_seconds=120, max_seconds=900, recovery_seconds=120):
    """Give each document its own bounded allowance; retain only run-local evidence."""
    session = _session.get()
    if session is not None:
        session.budget_seconds = max(0.01, min(max_seconds, max(base_seconds, citation_count * 30)))
        session.spent_seconds = 0
        session.recovery_seconds = max(0, min(recovery_seconds, max_seconds))
        session.recovery_used = False
        session.recovery_probes.clear()
        # Keep authentication failures and server Retry-After across documents.
        session.failures.clear()
    return session


@contextmanager
def source_lookup_trace():
    trace = LookupTrace()
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)


@contextmanager
def source_recovery():
    session = _session.get()
    if session is None:
        yield False
        return
    if not session.recovery_used:
        session.budget_seconds += session.recovery_seconds
        session.recovery_used = True
    session.recovering = True
    try:
        yield session if session.remaining() > 0 else None
    finally:
        session.recovering = False


def _wait(session, seconds):
    if seconds <= 0:
        session.check_active()
        return
    if seconds >= session.remaining():
        raise SourceRequestStopped("재조회 대기 시간이 남은 조회 한도를 초과했습니다", retryable=True)
    started = time.monotonic()
    next_notice = started + 5
    try:
        while time.monotonic() - started < seconds:
            session.check_active()
            if time.monotonic() >= next_notice:
                session.message("외부 출처 재조회 대기 중")
                next_notice = time.monotonic() + 5
            time.sleep(max(0, min(0.25, seconds - (time.monotonic() - started))))
    finally:
        session.spent_seconds += time.monotonic() - started


def _retry_after(response):
    value = response.headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


async def _fetch(url, *, params, headers, timeout):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        async with client.stream("GET", url, params=params, headers=headers) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise SourceRequestStopped("외부 출처 응답 크기 한도를 초과했습니다", AdapterStatus.ERROR)
                body.extend(chunk)
            # The decoded body must not be decompressed a second time on cache hits.
            clean_headers = {k: v for k, v in response.headers.items()
                             if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}}
            return httpx.Response(response.status_code, headers=clean_headers, content=bytes(body),
                                  request=response.request)


async def _fetch_with_deadline(url, *, params, headers, timeout):
    task = asyncio.create_task(_fetch(url, params=params, headers=headers, timeout=timeout))
    session = _session.get()
    started = time.monotonic()
    next_notice = started + 5
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise SourceRequestStopped("외부 출처 조회 시간이 초과되었습니다")
            done, _ = await asyncio.wait({task}, timeout=min(1.0, remaining))
            if session:
                session.check_active()
            if done:
                return task.result()
            if session and time.monotonic() >= next_notice:
                session.message("외부 출처 응답 대기 중")
                next_notice = time.monotonic() + 5
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def source_get(adapter, url, *, params=None, headers=None, timeout=12):
    session = _session.get() or LookupSession(max(0.01, float(timeout)), max_attempts=1)
    trace = _trace.get()
    key = hashlib.sha256(json.dumps([adapter, url, params, headers], sort_keys=True,
                                   ensure_ascii=False, default=str).encode()).hexdigest()
    timeout = max(0.01, float(session.request_timeout if session.request_timeout is not None else timeout))
    attempts = 0
    status = AdapterStatus.ERROR
    retryable = False
    cached = False
    try:
        session.check_active()
        if key in session.cache:
            cached, status = True, AdapterStatus.READY
            session.cache.move_to_end(key)
            return session.cache[key]
        if adapter in session.blocked:
            until = session.blocked_until.get(adapter)
            if until is None:
                raise SourceRequestStopped("출처 접근 권한을 확인해야 합니다", session.blocked[adapter], retryable=False)
            delay = max(0, until - time.monotonic())
            if delay and session.recovering and adapter not in session.recovery_probes:
                session.recovery_probes.add(adapter)
                session.message("출처 연결 회복을 기다린 뒤 다시 조회합니다")
                _wait(session, delay)
                delay = 0
            if delay:
                raise SourceRequestStopped("외부 출처의 반복 장애로 조회를 잠시 보류했습니다",
                                           session.blocked[adapter], retryable=True)
            session.blocked.pop(adapter)
            session.blocked_until.pop(adapter, None)
        for attempt in range(session.max_attempts):
            session.check_active()
            remaining = session.remaining()
            if remaining <= 0:
                raise SourceRequestStopped("이 문서의 외부 출처 조회 시간 한도를 소진했습니다")
            attempts += 1
            started = time.monotonic()
            delay = 0.0
            try:
                response = asyncio.run(_fetch_with_deadline(url, params=params, headers=headers,
                    timeout=min(timeout * (attempt + 1), 45.0, remaining)))
                code = response.status_code
                status = (AdapterStatus.READY if 200 <= code < 300 else
                          AdapterStatus.RATE_LIMITED if code == 429 else AdapterStatus.ERROR)
                retryable = code in (408, 429) or 500 <= code < 600
                if retryable:
                    delay = _retry_after(response)
                    if delay:
                        session.blocked[adapter] = status
                        session.blocked_until[adapter] = time.monotonic() + delay
                elif code in (401, 403):
                    session.blocked[adapter] = status
                    session.blocked_until.pop(adapter, None)
            except (httpx.RequestError, OSError) as exc:
                status = (exc.status if isinstance(exc, SourceRequestStopped) else
                          AdapterStatus.TIMEOUT if isinstance(exc, httpx.TimeoutException) else AdapterStatus.ERROR)
                retryable = exc.retryable if isinstance(exc, SourceRequestStopped) else True
                if not retryable:
                    raise
            finally:
                session.spent_seconds += time.monotonic() - started
            if not retryable:
                session.failures[adapter] = 0
                if status == AdapterStatus.READY:
                    session.blocked.pop(adapter, None)
                    session.blocked_until.pop(adapter, None)
                session.remember(key, response)
                return response
            if attempt + 1 < session.max_attempts:
                session.message(f"외부 출처 재조회 {attempt + 2}/{session.max_attempts}회")
                _wait(session, max(delay, min(8, session.retry_backoff * 2 ** attempt)))
        raise SourceRequestStopped("자동 재조회 후에도 외부 출처 응답을 확보하지 못했습니다",
                                   status, retryable=True)
    except SourceRequestStopped as exc:
        status, retryable = exc.status, exc.retryable
        if retryable and attempts:
            session.failures[adapter] = session.failures.get(adapter, 0) + 1
            if session.failures[adapter] >= FAILURE_THRESHOLD or status == AdapterStatus.RATE_LIMITED:
                session.blocked[adapter] = status
                session.blocked_until[adapter] = max(session.blocked_until.get(adapter, 0),
                                                     time.monotonic() + session.cooldown_seconds)
        raise
    finally:
        if trace:
            trace.record(key, adapter, attempts, status, retryable, cached)
