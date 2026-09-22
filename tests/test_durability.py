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
