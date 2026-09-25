"""Durability, ownership and money invariants using real database transactions."""
from __future__ import annotations

import asyncio
import copy
import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from apps.api import db
from apps.api.db import Document, Project, VerificationRun
from apps.api.job_control import (
    DurableJob, JobAttempt, JobConflict, JobOwnershipLost, JobStore, Lease,
    enqueue_run, execution_settings_snapshot,
)
from apps.api.services import build_context, execute_run, persist_result
from apps.worker.runner import JobRunner
from packages.common.config import ProviderConfig, get_settings
from packages.common.enums import JobState, LLMRole
from packages.common.storage import get_storage, sha256_bytes
from packages.llm_router.budget import (
    BudgetAccount, BudgetExceeded, BudgetLedger, BudgetReservation, write_session,
)
from packages.llm_router.providers import LLMProvider, LLMRequest, LLMResponse
from packages.llm_router.router import LLMRouter
from packages.verification_engine import VerificationPipeline, VerificationRunResult


def _process_reserve(args):
    url, index = args
    engine = create_engine(url, connect_args={"timeout": 30})
    try:
        ledger = BudgetLedger(sessionmaker(engine))
        ledger.reserve("process-" + str(index), "0.2", monthly_limit="1")
        return True
    except BudgetExceeded:
        return False
    finally:
        engine.dispose()


def _crash_after_reserve(url):
    ledger = BudgetLedger(sessionmaker(create_engine(url)))
    reservation = ledger.reserve("crashed", "0.75", monthly_limit="1", reservation_id="crash")
    ledger.dispatch(reservation.id)
    os._exit(0)


def _crash_after_claim(url, run_id):
    store = JobStore(sessionmaker(create_engine(url), expire_on_commit=False))
    lease = store.claim(run_id)
    with store.session() as session:
        document_id = session.get(VerificationRun, run_id).document_ids[0]
    store.checkpoint(lease, document={"document_id": document_id, "findings": []})
    os._exit(0)


@pytest.fixture
def ops(tmp_path, monkeypatch):
    # Import the route-owned models before creating this isolated schema.
    from apps.api.routers import jobs, verification  # noqa: F401
    engine = create_engine("sqlite:///" + str(tmp_path / "operations.db"),
                           connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")

    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_SessionLocal", factory)
    monkeypatch.setattr(get_settings(), "worker_mode", "inprocess")
    monkeypatch.setenv("LV_JOB_BACKOFF_SECONDS", "0")
    yield factory
    engine.dispose()


def seeded_run(factory, *, enqueue=True, organization_id=None, policy="LOCAL_ONLY"):
    with factory() as session:
        project = Project(name="Snapshot", key_dates={"issue-a": "2020-01-02"}, external_ai_policy=policy,
                          organization_id=organization_id)
        session.add(project)
        session.flush()
        body = b"original snapshot bytes"
        key = get_storage().put_original(project.id + "/original.txt", body)
        document = Document(project_id=project.id, filename="original.txt", mime_type="text/plain",
                            storage_key=key, sha256=sha256_bytes(body), is_own_document=True)
        session.add(document)
        session.flush()
        snapshot = {"context": build_context(project).__dict__, "documents": [{
            "document_id": document.id, "filename": document.filename, "sha256": document.sha256,
            "is_own_document": True, "evidence_number": "EX-1"}], "issues": [{"id": "issue-a"}]}
        run = VerificationRun(project_id=project.id, document_ids=[document.id], profile="STANDARD",
                              verification_key="same-inputs", state="QUEUED", input_snapshot=snapshot)
        if enqueue:
            run, reused = enqueue_run(session, run)
            assert not reused
        session.commit()
        return run


def completed(run):
    return VerificationRunResult(run.id, run.project_id, JobState.COMPLETED, run.verification_key,
                                 scores={"ready": True})


def test_concurrent_monthly_reservations_and_decimal_precision(ops):
    def reserve(index):
        try:
            BudgetLedger(ops).reserve(str(index), "0.1", monthly_limit="1")
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(reserve, range(24)))
    assert sum(admitted) == 10
    account = BudgetLedger(ops).account("month:" + datetime.utcnow().strftime("%Y-%m"))
    assert account["reserved"] == Decimal("1") and account["spent"] == 0


def test_separate_processes_share_the_same_monthly_limit(ops):
    url = str(ops.kw["bind"].url)
    with multiprocessing.get_context("spawn").Pool(3) as pool:
        admitted = pool.map(_process_reserve, [(url, i) for i in range(12)])
    assert sum(admitted) == 5


def test_reservation_survives_process_crash_and_cannot_be_released(ops):
    process = multiprocessing.get_context("spawn").Process(target=_crash_after_reserve, args=(str(ops.kw["bind"].url),))
    process.start()
    process.join(30)
    assert process.exitcode == 0
    ledger = BudgetLedger(ops)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("next", "0.3", monthly_limit="1")
    with pytest.raises(ValueError, match="confirmed usage"):
        ledger.release("crash")
    ledger.settle("crash", Decimal("0.2"))
    assert not ledger.settle("crash", Decimal("0.2"))
    ledger.reserve("next", "0.8", monthly_limit="1")


def test_run_ceiling_is_atomic_and_failed_reservation_rolls_back_month(ops):
    ledger = BudgetLedger(ops)
    ledger.reserve("r1", "0.3", monthly_limit="5", run_limit="0.5", budget_run_id="root")
    with pytest.raises(BudgetExceeded):
        ledger.reserve("r2", "0.3", monthly_limit="5", run_limit="0.5", budget_run_id="root")
    assert ledger.account("run:root")["reserved"] == Decimal("0.3")
    assert ledger.account("month:" + datetime.utcnow().strftime("%Y-%m"))["reserved"] == Decimal("0.3")


def test_unused_release_and_tiny_usage_are_not_rounded_to_zero(ops):
    ledger = BudgetLedger(ops)
    reservation = ledger.reserve("tiny", "0.0000000011")
    assert reservation.amount == Decimal("0.000000002")
    assert ledger.release(reservation.id)
    assert not ledger.release(reservation.id)
    assert ledger.account("run:tiny")["reserved"] == 0


def test_month_rollover_keeps_original_reservations_and_attribution(ops):
    ledger = BudgetLedger(ops, clock=lambda: datetime(2026, 1, 31, 23, 59))
    reservation = ledger.reserve("old", "1", monthly_limit="1")
    ledger.clock = lambda: datetime(2026, 2, 1)
    ledger.reserve("new", "1", monthly_limit="1")
    ledger.settle(reservation.id, "0.5")
    assert ledger.account("month:2026-01")["spent"] == Decimal("0.5")
    assert ledger.account("month:2026-02")["reserved"] == Decimal("1")


def test_enqueue_and_outer_rollback_are_atomic(ops):
    template = seeded_run(ops, enqueue=False)
    with ops() as session:
        run, _ = enqueue_run(session, template)
        run_id = run.id
        session.rollback()
    with ops() as session:
        assert session.get(VerificationRun, run_id) is None
        assert session.get(DurableJob, run_id) is None


