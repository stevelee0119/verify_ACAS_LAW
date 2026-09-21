"""Upload errors remain actionable and blocking storage does not stall health checks."""
import asyncio
import errno
import threading

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from test_api import client, project

PAYLOAD = b"%PDF-1.4\nSynthetic upload only\n%%EOF"


@pytest.mark.parametrize("error,code", [
    (PermissionError(errno.EACCES, "SECRET_PATH"), "UPLOAD_STORAGE_UNAVAILABLE"),
    (OSError(errno.ENOSPC, "SECRET_PATH"), "UPLOAD_STORAGE_UNAVAILABLE"),
    (OperationalError("SECRET_SQL", {}, RuntimeError("SECRET_VALUE")), "UPLOAD_DATABASE_UNAVAILABLE"),
])
def test_upload_failure_has_safe_reason_and_trace_id(client, project, monkeypatch, caplog, error, code):
    from apps.api.routers import projects

    def fail(*args):
        raise error
    monkeypatch.setattr(projects, "_store_document", fail)
    response = client.post(f"/api/projects/{project['id']}/documents", files={"file": ("test.pdf", PAYLOAD)})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert len(detail["request_id"]) == 32
    assert response.headers["X-Request-ID"] == detail["request_id"]
    assert detail["request_id"] in caplog.text
    assert "SECRET" not in response.text + caplog.text


def test_upload_success_and_validation_keep_trace_id(client, project):
    path = f"/api/projects/{project['id']}/documents"
    for payload, status in [(PAYLOAD, 201), (b"", 400)]:
        response = client.post(path, files={"file": ("test.pdf", payload)})
        assert response.status_code == status
        assert len(response.headers["X-Request-ID"]) == 32


def test_blocking_upload_does_not_block_health(client, project, monkeypatch):
    from apps.api.routers import projects

    started, released = threading.Event(), threading.Event()
    health_released_scan = []

    def slow_scan(*args):
        started.set()
        health_released_scan.append(released.wait(5))
        return None
    monkeypatch.setattr(projects, "scan_upload", slow_scan)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                    base_url="http://testserver", headers=dict(client.headers)) as ac:
            task = asyncio.create_task(ac.post(f"/api/projects/{project['id']}/documents",
                                               files={"file": ("test.pdf", PAYLOAD)}))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                response = await asyncio.wait_for(ac.get("/api/health"), timeout=3)
                assert response.status_code == 200
            finally:
                released.set()
                uploaded = await asyncio.wait_for(task, timeout=5)
            assert uploaded.status_code == 201
    asyncio.run(check())
    assert health_released_scan == [True]
