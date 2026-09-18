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


class JobRunner:
    def __init__(self, store=None):
        self.store = store or JobStore()
        self._threads = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._poller = None

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
        while not self._stop.wait(float(os.getenv("LV_JOB_POLL_SECONDS", "2"))):
            try:
                self.recover()
            except Exception:
                log.exception("Durable job recovery will retry on the next poll")

    def recover(self):
        self.store.adopt_queued()
        recovered = self.store.recover()
        for run_id in self.store.due():
            self._dispatch(run_id)
        with self._lock:
            self._threads = {rid: t for rid, t in self._threads.items() if t.is_alive()}
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
        if mode == "inprocess":
            with self._lock:
                active = sum(t.is_alive() for t in self._threads.values())
                if active >= max(1, int(os.getenv("LV_JOB_CONCURRENCY", "2"))):
                    return "queued"
        if not self.store.acquire_dispatch(run_id):
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
                    self.store.dispatch_result(run_id, error=type(exc).__name__)
                    return "queued"
                # Auto mode may run locally; both transports must obtain the same DB lease.
        from apps.api.services import execute_run
        with self._lock:
            current = self._threads.get(run_id)
            if current and current.is_alive():
                return "inprocess"
            if sum(t.is_alive() for t in self._threads.values()) >= max(1, int(os.getenv("LV_JOB_CONCURRENCY", "2"))):
                self.store.dispatch_result(run_id, error="LOCAL_CAPACITY_BUSY")
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