def test_concurrent_duplicate_submission_creates_one_run(ops):
    template = seeded_run(ops, enqueue=False)
    def submit(_):
        with ops() as session:
            run = VerificationRun(project_id=template.project_id, document_ids=template.document_ids,
                profile=template.profile, verification_key=template.verification_key, state="QUEUED",
                input_snapshot=copy.deepcopy(template.input_snapshot))
            run, _ = enqueue_run(session, run)
            session.commit()
            return run.id
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(submit, range(16)))
    assert len(set(ids)) == 1
    with ops() as session:
        assert session.scalar(select(func.count()).select_from(VerificationRun)) == 1
        assert session.scalar(select(func.count()).select_from(DurableJob)) == 1


def test_completion_between_cache_lookup_and_enqueue_keeps_deduplication(ops, monkeypatch):
    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    with write_session(ops) as session:
        persist_result(session, session.get(VerificationRun, run.id), completed(run),
                       lease=lease, store=store, commit=False)
        store.complete(session, lease, completed(run))
    with ops() as session:
        original = session.execute
        missed_cache_lookup = False

        def execute(statement, *args, **kwargs):
            nonlocal missed_cache_lookup
            if not missed_cache_lookup:
                missed_cache_lookup = True
                # PostgreSQL can finish a worker after this SELECT but before INSERT.
                return type("CacheMiss", (), {"scalar_one_or_none": lambda self: None})()
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", execute)
        candidate = VerificationRun(project_id=run.project_id, document_ids=run.document_ids,
            profile=run.profile, verification_key=run.verification_key, state="QUEUED",
            input_snapshot=copy.deepcopy(run.input_snapshot))
        canonical, reused = enqueue_run(session, candidate)
        session.commit()
        assert reused and canonical.id == run.id
        assert session.scalar(select(func.count()).select_from(VerificationRun)) == 1


def test_concurrent_claim_only_one_owner(ops):
    run = seeded_run(ops)
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda _: JobStore(ops).claim(run.id), range(16)))
    assert sum(lease is not None for lease in leases) == 1


def test_dead_process_recovery_fences_old_completion_and_preserves_partial(ops):
    run = seeded_run(ops)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_after_claim, args=(str(ops.kw["bind"].url), run.id))
    process.start()
    process.join(30)
    assert process.exitcode == 0
    with ops() as session:
        job = session.get(DurableJob, run.id)
        old = Lease(run.id, job.owner, job.fence)
        now = job.lease_expires_at + timedelta(seconds=1)
    store = JobStore(ops, clock=lambda: now, backoff_seconds=0)
    assert store.recover() == [run.id]
    fresh = store.claim(run.id)
    assert fresh and fresh.fence > old.fence
    with ops() as session, pytest.raises(JobOwnershipLost):
        persist_result(session, session.get(VerificationRun, run.id), completed(run), lease=old, store=store)
    with write_session(ops) as session:
        persist_result(session, session.get(VerificationRun, run.id), completed(run),
                       lease=fresh, store=store, commit=False)
        store.complete(session, fresh, completed(run))
    history = store.status(run.id)["history"]
    assert history[0]["state"] == "FAILED"
    assert history[0]["partial_result"]["documents"][0]["document_id"] == run.document_ids[0]
    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        # scores의 정본은 전용 칼럼이다. result_json은 그것을 중복하지 않는다.
        assert saved.state == "COMPLETED" and saved.scores["ready"]
        assert "WORKER_LEASE_EXPIRED" in saved.errors


def test_backoff_and_attempt_limit(ops):
    run = seeded_run(ops)
    now = datetime.utcnow() + timedelta(seconds=1)
    store = JobStore(ops, clock=lambda: now, backoff_seconds=2)
    with ops() as session:
        session.get(DurableJob, run.id).max_attempts = 2
        session.commit()
    first = store.claim(run.id)
    store.fail(first, "temporary")
    assert store.claim(run.id) is None
    now += timedelta(seconds=2)
    second = store.claim(run.id)
    store.fail(second, "again")
    assert store.status(run.id)["state"] == "FAILED"
    assert store.claim(run.id) is None


@pytest.mark.parametrize("claimed", [False, True])
def test_cancel_is_idempotent_and_invalidates_running_owner(ops, claimed):
    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id) if claimed else None
    if lease:
        store.checkpoint(lease, document={"document_id": run.document_ids[0]})
    assert store.cancel(run.id, actor="reviewer") == "CANCELLED"
    assert store.cancel(run.id, actor="reviewer") == "CANCELLED"
    assert store.claim(run.id) is None
    if lease:
        with pytest.raises(JobOwnershipLost):
            store.progress(lease, JobState.VERIFYING, "late", 0.9)
        assert store.status(run.id)["history"][0]["partial_result"]["documents"]


def test_retry_is_idempotent_and_copies_snapshot_and_budget_root(ops):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    with ops() as session:
        session.get(Project, run.project_id).key_dates = {"changed": "2099-01-01"}
        session.get(Document, run.document_ids[0]).included_in_verification = False
        session.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        children = list(pool.map(lambda _: JobStore(ops).retry(run.id), range(8)))
    assert len(set(children)) == 1
    with ops() as session:
        source, child = session.get(VerificationRun, run.id), session.get(VerificationRun, children[0])
        assert child.input_snapshot == source.input_snapshot
        assert child.verification_key == source.verification_key and child.document_ids == source.document_ids
        assert session.get(DurableJob, child.id).snapshot == session.get(DurableJob, source.id).snapshot
        assert session.get(DurableJob, child.id).budget_run_id == source.id
        assert source.state == "CANCELLED"


def test_runtime_uses_frozen_inputs_and_ignores_live_document_changes(ops, monkeypatch):
    run = seeded_run(ops)
    with ops() as session:
        session.get(Project, run.project_id).key_dates = {"new": "2099-01-01"}
        document = session.get(Document, run.document_ids[0])
        document.storage_key, document.filename, document.is_own_document = "missing", "changed", False
        session.commit()
    def pipeline(self, run_id, context, documents, **kwargs):
        assert context.issue_dates == {"issue-a": "2020-01-02"}
        assert documents[0].is_own_document is True and documents[0].filename == "original.txt"
        return completed(run)
    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=JobStore(ops))
    assert JobStore(ops).status(run.id)["state"] == "COMPLETED"


def test_late_result_after_cancellation_cannot_complete(ops, monkeypatch):
    run = seeded_run(ops)
    store = JobStore(ops)
    def pipeline(*args, **kwargs):
        store.cancel(run.id)
        return completed(run)
    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=store)
    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        assert saved.state == "CANCELLED" and saved.result_json is None


