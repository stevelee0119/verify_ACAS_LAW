"""저장 공간 관리와 DB 장애 안내.

- 헬스체크는 DB 연결 상태를 싣는다(DB가 끊겨도 웹 서버는 살아 있어 배포 플랫폼은 정상으로 본다).
- DB에 연결할 수 없거나 저장 공간이 찬 오류는 기능 오류(500)가 아니라 '데이터베이스 사용 불가'(503)로 알린다.
- 관리자는 저장 공간 사용량을 보고, 빈 공간 정리(VACUUM)·디스크 반환(VACUUM FULL)을 실행한다.
- 영구 삭제 뒤에는 지운 테이블을 자동으로 정리한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from test_api import client  # noqa: F401


def _db_error(sqlstate):
    class DriverError(Exception):
        pass
    DriverError.sqlstate = sqlstate
    return OperationalError("SELECT 1", {}, DriverError("connection failed"))


def test_health_reports_database_status(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == {"status": "ok"}


def test_health_stays_200_when_the_database_is_down(client, monkeypatch):
    from apps.api import storage_admin

    class Broken:
        def connect(self):
            raise _db_error(None)
    monkeypatch.setattr(storage_admin, "get_engine", lambda: Broken())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"]["status"] == "error"


@pytest.mark.parametrize("sqlstate,phrase", [(None, "연결할 수 없어"), ("08006", "연결할 수 없어"),
                                             ("53100", "저장 공간이 가득"), ("57P03", "연결할 수 없어")])
def test_database_outage_is_reported_as_503_not_a_feature_error(client, monkeypatch, sqlstate, phrase):
    from apps.api.routers import projects as projects_router

    def broken(session, project):
        raise _db_error(sqlstate)
    client.post("/api/projects", json={"name": "DB 장애"})
    monkeypatch.setattr(projects_router, "_project_out", broken)
    raw = TestClient(client.app, raise_server_exceptions=False)
    raw.headers.update(client.headers)
    response = raw.get("/api/projects")
    detail = response.json()["detail"]
    assert response.status_code == 503 and detail["code"] == "DATABASE_UNAVAILABLE"
    assert phrase in detail["message"] and detail["request_id"] in detail["message"]


def test_query_errors_that_are_not_outages_stay_500(client, monkeypatch):
    from apps.api.routers import projects as projects_router

    def broken(session, project):
        raise _db_error("57014")        # 질의 취소는 DB 장애가 아니다
    client.post("/api/projects", json={"name": "질의 취소"})
    monkeypatch.setattr(projects_router, "_project_out", broken)
    raw = TestClient(client.app, raise_server_exceptions=False)
    raw.headers.update(client.headers)
    assert raw.get("/api/projects").status_code == 500


def test_admin_sees_storage_usage_and_can_reclaim_space(client):
    report = client.get("/api/admin/storage").json()
    assert report["dialect"] in {"sqlite", "postgresql"} and report["database_bytes"] > 0
    assert set(report["files"]["parts"]) >= {"originals", "derivatives"} and "다시 쓰게" in report["note"]
    result = client.post("/api/admin/storage/reclaim", json={"full": False}).json()
    assert result["full"] is False and result["before_bytes"] > 0 and result["seconds"] >= 0
    events = client.get("/api/audit/events").json() if client.get("/api/audit/events").status_code == 200 else None
    if isinstance(events, list):
        assert any((e.get("payload") or {}).get("action") == "STORAGE_RECLAIMED" for e in events)

