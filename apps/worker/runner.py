"""Database polling is the recovery authority; Celery is only a delivery channel."""
from __future__ import annotations

import logging
import os
import threading
import time

from apps.api.db import VerificationRun
from apps.api.job_control import DurableJob, JobStore, TERMINAL
from packages.common.config import get_settings

log = logging.getLogger(__name__)


def _env_seconds(name, default):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    return max(1.0, value)


class JobRunner:
    def __init__(self, store=None):
        self.store = store or JobStore()
        self._threads = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._poller = None
        self._busy = False

    def concurrency(self, mode=None):
        """인프로세스 실행은 API와 같은 프로세스를 쓴다.

        파싱·정규식 구간은 GIL을 쥐므로 그동안 HTTP 응답이 밀린다. 검증을
        둘씩 돌리면 그 구간이 겹쳐 화면이 "서버 연결 지연"으로 보인다.
        별도 Worker 프로세스라면 API를 밀어내지 않으므로 둘을 허용한다.
        LV_JOB_CONCURRENCY로 명시하면 그 값을 따른다.
        """
        configured = (os.getenv("LV_JOB_CONCURRENCY") or "").strip()
        if configured:
            try:
                return max(1, int(configured))
            except ValueError:
                log.warning("LV_JOB_CONCURRENCY=%r is not an integer; using the default", configured)
        return 1 if (mode or self.mode) == "inprocess" else 2

    @property
    def mode(self):
        settings = get_settings()
        configured = (settings.worker_mode or "auto").lower()
        if configured in {"inprocess", "celery"}:
            return configured
        from workers.celery_app import broker_url, celery_available
        return "celery" if broker_url() and celery_available() else "inprocess"

    def start(self):
        """Call after schema initialization, once per API lifespan."""
        with self._lock:
            if self._poller and self._poller.is_alive():
                return
            self._stop.clear()
            self.recover()
            self._poller = threading.Thread(target=self._poll, daemon=True, name="job-recovery")
            self._poller.start()

    def _poll(self):
        """Back off while idle; recovery polling competes with the run for the DB."""
        base = float(os.getenv("LV_JOB_POLL_SECONDS", "2"))
        # 짧은 주기로 설정한 시험이 대기 상한에 걸리지 않도록 base에 비례해 묶는다.
        idle_max = max(base, min(float(os.getenv("LV_JOB_POLL_IDLE_SECONDS", "15")), base * 15))
        wait = base
        while not self._stop.wait(wait):
            try:
                self.recover()
                wait = base if self._busy else min(idle_max, wait * 2)
            except Exception:
                wait = base
                log.exception("Durable job recovery will retry on the next poll")

    def recover(self):
        self.store.adopt_queued()
        recovered = self.store.recover()
        due = self.store.due()
        for run_id in due:
            self._dispatch(run_id)
        with self._lock:
            self._threads = {rid: t for rid, t in self._threads.items() if t.is_alive()}
        # 실행 중인 스레드는 폴러를 필요로 하지 않는다. 오히려 그때가 DB 경합을
        # 줄여야 할 시점이다. 대기 중인 일이 있을 때만 빠른 주기를 유지한다.
        self._busy = bool(recovered or due)
        return recovered

    def stop(self, timeout=10):
        self._stop.set()
        deadline = time.monotonic() + timeout
        if self._poller:
            self._poller.join(max(0, deadline - time.monotonic()))
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        # An interrupted process leaves an expiring lease; another poller recovers it.

    def submit(self, run_id):
        self.store.ensure(run_id)
        return self._dispatch(run_id)

    def _dispatch(self, run_id):
        mode = self.mode
        limit = self.concurrency(mode)
        if mode == "inprocess":
            with self._lock:
                active = sum(t.is_alive() for t in self._threads.values())
                if active >= limit:
                    self.store.defer(run_id, active)
                    return "queued"
        dispatch_seconds = (_env_seconds("LV_JOB_CELERY_DISPATCH_SECONDS",
                                         os.getenv("LV_JOB_DISPATCH_SECONDS", "300"))
                            if mode == "celery" else
                            _env_seconds("LV_JOB_DISPATCH_SECONDS", "30"))
        if not self.store.acquire_dispatch(run_id, seconds=dispatch_seconds):
            return mode
        if mode == "celery":
            try:
                from workers.celery_app import VERIFICATION_TASK, get_celery_app
                app = get_celery_app()
                if app is None:
                    raise RuntimeError("Celery is unavailable")
                task = app.send_task(VERIFICATION_TASK, args=[run_id], queue="verification", retry=False)
                self.store.dispatch_result(run_id, task_id=task.id)
                return "celery"
            except Exception as exc:
                if get_settings().worker_mode == "celery":
                    self.store.dispatch_result(run_id, error=type(exc).__name__,
                                               seconds=_env_seconds("LV_JOB_DISPATCH_RETRY_SECONDS", "30"))
                    return "queued"
                # Auto mode may run locally; both transports must obtain the same DB lease.
        from apps.api.services import execute_run
        with self._lock:
            current = self._threads.get(run_id)
            if current and current.is_alive():
                return "inprocess"
            active = sum(t.is_alive() for t in self._threads.values())
            if active >= limit:
                self.store.dispatch_result(run_id, error="LOCAL_CAPACITY_BUSY",
                                           seconds=_env_seconds("LV_JOB_DISPATCH_RETRY_SECONDS", "5"))
                self.store.defer(run_id, active)
                return "queued"
            thread = threading.Thread(target=execute_run, args=(run_id,), kwargs={"store": self.store},
                                      daemon=True, name="verification-" + run_id)
            self._threads[run_id] = thread
            thread.start()
        return "inprocess"

    def task_id(self, run_id):
        with self.store.session() as session:
            job = session.get(DurableJob, run_id)
            return job.task_id if job else None

    def wait(self, run_id, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.store.session() as session:
                run = session.get(VerificationRun, run_id)
                if run is None or run.state in TERMINAL:
                    return
            self.recover()
            time.sleep(0.05)

    def busy(self):
        from sqlalchemy import select
        with self.store.session() as session:
            return list(session.scalars(select(DurableJob.run_id).where(DurableJob.state == "RUNNING")))