def test_heartbeat_prevents_recovery_during_slow_work(ops):
    """갱신 스레드가 도는 동안에는 임차 기간보다 오래 일해도 회수되지 않는다.

    시간은 주입 시계로, 갱신은 한 박자씩 진행한다. 벽시계로 재면 부하 걸린 CI 러너에서 스레드가
    잠깐 밀리는 것만으로 실패했다(임차 0.3초·0.45초 설정 모두 CI에서 실패).
    """
    from apps.worker.runtime import heartbeat

    run = seeded_run(ops)
    clock = ManualClock()
    store = JobStore(ops, clock=clock, lease_seconds=1.2)
    lease = store.claim(run.id)
    ticker = Ticker()
    try:
        with heartbeat(store, lease, monotonic=clock.monotonic, pause=ticker.pause) as check:
            for _ in range(5):  # 갱신 간격 0.4초 × 5 = 2초 > 임차 1.2초
                clock.advance(0.4)
                ticker.step()
                assert store.recover() == []
            check()
    finally:
        ticker.close()
    clock.advance(1.3)  # 갱신이 멈춘 뒤 임차 기간이 지나면 회수된다
    assert store.recover() == [run.id]


def test_startup_recovers_expired_run_and_shuts_down(ops, monkeypatch):
    run = seeded_run(ops)
    store = JobStore(ops, backoff_seconds=0)
    store.claim(run.id)
    with ops() as session:
        session.get(DurableJob, run.id).lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
    monkeypatch.setattr(VerificationPipeline, "run", lambda *a, **kw: completed(run))
    runner = JobRunner(store)
    try:
        runner.start()
        runner.start()
        runner.wait(run.id, 10)
        assert store.status(run.id)["state"] == "COMPLETED"
    finally:
        runner.stop()
    assert not runner._poller.is_alive()


def test_celery_delivery_uses_same_claim_and_duplicate_is_noop(ops, monkeypatch):
    import workers.celery_app as celery_module
    run = seeded_run(ops)
    now = datetime.utcnow()
    calls = []
    class App:
        def send_task(self, name, **kwargs):
            calls.append((name, kwargs))
            return type("Task", (), {"id": "task-" + str(len(calls))})()
    monkeypatch.setattr(celery_module, "get_celery_app", lambda: App())
    monkeypatch.setattr(get_settings(), "worker_mode", "celery")
    monkeypatch.delenv("LV_JOB_CELERY_DISPATCH_SECONDS", raising=False)
    monkeypatch.delenv("LV_JOB_DISPATCH_SECONDS", raising=False)
    runner = JobRunner(JobStore(ops, clock=lambda: now))
    assert runner.submit(run.id) == "celery"
    runner.submit(run.id)
    assert len(calls) == 1 and runner.task_id(run.id) == "task-1"
    now += timedelta(seconds=31)
    runner.submit(run.id)
    assert len(calls) == 1, "A queued Celery delivery must not be re-sent every local dispatch cycle"
    assert JobStore(ops, clock=lambda: now).status(run.id)["next_dispatch_at"] > now
    executions = []
    def pipeline(*args, **kwargs):
        executions.append(run.id)
        return completed(run)
    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=runner.store)
    execute_run(run.id, store=runner.store)
    assert executions == [run.id]


def test_explicit_celery_dispatch_failure_uses_bounded_retry_interval(ops, monkeypatch):
    import workers.celery_app as celery_module
    run = seeded_run(ops)
    now = datetime.utcnow()
    calls = []

    class BrokenApp:
        def send_task(self, *args, **kwargs):
            calls.append(now)
            raise ConnectionError("broker unavailable")

    monkeypatch.setattr(celery_module, "get_celery_app", lambda: BrokenApp())
    monkeypatch.setattr(get_settings(), "worker_mode", "celery")
    monkeypatch.setenv("LV_JOB_DISPATCH_RETRY_SECONDS", "45")
    runner = JobRunner(JobStore(ops, clock=lambda: now))
    assert runner.submit(run.id) == "queued"
    assert len(calls) == 1
    now += timedelta(seconds=30)
    assert runner.submit(run.id) == "celery"
    assert len(calls) == 1
    now += timedelta(seconds=15)
    assert runner.submit(run.id) == "queued"
    assert len(calls) == 2


class StubProvider(LLMProvider):
    name = "openai"
    @property
    def available(self):
        return True
    async def generate(self, request):
        self.calls += 1
        if self.callback:
            self.callback()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def model_router(ops, monkeypatch, response, **kwargs):
    from dataclasses import replace
    settings = replace(get_settings(), pricing={"openai": {"input": 2, "output": 8}})
    provider = StubProvider(ProviderConfig("openai", enabled=True, model="fixture"))
    provider.response, provider.calls, provider.callback = response, 0, None
    monkeypatch.delenv("LV_MONTHLY_BUDGET_USD", raising=False)
    router = LLMRouter({"openai": provider}, settings=settings, ledger=BudgetLedger(ops), run_id="model-run",
        limits={"monthly_limit": "1", "run_limit": "1", "max_input_tokens": 4096,
                "max_output_tokens": 1200, "unknown_call_usd": ""}, **kwargs)
    return router, provider


def test_model_reserves_before_external_call_then_settles_reported_usage(ops, monkeypatch):
    router, provider = model_router(ops, monkeypatch, LLMResponse(True, text="ok", input_tokens=100, output_tokens=10))
    def reserved():
        with ops() as session:
            row = session.scalar(select(BudgetReservation))
            assert row.state == "DISPATCHED" and row.reserved_units > 0
    provider.callback = reserved
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert result.used and provider.calls == 1
    assert BudgetLedger(ops).account("run:model-run")["spent"] == Decimal("0.00028")
    assert BudgetLedger(ops).account("run:model-run")["reserved"] == 0


def test_unresponsive_model_is_cancelled_without_releasing_uncertain_charge(ops, monkeypatch):
    router, provider = model_router(ops, monkeypatch, None)
    router.settings.http_timeout = 0.01
    closed = []
    async def never_finishes(request):
        try:
            await asyncio.sleep(60)
        finally:
            closed.append(True)
    monkeypatch.setattr(provider, "generate", never_finishes)
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert closed == [True] and not result.used
    assert result.executions[0].error.startswith("PROVIDER_TIMEOUT")
    assert result.executions[0].cost_status == "RESERVED_UNCERTAIN"
    with ops() as session:
        assert session.scalar(select(BudgetReservation)).state == "DISPATCHED"


@pytest.mark.parametrize("response,state", [(TimeoutError(), "DISPATCHED"), (LLMResponse(True, text="ok"), "SETTLED")])
def test_uncertain_or_missing_usage_never_releases_budget(ops, monkeypatch, response, state):
    router, provider = model_router(ops, monkeypatch, response)
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    with ops() as session:
        reservation = session.scalar(select(BudgetReservation))
        assert reservation.state == state
    account = BudgetLedger(ops).account("run:model-run")
    assert account["reserved"] + account["spent"] == Decimal("0.017792")


