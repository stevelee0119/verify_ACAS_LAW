"""제3.1장 비동기 Worker.

브로커 유무에 따른 실행 경로 선택과 Graceful Degradation을 검증한다.
실제 Celery 통합은 LV_TEST_CELERY_BROKER가 지정된 경우에만 수행한다.
"""
from __future__ import annotations

import os

import pytest

from packages.common.config import get_settings
from workers.celery_app import broker_url, build_app, celery_available, ensure_import_path, get_celery_app

CELERY_BROKER = os.getenv("LV_TEST_CELERY_BROKER")
celery_integration = pytest.mark.skipif(not CELERY_BROKER, reason="LV_TEST_CELERY_BROKER 미지정")


@pytest.fixture()
def runner():
    from apps.api.services import get_runner

    return get_runner()


@pytest.fixture()
def restore_worker_settings():
    settings = get_settings()
    original = (settings.worker_mode, settings.celery_broker)
    yield settings
    settings.worker_mode, settings.celery_broker = original


# --- 모드 선택 ---------------------------------------------------------------
def test_defaults_to_inprocess_without_broker(runner, restore_worker_settings):
    settings = restore_worker_settings
    settings.worker_mode = "auto"
    settings.celery_broker = ""
    assert runner.mode == "inprocess"


@pytest.mark.skipif(not celery_available(), reason="celery 미설치")
def test_switches_to_celery_when_broker_configured(runner, restore_worker_settings):
    settings = restore_worker_settings
    settings.worker_mode = "auto"
    settings.celery_broker = "redis://127.0.0.1:6399/0"
    assert runner.mode == "celery"


def test_explicit_inprocess_overrides_broker(runner, restore_worker_settings):
    settings = restore_worker_settings
    settings.worker_mode = "inprocess"
    settings.celery_broker = "redis://127.0.0.1:6399/0"
    assert runner.mode == "inprocess"


# --- Graceful Degradation ----------------------------------------------------
@pytest.mark.skipif(not celery_available(), reason="celery 미설치")
def test_falls_back_to_inprocess_when_broker_unreachable(tmp_path, restore_worker_settings):
    """브로커 장애가 전체 기능 상실로 이어지지 않는다(제2장)."""
    from helpers import make_pdf

    from apps.api.db import Document, Project, VerificationRun, get_session_factory, init_db
    from apps.api.services import get_runner
    from packages.common.enums import JobState
    from packages.common.storage import get_storage, sha256_bytes

    settings = restore_worker_settings
    settings.worker_mode = "auto"
    # 아무도 듣고 있지 않은 포트 + 즉시 실패하도록 재시도를 끈다
    settings.celery_broker = "redis://127.0.0.1:6399/0"

    init_db()
    session = get_session_factory()()
    try:
        project = Project(name="브로커 장애 테스트")
        session.add(project)
        session.flush()

        path = make_pdf(tmp_path / "fallback.pdf", ["원고는 손해배상을 구한다."])
        data = path.read_bytes()
        digest = sha256_bytes(data)
        key = get_storage().put_original(f"{project.id}/{digest}.pdf", data)
        document = Document(
            project_id=project.id, filename="fallback.pdf", mime_type="application/pdf",
            size_bytes=len(data), sha256=digest, storage_key=key,
        )
        session.add(document)
        session.flush()

        run = VerificationRun(
            project_id=project.id, document_ids=[document.id], profile="STANDARD",
            state=str(JobState.QUEUED), verification_key="fallback-test-key",
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    runner = get_runner()

    # Celery 디스패치가 실패하도록 강제한다
    import workers.celery_app as worker_module

    class _BrokenApp:
        @staticmethod
        def send_task(*_args, **_kwargs):
            raise ConnectionError("브로커에 연결할 수 없다")

    original_factory = worker_module.get_celery_app
    worker_module.get_celery_app = lambda *a, **k: _BrokenApp()  # type: ignore[assignment]
    try:
        mode = runner.submit(run_id)
        assert mode == "inprocess", "브로커 장애 시 인프로세스로 강등되어야 한다"
        runner.wait(run_id, 120)
    finally:
        worker_module.get_celery_app = original_factory  # type: ignore[assignment]

    session = get_session_factory()()
    try:
        finished = session.get(VerificationRun, run_id)
        assert finished.state in (str(JobState.COMPLETED), str(JobState.PARTIAL_COMPLETED))
    finally:
        session.close()


# --- Celery 앱 구성 -----------------------------------------------------------
@pytest.mark.skipif(not celery_available(), reason="celery 미설치")
def test_celery_app_configuration():
    app = build_app("redis://127.0.0.1:6399/0")
    assert app is not None
    assert app.conf.task_acks_late is True, "장시간 작업이므로 late ack이어야 한다"
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_serializer == "json" and app.conf.accept_content == ["json"]
    assert "verification.run" in app.conf.task_routes


def test_import_path_bootstrap_is_idempotent():
    import sys

    ensure_import_path()
    before = list(sys.path)
    ensure_import_path()
    assert sys.path == before


# --- 실제 브로커 통합 ----------------------------------------------------------
@celery_integration
def test_dispatches_to_real_broker(restore_worker_settings):
    """브로커가 있으면 Celery로 넘기고 task id를 남긴다."""
    from apps.api.db import Project, VerificationRun, get_session_factory, init_db
    from apps.api.services import get_runner
    from packages.common.enums import JobState

    settings = restore_worker_settings
    settings.worker_mode = "celery"
    settings.celery_broker = CELERY_BROKER

    init_db()
    session = get_session_factory()()
    try:
        project = Project(name="브로커 통합 테스트")
        session.add(project)
        session.flush()
        run = VerificationRun(
            project_id=project.id, document_ids=[], profile="STANDARD",
            state=str(JobState.QUEUED), verification_key="broker-integration-key",
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    runner = get_runner()
    assert runner.submit(run_id) == "celery"
    assert runner.task_id(run_id)
