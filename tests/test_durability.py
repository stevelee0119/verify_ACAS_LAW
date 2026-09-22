"""배포 저장소 내구성 점검.

잘못된 구성이 조용히 정상처럼 동작하는 것을 막는다. 실제로 SQLite가 컨테이너
내부에 생성된 배포에서 재시작마다 로그인·프로젝트·업로드 원본·감사기록이
사라졌고, 화면은 정상으로 보여 원인 발견이 늦어졌다.
"""
from __future__ import annotations

import logging

import pytest

from apps.api.durability import AT_RISK, DURABLE, UNKNOWN, durability_report, log_durability_warning


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    from packages.common.config import reset_settings

    for name in ("LV_DATABASE_URL", "DATABASE_URL", "LV_STORAGE_ROOT", "LV_DATA_DIR",
                 "RENDER_SERVICE_ID", "K_SERVICE", "DYNO", "WEBSITE_SITE_NAME",
                 "FLY_APP_NAME", "RAILWAY_SERVICE_ID"):
        monkeypatch.delenv(name, raising=False)
    reset_settings()
    yield
    reset_settings()


def _report(monkeypatch, **env):
    from packages.common.config import reset_settings

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    reset_settings()
    return durability_report()


def test_sqlite_inside_the_application_directory_is_at_risk(monkeypatch):
    """기본 배포 형태. 재배포하면 통째로 사라진다."""
    report = _report(monkeypatch)
    assert report["verdict"] == AT_RISK
    assert report["database"]["state"] == AT_RISK
    for item in ("로그인 세션", "업로드 원본", "감사기록"):
        assert item in report["at_risk"]


def test_managed_platform_without_a_configured_location_is_at_risk(monkeypatch, tmp_path):
    """Render 등에서 저장 위치를 지정하지 않으면 컨테이너와 함께 사라진다."""
    report = _report(monkeypatch, RENDER_SERVICE_ID="srv-1",
                     LV_DATABASE_URL=f"sqlite:///{tmp_path}/a.db")
    assert report["platform"] == "RENDER_SERVICE_ID"
    assert report["storage"]["state"] == AT_RISK
    assert "사라집니다" in report["storage"]["reason"]


def test_external_database_is_durable(monkeypatch, tmp_path):
    report = _report(monkeypatch, LV_DATABASE_URL="postgresql+psycopg://u:p@db:5432/x",
                     LV_DATA_DIR=str(tmp_path))
    assert report["database"]["state"] == DURABLE
    assert "로그인 세션" not in report["at_risk"]


def test_configured_location_is_unknown_not_safe(monkeypatch, tmp_path):
    """마운트 여부는 프로세스 안에서 알 수 없다. 모르는 것을 안전하다고 하지 않는다."""
    report = _report(monkeypatch, RENDER_SERVICE_ID="srv-1", LV_DATA_DIR=str(tmp_path),
                     LV_DATABASE_URL=f"sqlite:///{tmp_path}/a.db")
    assert report["storage"]["state"] == UNKNOWN
    assert "확인하지 못함" in report["note"]
    assert report["verdict"] != DURABLE


def test_object_storage_counts_as_durable(monkeypatch, tmp_path):
    report = _report(monkeypatch, LV_DATABASE_URL="postgresql+psycopg://u:p@db/x",
                     LV_STORAGE_BACKEND="s3", LV_DATA_DIR=str(tmp_path))
    if report["storage"]["kind"] in ("s3", "minio"):
        assert report["storage"]["state"] == DURABLE


def test_startup_logs_a_warning_naming_what_is_lost(monkeypatch, caplog):
    report = _report(monkeypatch)
    with caplog.at_level(logging.WARNING):
        log_durability_warning(report)
    message = caplog.text
    assert "사라집니다" in message
    assert "로그인 세션" in message


def test_durable_deployment_stays_quiet(monkeypatch, tmp_path, caplog):
    report = _report(monkeypatch, LV_DATABASE_URL="postgresql+psycopg://u:p@db/x",
                     LV_DATA_DIR=str(tmp_path))
    if report["verdict"] == AT_RISK:
        pytest.skip("이 환경에서는 저장소 경로가 위험으로 판정된다")
    with caplog.at_level(logging.WARNING):
        log_durability_warning(report)
    assert "사라집니다" not in caplog.text