def test_missing_pricing_and_exhausted_budget_prevent_provider_call(ops, monkeypatch):
    router, provider = model_router(ops, monkeypatch, LLMResponse(True, text="ok"))
    router.settings.pricing = {}
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert not result.used and provider.calls == 0
    router.settings.pricing = {"openai": {"input": 2, "output": 8}}
    router.limits["run_limit"] = "0.00001"
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert not result.used and provider.calls == 0


def test_cancel_between_reservation_and_dispatch_releases_unsent_hold(ops, monkeypatch):
    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    checks = []
    def guard():
        checks.append(1)
        if len(checks) == 2:
            store.cancel(run.id)
        store.check(lease)
    router, provider = model_router(ops, monkeypatch, LLMResponse(True, text="ok"), call_guard=guard)
    with pytest.raises(JobOwnershipLost):
        asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert provider.calls == 0
    assert BudgetLedger(ops).account("run:model-run")["reserved"] == 0


def test_snapshot_contains_key_names_only_and_rejects_credentials_in_urls(ops, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-snapshot")
    snapshot = execution_settings_snapshot()
    assert "must-not-enter-snapshot" not in str(snapshot)
    assert snapshot["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    monkeypatch.setattr(get_settings().providers["openai"], "base_url", "https://secret@example.com/v1")
    with pytest.raises(JobConflict):
        execution_settings_snapshot()


def test_rejected_tighter_cap_remains_central_across_process_configurations(ops):
    ledger = BudgetLedger(ops)
    ledger.reserve("first", "1", monthly_limit="10")
    with pytest.raises(BudgetExceeded):
        ledger.reserve("tight", "0.1", monthly_limit="0.5")
    with pytest.raises(BudgetExceeded):
        BudgetLedger(ops).reserve("old-config", "0.1", monthly_limit="10")
    assert ledger.account("month:" + datetime.utcnow().strftime("%Y-%m"))["limit"] == Decimal("0.5")


@pytest.fixture
def ops_client(ops, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.identity import Principal, _principal
    from apps.api.routers import jobs, verification

    state = {"principal": Principal("local-owner", None, "ADMIN", "local")}
    app = FastAPI()
    @app.middleware("http")
    async def identity(request, call_next):
        request.state.principal = state["principal"]
        token = _principal.set(state["principal"])
        try:
            return await call_next(request)
        finally:
            _principal.reset(token)
    app.include_router(jobs.router, prefix="/api")
    app.include_router(verification.router, prefix="/api")
    monkeypatch.setattr(jobs, "get_runner", lambda: type("Runner", (), {"submit": lambda *a: None})())
    with TestClient(app) as client:
        yield client, state


def test_status_api_never_exposes_untrusted_partial_text_or_secrets(ops, ops_client):
    client, _ = ops_client
    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    forbidden = ["SEALED_SENTINEL", "HIDDEN_SENTINEL", "PROVIDER_SECRET_SENTINEL"]
    store.checkpoint(lease, document={"document_id": run.document_ids[0],
        "filename": forbidden[0], "sealed_excerpt": forbidden[0],
        "pages": [{"blocks": [{"text": forbidden[1], "visible": False}]}],
        "engine_data": {"api_key": forbidden[2]},
        "findings": [{"sealed_excerpt": forbidden[0], "detail": forbidden[1]}]})
    store.checkpoint(lease, execution={"provider": forbidden[2], "model": forbidden[2],
        "error": forbidden[2], "quarantine_reasons": forbidden, "text": forbidden[0], "ok": False})
    store.fail(lease, forbidden[2])
    response = client.get(f"/api/verification-runs/{run.id}/job")
    assert response.status_code == 200
    assert all(secret not in response.text for secret in forbidden)
    summary = response.json()["history"][0]["partial_result"]["documents"][0]
    assert summary["finding_count"] == 1 and summary["page_count"] == 1
    with ops() as session:
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.run_id == run.id))
        assert attempt.partial_result["documents"][0]["sealed_excerpt"] == forbidden[0]


def test_jobs_api_resolves_project_and_requires_member_for_mutations(ops, ops_client):
    from apps.api.identity import Principal
    client, state = ops_client
    run = seeded_run(ops)
    with ops() as session:
        session.add(db.Organization(id="org", name="Org"))
        session.flush()
        session.add(db.User(id="viewer", email="viewer@example.invalid", organization_id="org", role="VIEWER"))
        session.flush()
        session.get(Project, run.project_id).organization_id = "org"
        session.add(db.ProjectMember(project_id=run.project_id, user_id="viewer", role="VIEWER"))
        session.commit()
    state["principal"] = Principal("viewer", "org", "VIEWER", "token")
    assert client.get(f"/api/verification-runs/{run.id}/job").status_code == 200
    assert client.post(f"/api/verification-runs/{run.id}/cancel").status_code == 403
    assert client.post(f"/api/verification-runs/{run.id}/retry").status_code == 403
    state["principal"] = Principal("outsider", "elsewhere", "ADMIN", "token")
    assert client.get(f"/api/verification-runs/{run.id}/job").status_code == 404
    state["principal"] = None
    assert client.get(f"/api/verification-runs/{run.id}/job").status_code == 401


def test_cancel_retry_api_contract_and_actor(ops, ops_client):
    client, _ = ops_client
    run = seeded_run(ops)
    assert client.post(f"/api/verification-runs/{run.id}/retry").status_code == 409
    cancelled = client.post(f"/api/verification-runs/{run.id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "CANCELLED"
    retried = client.post(f"/api/verification-runs/{run.id}/retry")
    assert retried.status_code == 202 and retried.json()["id"] != run.id
    assert retried.json()["input_snapshot"] == cancelled.json()["input_snapshot"]
    again = client.post(f"/api/verification-runs/{run.id}/retry")
    assert again.json()["id"] == retried.json()["id"]
    with ops() as session:
        check = session.scalar(select(db.VerificationCheck).where(db.VerificationCheck.name == "CANCEL"))
        assert check.detail["actor"] == "local-owner"


def test_legacy_review_updates_structured_workflow_then_rejects_stale_legacy_edit(ops, ops_client):
    from apps.api.workspace import FindingWorkflow
    client, _ = ops_client
    run = seeded_run(ops)
    with ops() as session:
        session.add(db.FindingRow(id="finding", run_id=run.id, project_id=run.project_id,
            type="ARITHMETIC_MISMATCH", status="UNVERIFIED", severity="LOW", evidence_grade="U", confidence=0.1))
        session.commit()
    response = client.patch("/api/findings/finding/review", json={
        "review_status": "ACCEPTED", "note": "Keep this note", "reviewer": "forged"})
    assert response.status_code == 200
    with ops() as session:
        workflow = session.get(FindingWorkflow, "finding")
        assert workflow.revision == 1 and workflow.decision == "AGREED"
        assert workflow.updated_by == "local-owner" and workflow.note == "Keep this note"
    assert client.patch("/api/findings/finding/review", json={"review_status": "FALSE_POSITIVE"}).status_code == 409


def test_reported_usage_on_failed_response_is_settled(ops, monkeypatch):
    router, _ = model_router(ops, monkeypatch, LLMResponse(False, input_tokens=100, output_tokens=10, error="rejected"))
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "user")))
    assert not result.used and result.executions[0].cost_status == "REPORTED"
    assert BudgetLedger(ops).account("run:model-run")["spent"] == Decimal("0.00028")
    assert BudgetLedger(ops).account("run:model-run")["reserved"] == 0


