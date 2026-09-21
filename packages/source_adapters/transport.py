"""Run-local, bounded official-source requests. Never cache across projects or runs."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Callable, Optional

import httpx

from packages.common.enums import AdapterStatus

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_CACHE_ENTRIES = 64
FAILURE_THRESHOLD = 2


class SourceRequestStopped(httpx.RequestError):
    def __init__(self, message, status=AdapterStatus.TIMEOUT):
        super().__init__(message)
        self.status = status


@dataclass
class LookupSession:
    budget_seconds: float
    check: Optional[Callable[[], None]] = None
    spent_seconds: float = 0.0
    failures: dict = field(default_factory=dict)
    blocked: dict = field(default_factory=dict)
    cache: OrderedDict = field(default_factory=OrderedDict)
    cache_bytes: int = 0

    def remember(self, key, response):
        size = len(response.content)
        if size > MAX_CACHE_BYTES or not 200 <= response.status_code < 300:
            return
        while self.cache and (len(self.cache) >= MAX_CACHE_ENTRIES or self.cache_bytes + size > MAX_CACHE_BYTES):
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= len(old.content)
        self.cache[key] = response
        self.cache_bytes += size


_session = ContextVar("source_lookup_session", default=None)


@contextmanager
def source_lookup_session(budget_seconds, *, check=None):
    session = LookupSession(max(0.01, float(budget_seconds)), check=check)
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)
        session.cache.clear()
        session.cache_bytes = 0


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
    try:
        return await asyncio.wait_for(_fetch(url, params=params, headers=headers, timeout=timeout), timeout)
    except asyncio.TimeoutError as exc:
        raise SourceRequestStopped("외부 출처 조회 시간이 초과되었습니다") from exc


def source_get(adapter, url, *, params=None, headers=None, timeout=12):
    session = _session.get()
    key = hashlib.sha256(json.dumps([adapter, url, params, headers], sort_keys=True,
                                   ensure_ascii=False, default=str).encode()).hexdigest()
    timeout = max(0.01, float(timeout))
    if session is not None:
        if session.check:
            session.check()
        if key in session.cache:
            session.cache.move_to_end(key)
            return session.cache[key]
        if adapter in session.blocked:
            raise SourceRequestStopped(
                "외부 출처의 반복 장애로 이번 검증의 추가 조회를 중단했습니다. 해당 항목은 미검증입니다",
                session.blocked[adapter])
        remaining = session.budget_seconds - session.spent_seconds
        if remaining <= 0:
            raise SourceRequestStopped("이번 검증의 외부 출처 조회 시간 한도를 소진했습니다. 해당 항목은 미검증입니다")
        timeout = min(timeout, remaining)
    started = time.monotonic()
    try:
        response = asyncio.run(_fetch_with_deadline(url, params=params, headers=headers, timeout=timeout))
        if session is not None:
            if response.status_code in (401, 403, 429):
                session.blocked[adapter] = (AdapterStatus.RATE_LIMITED if response.status_code == 429
                                            else AdapterStatus.ERROR)
            elif response.status_code >= 500:
                session.failures[adapter] = session.failures.get(adapter, 0) + 1
                if session.failures[adapter] >= FAILURE_THRESHOLD:
                    session.blocked[adapter] = AdapterStatus.ERROR
            else:
                session.failures[adapter] = 0
                session.remember(key, response)
        return response
    except (httpx.RequestError, OSError) as exc:
        if session is not None:
            session.failures[adapter] = session.failures.get(adapter, 0) + 1
            if session.failures[adapter] >= FAILURE_THRESHOLD:
                session.blocked[adapter] = (exc.status if isinstance(exc, SourceRequestStopped) else
                                           AdapterStatus.TIMEOUT if isinstance(exc, httpx.TimeoutException)
                                           else AdapterStatus.ERROR)
        raise
    finally:
        if session is not None:
            session.spent_seconds += time.monotonic() - started
