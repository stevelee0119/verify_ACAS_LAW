"""Celery Worker 정의 (제3.1장).

MVP는 인프로세스 JobRunner로 동작하며, Redis가 구성되면 동일 함수를
Celery task로 실행한다. Verification Core는 두 경로에서 동일하게 재사용된다.
"""
from __future__ import annotations

import os

BROKER_URL = os.getenv("LV_CELERY_BROKER", "redis://localhost:6379/0")

try:  # pragma: no cover - 선택적 의존성
    from celery import Celery

    celery_app = Celery("legal_verifier", broker=BROKER_URL, backend=BROKER_URL)
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=60 * 30,
    )

    @celery_app.task(name="verification.run")
    def run_verification_task(run_id: str) -> str:
        from apps.api.services import execute_run

        execute_run(run_id)
        return run_id

except ImportError:  # Celery 미설치 환경
    celery_app = None

    def run_verification_task(run_id: str) -> str:  # type: ignore[misc]
        from apps.api.services import execute_run

        execute_run(run_id)
        return run_id