def test_sub_microdollar_cost_is_visible_in_total():
    from packages.llm_router.router import ModelExecution, RouterResult
    result = RouterResult(executions=[ModelExecution("role", "provider", "model", True, cost_usd=0.0000002)])
    assert result.total_cost == 0.0000002


def test_stale_worker_cannot_append_audit_events(ops):
    from apps.worker.runtime import FencedAuditSink
    from packages.audit_engine import AuditChain
    from packages.common.enums import AuditEventType
    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    store.cancel(run.id)
    with pytest.raises(JobOwnershipLost):
        AuditChain(sink=FencedAuditSink(store, lease)).record(AuditEventType.VERIFICATION, {"late": True})
    with ops() as session:
        assert session.scalar(select(func.count()).select_from(db.AuditEventRow)) == 0


def test_concurrent_local_dispatch_respects_capacity(ops, monkeypatch):
    import threading
    import apps.api.services as services
    first, second = seeded_run(ops), seeded_run(ops)
    runner = JobRunner(JobStore(ops))
    monkeypatch.setenv("LV_JOB_CONCURRENCY", "1")
    barrier = threading.Barrier(2)
    release = threading.Event()
    original = runner.store.acquire_dispatch
    def acquire(run_id, **kwargs):
        barrier.wait(timeout=10)
        return original(run_id, **kwargs)
    monkeypatch.setattr(runner.store, "acquire_dispatch", acquire)
    monkeypatch.setattr(services, "execute_run", lambda *args, **kwargs: release.wait(10))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            modes = list(pool.map(runner.submit, [first.id, second.id]))
        assert sorted(modes) == ["inprocess", "queued"]
        assert sum(t.is_alive() for t in runner._threads.values()) == 1
    finally:
        release.set()
        runner.stop()


@pytest.mark.parametrize("saved_policy,forced,blocked,expected", [
    ("ORIGINAL", "LOCAL_ONLY", [], "LOCAL_ONLY"),
    ("ORIGINAL", None, ["openai"], "ORIGINAL"),
    ("LOCAL_ONLY", "ORIGINAL", [], "LOCAL_ONLY"),
])
def test_queued_run_obeys_current_organization_restrictions(ops, monkeypatch, saved_policy, forced, blocked, expected):
    with ops() as session:
        session.add(db.Organization(id="org", name="Org"))
        session.commit()
    run = seeded_run(ops, organization_id="org", policy=saved_policy)
    with ops() as session:
        organization = session.get(db.Organization, "org")
        organization.forced_ai_policy, organization.blocked_providers = forced, blocked
        session.commit()
    _, provider = model_router(ops, monkeypatch, LLMResponse(True, text="not permitted"))

    def pipeline(self, run_id, context, documents, **kwargs):
        assert str(context.external_ai_policy) == expected
        self.router.providers = {"openai": provider}
        result = asyncio.run(self.router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "raw data"),
                                             policy=context.external_ai_policy))
        assert not result.used
        return completed(run)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=JobStore(ops))
    assert provider.calls == 0
    assert JobStore(ops).status(run.id)["state"] == "COMPLETED"
    with ops() as session:
        assert session.get(DurableJob, run.id).snapshot["context"]["external_ai_policy"] == saved_policy


@pytest.mark.parametrize("forced,blocked", [("MASKED", []), ("LOCAL_ONLY", []), (None, ["openai"])])
def test_org_restriction_changed_after_request_preparation_blocks_dispatch(ops, monkeypatch, forced, blocked):
    with ops() as session:
        session.add(db.Organization(id="org", name="Org"))
        session.commit()
    run = seeded_run(ops, organization_id="org", policy="ORIGINAL")
    _, provider = model_router(ops, monkeypatch, LLMResponse(True, text="not permitted"))

    def pipeline(self, run_id, context, documents, **kwargs):
        self.router.providers = {"openai": provider}
        with ops() as session:
            organization = session.get(db.Organization, "org")
            organization.forced_ai_policy, organization.blocked_providers = forced, blocked
            session.commit()
        response = asyncio.run(self.router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "raw data"),
                                               policy=context.external_ai_policy))
        assert response.executions[0].cost_status == "NOT_SENT"
        assert response.executions[0].error.startswith("PROVIDER_POLICY_BLOCKED")
        with ops() as session:
            organization = session.get(db.Organization, "org")
            organization.forced_ai_policy, organization.blocked_providers = None, []
            session.commit()
        response = asyncio.run(self.router.run(LLMRole.PRIMARY_REASONER, LLMRequest("system", "raw data"),
                                               policy=context.external_ai_policy))
        assert response.executions[0].cost_status == "NOT_SENT"
        return completed(run)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=JobStore(ops))
    assert provider.calls == 0
    assert JobStore(ops).status(run.id)["state"] == "COMPLETED"
    assert BudgetLedger(ops).account("run:" + run.id)["reserved"] == 0


def test_removed_organization_fails_closed_before_pipeline(ops, monkeypatch):
    with ops() as session:
        session.add(db.Organization(id="org", name="Org"))
        session.commit()
    run = seeded_run(ops, organization_id="org", policy="ORIGINAL")
    with ops() as session:
        session.get(Project, run.project_id).organization_id = None
        session.get(DurableJob, run.id).max_attempts = 1
        session.flush()
        session.delete(session.get(db.Organization, "org"))
        session.commit()
    called = []
    monkeypatch.setattr(VerificationPipeline, "run", lambda *a, **kw: called.append(True))
    execute_run(run.id, store=JobStore(ops))
    assert called == [] and JobStore(ops).status(run.id)["state"] == "FAILED"


def test_server_captures_submitter_and_worker_audit_does_not_impersonate_client(ops, ops_client, monkeypatch):
    from apps.api.routers import verification
    from apps.worker.runtime import FencedAuditSink
    from packages.audit_engine import AuditChain
    from packages.common.enums import AuditEventType
    client, _ = ops_client
    template = seeded_run(ops, enqueue=False)
    monkeypatch.setattr(verification, "get_runner", lambda: type("Runner", (), {"submit": lambda *a: None})())
    response = client.post(f"/api/projects/{template.project_id}/verify", json={
        "submission": {"actor_id": "forged", "api_key": "REQUEST_SECRET_SENTINEL"}})
    assert response.status_code == 202
    run_id = response.json()["id"]
    with ops() as session:
        run = session.get(VerificationRun, run_id)
        assert run.input_snapshot["submission"]["actor_id"] == "local-owner"
        assert "forged" not in str(run.input_snapshot) and "REQUEST_SECRET_SENTINEL" not in str(run.input_snapshot)

    def pipeline(self, *args, **kwargs):
        self.audit.record(AuditEventType.VERIFICATION, {"stage": "TEST"}, actor="forged")
        return completed(run)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    store = JobStore(ops)
    execute_run(run_id, store=store)
    with ops() as session:
        events = list(session.scalars(select(db.AuditEventRow)))
        assert len(events) >= 2
        assert all(event.actor == "system:worker" for event in events)
        assert all(event.payload["submission"]["actor_id"] == "local-owner" for event in events)
    assert AuditChain(sink=FencedAuditSink(store, None)).verify()["valid"]