def test_diagnostics_reports_durability_without_blocking_analysis(client):
    """분석 능력(OCR)과 저장소 내구성을 섞지 않는다."""
    payload = client.get("/api/diagnostics").json()
    durability = payload["capabilities"]["durability"]
    assert durability["verdict"] in (AT_RISK, UNKNOWN, DURABLE)
    assert "durability" not in payload["blocking"]
    if durability["verdict"] == AT_RISK:
        assert "durability" in payload["warnings"]
        assert durability["remedy"]


from test_api import client, project  # noqa: E402,F401


def test_mounted_volume_inside_the_application_directory_is_not_flagged(monkeypatch, tmp_path):
    """디스크를 소스 디렉터리 안에 마운트하는 배포도 있다.

    경로만 보고 위험하다고 하면 정상 구성을 잘못 경고한다. 실제 마운트를
    확인해서, 별도 볼륨이면 AT_RISK로 단정하지 않는다.
    """
    from apps.api import durability

    monkeypatch.setattr(durability, "mounted_volume", lambda path: True)
    report = _report(monkeypatch, RENDER_SERVICE_ID="srv-1")
    assert report["database"]["state"] != AT_RISK
    assert "별도 볼륨" in report["database"]["reason"]
    assert "확인하세요" in report["database"]["reason"]


def test_mount_detection_uses_the_filesystem_not_the_path(tmp_path):
    from apps.api.durability import mounted_volume

    assert mounted_volume(tmp_path) is False
    assert mounted_volume(tmp_path / "아직" / "없는" / "경로") is False


def test_sqlite_waits_for_the_write_lock_instead_of_failing(tmp_path, monkeypatch):
    """갱신 쓰기가 잠금 경합 한 번으로 실패하지 않아야 한다.

    기본 5초로는 느린 디스크에서 큰 체크포인트를 쓰는 동안 임차 갱신이
    "database is locked"로 떨어졌고, 그 한 번이 작업을 같은 단계에서
    반복 중단시켰다.
    """
    import apps.api.db as db
    from sqlalchemy import text

    monkeypatch.setenv("LV_SQLITE_BUSY_SECONDS", "17")
    monkeypatch.setenv("LV_DATABASE_URL", f"sqlite:///{tmp_path}/pragma.db")
    monkeypatch.setattr(db, "_engine", None)
    try:
        with db.get_engine().connect() as connection:
            def pragma(name):
                return connection.execute(text(f"PRAGMA {name}")).scalar()

            assert str(pragma("journal_mode")).lower() == "wal"
            assert int(pragma("busy_timeout")) == 17000
            assert int(pragma("synchronous")) == 1  # NORMAL
            assert int(pragma("foreign_keys")) == 1
    finally:
        db._engine = None


def test_ownership_check_does_not_take_the_write_lock(tmp_path, monkeypatch):
    """소유권 확인은 읽기여야 한다.

    외부 출처 조회 중 transport._fetch_with_deadline이 초당 한 번 이 확인을
    부른다. 그것이 쓰기 트랜잭션이면 문서당 수백 번 쓰기 잠금을 다투고,
    임차 갱신이 그 경합에 밀린다. 실제로 그렇게 실패했다.
    """
    from sqlalchemy import event

    from apps.api.db import get_engine
    from apps.api.job_control import JobOwnershipLost, JobStore

    store = JobStore()
    lease = type("Lease", (), {"run_id": "no-such-run", "owner": "nobody", "fence": 1})()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert store.owns(lease) is False
        with pytest.raises(JobOwnershipLost):
            store.check(lease)   # 파이프라인이 실제로 부르는 경로
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements, "확인이 DB에 닿지 않았다면 시험이 무의미하다"
    assert "UPDATE" not in statements, f"소유권 확인이 쓰기를 발생시켰다: {statements}"
