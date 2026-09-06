"""Celery Worker (제3.1장 비동기 Worker).

MVP는 인프로세스 스레드로 동작하고, 브로커가 설정되면 동일 진입점을 Celery task로 실행한다.
Verification Core는 두 경로에서 동일하게 재사용된다.

실행:
    celery -A workers.celery_app worker -l info -Q verification,report
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# celery 콘솔 스크립트로 기동하면 sys.path[0]이 .venv/bin이라 저장소 루트가 빠진다.
# 또한 prefork 워커 자식 프로세스는 부모의 sys.path를 그대로 물려받지 않을 수 있으므로
# 모듈 로드 시점과 태스크 실행 시점 양쪽에서 루트를 보장한다.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])


def ensure_import_path() -> None:
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)


ensure_import_path()

from packages.common.config import get_settings

DEFAULT_BROKER = "redis://localhost:6379/0"


def broker_url() -> str:
    settings = get_settings()
    return settings.celery_broker or os.getenv("LV_CELERY_BROKER", "")


def backend_url() -> str:
    settings = get_settings()
    return settings.celery_backend or settings.celery_broker or os.getenv("LV_CELERY_BACKEND", "")


def celery_available() -> bool:
    try:
        import celery  # noqa: F401

        return True
    except Exception:
        return False


def build_app(broker: Optional[str] = None) -> Any:
    """Celery 앱을 만든다. celery 미설치 시 None을 반환한다."""
    if not celery_available():
        return None
    from celery import Celery

    url = broker or broker_url() or DEFAULT_BROKER
    app = Celery("legal_verifier", broker=url, backend=backend_url() or url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # 장시간 문서 분석을 위해 late ack + 프리페치 1로 둔다
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_time_limit=int(os.getenv("LV_TASK_TIME_LIMIT", str(60 * 30))),
        task_soft_time_limit=int(os.getenv("LV_TASK_SOFT_TIME_LIMIT", str(60 * 25))),
        task_default_queue="verification",
        task_routes={
            "verification.run": {"queue": "verification"},
            "report.build": {"queue": "report"},
        },
        result_expires=60 * 60 * 24,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = build_app()

# 브로커 URL별 앱 캐시. API 프로세스는 태스크 구현을 임포트하지 않고
# 이름으로 메시지만 보내므로(send_task) 프로듀서와 컨슈머가 분리된다.
_app_cache: dict = {}


def get_celery_app(broker: Optional[str] = None) -> Any:
    """현재 설정의 브로커에 연결된 Celery 앱을 돌려준다.

    모듈 로드 시점의 환경변수에 고정되지 않도록 URL을 키로 캐시한다.
    """
    if not celery_available():
        return None
    url = broker or broker_url() or DEFAULT_BROKER
    if url not in _app_cache:
        _app_cache[url] = build_app(url)
    return _app_cache[url]


VERIFICATION_TASK = "verification.run"


if celery_app is not None:  # pragma: no branch

    @celery_app.task(name="verification.run", bind=True, max_retries=2)
    def run_verification_task(self, run_id: str) -> str:
        """검증 Job 실행. 실패해도 Job 상태는 DB에 기록된다."""
        ensure_import_path()
        from apps.api.services import execute_run

        try:
            execute_run(run_id)
        except Exception as exc:  # pragma: no cover - 재시도 경로
            raise self.retry(exc=exc, countdown=10)
        return run_id

else:  # celery 미설치 환경에서도 임포트가 깨지지 않게 한다

    def run_verification_task(run_id: str) -> str:  # type: ignore[misc]
        ensure_import_path()
        from apps.api.services import execute_run

        execute_run(run_id)
        return run_id