def test_restricted_completion_is_not_reused_under_the_original_policy(ops, monkeypatch):
    with ops() as session:
        session.add(db.Organization(id="org", name="Org"))
        session.commit()
    run = seeded_run(ops, organization_id="org", policy="ORIGINAL")
    with ops() as session:
        session.get(db.Organization, "org").forced_ai_policy = "LOCAL_ONLY"
        session.commit()
    monkeypatch.setattr(VerificationPipeline, "run", lambda *a, **kw: completed(run))
    execute_run(run.id, store=JobStore(ops))
    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        assert saved.state == "COMPLETED" and saved.result_json["security_restricted"]
        assert saved.result_json["effective_security"]["external_ai_policy"] == "LOCAL_ONLY"
        assert saved.input_snapshot["context"]["external_ai_policy"] == "ORIGINAL"
        assert session.get(DurableJob, run.id).dedup_key is None
        session.get(db.Organization, "org").forced_ai_policy = None
        session.commit()
        candidate = VerificationRun(project_id=run.project_id, document_ids=run.document_ids,
            profile=run.profile, verification_key=run.verification_key, state="QUEUED",
            input_snapshot=copy.deepcopy(run.input_snapshot))
        child, reused = enqueue_run(session, candidate)
        session.commit()
        assert not reused and child.id != run.id


def test_heartbeat_survives_a_transient_renewal_failure(ops, monkeypatch):
    """일시적 DB 오류 하나로 임차를 버리지 않는다.

    이 회귀는 실제 배포에서 관찰되었다. 갱신 쓰기가 한 번 실패하면 갱신
    스레드가 끝났고, 임차가 만료되면 작업은 늘 같은 단계에서 재시도로
    되돌아갔다. 사용자에게는 특정 지점에서 반복 중단되는 것으로 보인다.

    시간은 주입 시계로 진행한다(벽시계 0.45초 임차는 CI run 36092298978에서 러너 지연으로 실패).
    """
    from apps.worker.runtime import heartbeat

    run = seeded_run(ops)
    clock = ManualClock()
    store = JobStore(ops, clock=clock, lease_seconds=0.45)
    lease = store.claim(run.id)
    original, calls = store.heartbeat, []

    def flaky(current):
        calls.append(current)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return original(current)

    monkeypatch.setattr(store, "heartbeat", flaky)
    ticker = Ticker()
    try:
        with heartbeat(store, lease, monotonic=clock.monotonic, pause=ticker.pause) as check:
            clock.advance(0.15)  # 갱신 간격(임차의 1/3)
            ticker.step()        # 첫 갱신: 일시 오류
            clock.advance(0.045)  # 재시도 간격(임차의 1/10)
            ticker.step()        # 재시도: 성공 → 임차 연장
            assert len(calls) == 2, "갱신 스레드가 첫 실패 뒤에도 살아 있어야 한다"
            clock.advance(0.4)   # 처음 임차(0.45초)는 지났지만 재시도로 연장된 임차는 남아 있다
            assert store.recover() == []
            check()
    finally:
        ticker.close()


def test_heartbeat_gives_up_when_ownership_is_actually_lost(ops):
    """소유권을 잃은 경우에는 즉시 포기하고 check()가 알린다."""
    from apps.worker.runtime import heartbeat
    from apps.api.job_control import JobOwnershipLost

    run = seeded_run(ops)
    clock = ManualClock()
    store = JobStore(ops, clock=clock, lease_seconds=0.3)
    lease = store.claim(run.id)
    ticker = Ticker()
    try:
        with heartbeat(store, lease, monotonic=clock.monotonic, pause=ticker.pause) as check:
            store.cancel(run.id)  # fence가 올라가 이 임차는 더 이상 유효하지 않다
            clock.advance(0.1)
            ticker.step(exits=Ticker.thread_for(run.id))  # 다음 갱신에서 소유권 상실을 확인하고 스레드가 끝난다
            with pytest.raises(JobOwnershipLost):
                check()
    finally:
        ticker.close()


def test_heartbeat_releases_the_job_after_a_full_lease_of_failures(ops, monkeypatch):
    """소유권과 무관한 실패라도 임차 기간 내내 갱신하지 못하면 작업을 놓는다(무한히 붙잡지 않는다)."""
    from apps.worker.runtime import heartbeat
    from apps.api.job_control import JobOwnershipLost

    run = seeded_run(ops)
    clock = ManualClock()
    store = JobStore(ops, clock=clock, lease_seconds=0.3)
    lease = store.claim(run.id)

    def always_locked(current):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "heartbeat", always_locked)
    ticker = Ticker()
    try:
        with heartbeat(store, lease, monotonic=clock.monotonic, pause=ticker.pause) as check:
            clock.advance(0.1)
            ticker.step()  # 실패 1회: 아직 임차 기간 안이라 재시도한다
            check()
            clock.advance(0.25)  # 마지막 성공(시작) 뒤 0.35초 > 임차 0.3초
            ticker.step(exits=Ticker.thread_for(run.id))
            with pytest.raises(JobOwnershipLost):
                check()
    finally:
        ticker.close()


def test_lease_renewal_failure_schedules_the_retry_without_waiting_for_expiry(ops, monkeypatch):
    """갱신이 끊기면 만료를 기다리지 않고 곧바로 다음 시도를 예약한다."""
    from apps.api.job_control import JobOwnershipLost

    run = seeded_run(ops)
    store = JobStore(ops, lease_seconds=30, backoff_seconds=0)

    def pipeline(*args, **kwargs):
        raise JobOwnershipLost(run.id)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    execute_run(run.id, store=store)
    status = store.status(run.id)
    assert status["state"] == "BACKOFF", "임차 만료를 기다리며 멈춰 있으면 안 된다"
    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        assert saved.state == "QUEUED" and "다시 시도" in (saved.stage_message or "")


