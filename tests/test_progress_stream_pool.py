"""진행률 스트림(SSE)이 요청 세션의 DB 커넥션을 스트림 내내 붙잡지 않는다.

붙잡으면 작은 커넥션 풀(운영 기본 5개)이 스트림 몇 개로 바닥나고, 다른 요청이 풀 대기
시간 초과(TimeoutError → HTTP 500)로 실패한다.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from apps.api.routers import verification


class FakeSession:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def close(self):
        self.log.append(f"close:{self.name}")

    def get(self, model, key):
        self.log.append(f"get:{self.name}")
        return SimpleNamespace(project_id="p1", state="COMPLETED", progress=1.0, stage_message="완료")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_request_session_is_released_before_streaming(monkeypatch):
    log = []
    monkeypatch.setattr(verification, "accessible_run", lambda session, user, run_id: log.append("authorize"))
    monkeypatch.setattr(verification, "current_principal", lambda: SimpleNamespace(user_id="u1"))
    monkeypatch.setattr(verification, "require_project", lambda *a, **k: None)
    monkeypatch.setattr(verification, "get_session_factory", lambda: (lambda: FakeSession(log, "short")))
    request_session = FakeSession(log, "request")
    response = asyncio.run(verification.stream_progress("run1", user=SimpleNamespace(), session=request_session))
    # 스트림을 돌려주기 전에 요청 세션을 닫는다.
    assert log[:2] == ["authorize", "close:request"]

    async def drain():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(drain())
    assert any('"finished": true' in c for c in chunks)
    # 스트림 안에서는 짧은 세션만 열고 닫는다.
    assert log.count("get:short") == log.count("close:short") >= 1