def test_a_second_run_waits_its_turn_and_says_so(ops, monkeypatch):
    """동시 실행 1에서 두 번째 검증은 대기하되, 대기 중임을 화면에 알린다.

    안내가 없으면 화면은 시작조차 못한 것과 멈춘 것을 구분할 수 없다.
    """
    monkeypatch.setenv("LV_JOB_CONCURRENCY", "1")
    first, second = seeded_run(ops), seeded_run(ops)
    store = JobStore(ops)
    runner = JobRunner(store)
    started, release = threading.Event(), threading.Event()

    def pipeline(self, run_id, *args, **kwargs):
        if run_id == first.id:
            started.set()
            release.wait(10)
        return completed(first if run_id == first.id else second)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    try:
        assert runner.submit(first.id) == "inprocess"
        assert started.wait(10)
        assert runner.submit(second.id) == "queued"
        with ops() as session:
            waiting = session.get(VerificationRun, second.id)
            assert waiting.state == "QUEUED"
            assert "기다" in waiting.stage_message or "시작합니다" in waiting.stage_message
        release.set()
        runner.wait(first.id, 15)
        runner.wait(second.id, 15)
    finally:
        release.set()
        runner.stop()
    assert store.status(first.id)["state"] == "COMPLETED"
    assert store.status(second.id)["state"] == "COMPLETED", "대기하던 검증이 결국 실행되어야 한다"


def test_defer_never_overwrites_a_running_run_message(ops):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.claim(run.id)
    store.progress.__self__  # 소유 중인 작업은 READY가 아니다
    assert store.defer(run.id, 1) is False


def test_checkpoint_stores_counts_not_the_whole_document(ops, monkeypatch, tmp_path):
    """체크포인트가 문서 결과 전체를 직렬화하면 임차 갱신이 밀린다.

    600문단 문서에서 17MB가 나왔고, 그 값은 JSON 칼럼에 들어가며 한 번 더
    직렬화된다. json.dumps/loads는 그동안 GIL을 놓지 않으므로 갱신 스레드가
    실행되지 못하고, 작업은 WORKER_LEASE_EXPIRED로 회수되어 처음부터 다시
    실행된다. 실제 배포에서 그렇게 실패했다.

    재개에 쓰이지도 않는다. 읽히는 것은 건수뿐이다.
    """
    from apps.api.job_control import JobAttempt

    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    store.checkpoint(lease, document={"document_id": "doc-1", "finding_count": 1800,
                                      "page_count": 42, "quarantined": False})
    with ops() as session:
        attempt = session.execute(select(JobAttempt).where(
            JobAttempt.run_id == run.id, JobAttempt.fence == lease.fence)).scalar_one()
        stored = json.dumps(attempt.partial_result, ensure_ascii=False)
        assert len(stored) < 4096, f"체크포인트가 {len(stored)}바이트로 커졌습니다"
        document = attempt.partial_result["documents"][0]
        assert "findings" not in document and "engine_data" not in document


def test_partial_summary_still_reads_old_checkpoint_rows(ops):
    """예전 행은 목록을 담고 있다. 그 행의 건수도 그대로 읽혀야 한다."""
    from apps.api.job_control import _partial_summary

    legacy = {"documents": [{"document_id": "d1", "findings": [{}, {}, {}],
                             "pages": [{}], "quarantined": True}]}
    compact = {"documents": [{"document_id": "d1", "finding_count": 3,
                              "page_count": 1, "quarantined": True}]}
    assert _partial_summary(legacy, {"d1"}) == _partial_summary(compact, {"d1"})
    assert _partial_summary(compact, {"d1"})["documents"][0]["finding_count"] == 3


class ManualClock:
    """시험용 시계. 벽시계 대신 명시적으로 시간을 흘려, 러너 속도와 무관하게 임차 판정을 검증한다."""

    def __init__(self):
        self.now = datetime.utcnow()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    def monotonic(self):
        """갱신 스레드용 단조 시계. 같은 시험 시계에서 초 단위로 읽는다."""
        return (self.now - datetime(2000, 1, 1)).total_seconds()


class Ticker:
    """갱신 스레드의 대기(pause)를 대신한다. step()을 부를 때마다 스레드가 한 번 갱신하고 다시 멈춘다.

    기다림의 상한(timeout)은 스레드가 멈춤 지점에 닿기를 기다리는 한도일 뿐, 판정에 쓰는 시간이 아니다.
    """

    def __init__(self, timeout=10):
        self.ready = threading.Semaphore(0)
        self.go = threading.Semaphore(0)
        self.done = threading.Event()
        self.timeout = timeout

    def pause(self, seconds):
        self.ready.release()
        self.go.acquire()
        return self.done.is_set()

    def step(self, *, exits=None):
        """exits: 이번 갱신에서 끝나야 하는 갱신 스레드. 주면 그 스레드가 끝날 때까지 기다린다."""
        assert self.ready.acquire(timeout=self.timeout), "갱신 스레드가 대기 지점에 오지 않았다"
        self.go.release()
        if exits is not None:
            exits.join(self.timeout)
            assert not exits.is_alive(), "갱신 스레드가 끝나지 않았다"
            return
        assert self.ready.acquire(timeout=self.timeout), "갱신 뒤 스레드가 다시 대기하지 않았다"
        self.ready.release()  # 다음 step이 쓸 대기 신호를 되돌려 둔다

    @staticmethod
    def thread_for(run_id):
        return next(t for t in threading.enumerate() if t.name == "lease-" + run_id)

    def close(self):
        self.done.set()
        self.go.release()


def test_progress_updates_keep_the_lease_alive(ops):
    """진행 기록은 일이 나아가고 있다는 증거다. 그것으로 임차가 연장돼야 한다.

    갱신 스레드는 CPU 경합이나 GIL을 오래 쥐는 구간에 밀릴 수 있다. 생존
    판정을 그 스레드 하나에만 맡기면, 정상 실행 중인 작업이 회수되어
    처음부터 다시 실행된다. 실제 배포에서 그렇게 실패했다.

    시간은 주입 시계로 흘린다. 벽시계(time.sleep)로 재면 러너 지연이 판정에 섞여 CI에서 실패했다
    (run 36090264005).
    """
    from packages.common.enums import JobState

    run = seeded_run(ops)
    clock = ManualClock()  # 작업 등록(available_at) 뒤에서 시작한다
    store = JobStore(ops, clock=clock, lease_seconds=0.4)
    lease = store.claim(run.id)
    for _ in range(4):
        clock.advance(0.25)
        store.progress(lease, JobState.VERIFYING, "분석 중", 0.5)
        assert store.recover() == [], "진행 중인 작업이 회수되면 안 된다"
    store.check(lease)  # 1초가 지났지만 0.4초 임차는 살아 있다

    clock.advance(0.5)  # 아무 진전이 없으면 종전대로 회수된다
    assert store.recover() == [run.id]


def test_progress_after_lease_expiry_loses_ownership(ops):
    """진행 기록이 임차 만료 뒤에 오면 연장하지 않고 소유권 상실을 알린다(만료된 작업을 되살리지 않는다)."""
    from apps.api.job_control import JobOwnershipLost
    from packages.common.enums import JobState

    run = seeded_run(ops)
    clock = ManualClock()  # 작업 등록(available_at) 뒤에서 시작한다
    store = JobStore(ops, clock=clock, lease_seconds=0.4)
    lease = store.claim(run.id)
    clock.advance(0.41)
    with pytest.raises(JobOwnershipLost):
        store.progress(lease, JobState.VERIFYING, "분석 중", 0.5)
    assert store.recover() == [run.id]


def test_claim_lease_starts_after_the_write_lock_is_acquired(ops, monkeypatch):
    """쓰기 잠금을 기다린 시간만큼 임차가 줄면 안 된다. 잠금을 얻은 뒤의 시각으로 만료를 정한다."""
    from contextlib import contextmanager

    from apps.api import job_control
    from packages.common.enums import JobState

    run = seeded_run(ops)
    clock = ManualClock()  # 작업 등록(available_at) 뒤에서 시작한다
    original = job_control.write_session

    @contextmanager
    def slow_lock(factory=None, **kwargs):
        clock.advance(0.3)  # 다른 쓰기가 잠금을 쥐고 있어 0.3초를 기다린 상황
        with original(factory, **kwargs) as session:
            yield session

    store = JobStore(ops, clock=clock, lease_seconds=0.4)
    monkeypatch.setattr(job_control, "write_session", slow_lock)
    lease = store.claim(run.id)
    claimed_at = clock()
    monkeypatch.setattr(job_control, "write_session", original)
    with ops() as session:
        expires = session.get(DurableJob, run.id).lease_expires_at
    assert expires == claimed_at + timedelta(seconds=0.4)
    clock.advance(0.35)  # 잠금 전 시각 기준이었다면 이미 만료(0.3 + 0.35 > 0.4)
    store.progress(lease, JobState.VERIFYING, "분석 중", 0.5)


def test_generic_write_session_does_not_touch_ledger_schema(tmp_path):
    """원장 표 확인은 원장 연산에서만 한다. 작업 관리 쓰기 경로에 스키마 검사를 끼우지 않는다."""
    from sqlalchemy import inspect

    from packages.llm_router.budget import BudgetLedger, write_session

    engine = create_engine(f"sqlite:///{tmp_path / 'generic.db'}")
    factory = sessionmaker(engine)
    with write_session(factory):
        pass
    assert "budget_accounts" not in inspect(engine).get_table_names()
    # 원장 읽기는 표를 만들고, 표가 없다는 이유로 '예산 소진'이 되지 않는다
    assert BudgetLedger(factory).account("month:2026-01")["spent"] == 0
    assert "budget_accounts" in inspect(engine).get_table_names()


def test_progress_writes_are_batched_within_a_stage(ops):
    """파이프라인은 인용 한 건마다 진행을 알린다. 문서 하나에 5천 번을 넘겼고,
    그때마다 쓰기 트랜잭션과 VerificationCheck 행이 생겼다. 그 쓰기가 SQLite
    쓰기 잠금을 계속 쥐어 임차 갱신 스레드가 끼어들지 못했다.
    """
    from apps.api.db import VerificationCheck
    from packages.common.enums import JobState

    run = seeded_run(ops)
    store = JobStore(ops)
    store.progress_min_seconds = 5.0
    lease = store.claim(run.id)

    assert store.progress(lease, JobState.VERIFYING, "1/500", 0.10) is True
    for index in range(2, 60):
        assert store.progress(lease, JobState.VERIFYING, f"{index}/500", 0.11) is False
    # 단계가 바뀌면 묶음과 무관하게 반드시 기록한다.
    assert store.progress(lease, JobState.CROSS_CHECKING, "교차검증", 0.85) is True

    with ops() as session:
        rows = session.scalars(select(VerificationCheck).where(
            VerificationCheck.run_id == run.id)).all()
        names = [r.name for r in rows if r.name in {"VERIFYING", "CROSS_CHECKING"}]
        assert names == ["VERIFYING", "CROSS_CHECKING"], names
        saved = session.get(VerificationRun, run.id)
        assert saved.stage_message == "교차검증"


def test_progress_batching_never_outlasts_the_lease(ops):
    """묶음 간격이 임차에 가까워지면 진행 기록이 생존 증거 구실을 못 한다."""
    store = JobStore(ops, lease_seconds=2.0)
    store.progress_min_seconds = 99.0  # 설정이 잘못돼도
    assert JobStore(ops, lease_seconds=2.0).progress_min_seconds <= 0.2


def test_batched_audit_events_form_the_same_chain(ops):
    """감사기록은 법정 기록이다. 묶어 쓰되 체인은 하나씩 쓴 것과 같아야 한다."""
    from packages.audit_engine import AuditChain
    from packages.common.enums import AuditEventType

    items = [(AuditEventType.API_QUERY, {"adapter": "law_go_kr", "n": i}) for i in range(6)]

    one_by_one = AuditChain()
    for event_type, payload in items:
        one_by_one.record(event_type, payload)
    batched = AuditChain()
    batched.record_many(items)

    single, many = one_by_one.sink.all(), batched.sink.all()
    assert [e.sequence for e in single] == [e.sequence for e in many] == list(range(1, 7))
    assert [e.event_hash for e in single] == [e.event_hash for e in many]
    assert all(many[i].event_hash == many[i + 1].previous_hash for i in range(len(many) - 1))


def test_result_payload_matches_the_json_export(ops):
    """DB에 넣을 때 문자열로 만들었다가 다시 읽지 않는다. 내용은 같아야 한다."""
    from packages.report_engine import to_json, to_payload

    run = seeded_run(ops)
    result = completed(run)
    assert to_payload(result) == json.loads(to_json(result).decode("utf-8"))


def test_result_response_keeps_its_shape_without_duplicating_columns(ops):
    """전용 칼럼과 result_json에 같은 값을 두 벌 담지 않는다.

    한 건에 수 MB가 중복되고 그만큼 직렬화 비용과 메모리가 늘어난다.
    다만 밖에서 보이는 응답 모양은 그대로여야 한다.
    """
    from apps.api.services import RESULT_COLUMN_KEYS, persist_result, run_result_view
    from packages.report_engine import to_payload

    run = seeded_run(ops)
    store = JobStore(ops)
    lease = store.claim(run.id)
    result = completed(run)
    result.timeline = [{"date": "2021-03-25", "label": "약정"}]
    result.unverified_items = [{"kind": "citation", "citation_id": "c1"}]

    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        persist_result(session, saved, result, lease=lease, store=store, commit=False)
        session.commit()

    with ops() as session:
        saved = session.get(VerificationRun, run.id)
        for key in RESULT_COLUMN_KEYS:
            assert key not in saved.result_json, f"{key}가 중복 저장됐습니다"
        view = run_result_view(saved)
        assert set(to_payload(result)) <= set(view), "응답에서 빠진 항목이 있습니다"
        assert view["scores"] == result.scores
        assert view["timeline"] == result.timeline
        assert view["unverified_items"] == result.unverified_items
