"""Shared execution path for local threads and the existing verification.run task."""
from __future__ import annotations

import copy
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from apps.api.audit_sink import DBAuditSink, MAX_APPEND_ATTEMPTS, _SEQUENCE_LOCK
from apps.api.db import VerificationRun
from apps.api.job_control import (DurableJob, JobConflict, JobOwnershipLost, JobStore,
                                  execution_security, restricted_policy, snapshot_hash)
from packages.audit_engine import AuditChain, AuditChainConflict
from packages.common.config import ProviderConfig, get_settings
from packages.common.enums import AuditEventType, ExternalAIPolicy, VerificationProfile
from packages.common.storage import get_storage, sha256_file
from packages.llm_router import LLMRouter
from packages.llm_router.budget import BudgetLedger, write_session
from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline

log = logging.getLogger(__name__)


@contextmanager
def heartbeat(store, lease, *, monotonic=time.monotonic, pause=None):
    """임차 갱신이 한 번 실패했다고 작업을 포기하지 않는다.

    갱신은 DB 쓰기다. SQLite 쓰기 잠금 경합, 커넥션 일시 끊김처럼
    소유권과 무관한 이유로도 실패한다. 예전에는 그 한 번으로 갱신
    스레드가 끝났고, 임차가 만료되면 작업은 늘 같은 단계에서 재시도로
    되돌아갔다. 사용자에게는 특정 지점에서 반복 중단되는 것으로 보인다.

    소유권을 실제로 잃은 경우에만 즉시 포기한다. 그 밖의 실패는 임차가
    남아 있는 동안 짧은 간격으로 다시 시도하고, 임차 기간을 통째로
    갱신하지 못했을 때 비로소 포기한다.

    monotonic·pause는 시험용 주입점이다(기본: time.monotonic, 멈춤 신호를 기다리는 Event.wait).
    pause(초)는 그만큼 기다린 뒤 멈춰야 하면 True를 돌려준다. 시험은 이것으로 갱신을 한 박자씩 진행해
    러너 속도와 무관하게 판정한다.
    """
    stop = threading.Event()
    lost = threading.Event()
    pause = pause or stop.wait
    interval = max(0.02, store.lease_seconds / 3)
    retry_interval = max(0.02, min(interval, store.lease_seconds / 10))
    state = {"ok_at": monotonic(), "error": ""}

    def expired():
        return monotonic() - state["ok_at"] >= store.lease_seconds

    def beat():
        wait = interval
        while not (stop.is_set() or pause(wait)):
            try:
                store.heartbeat(lease)
            except JobOwnershipLost:
                state["error"] = "다른 워커가 작업을 이어받았습니다"
                log.warning("임차 갱신 중단(%s): 소유권 상실", lease.run_id)
                lost.set()
                return
            except Exception as exc:
                state["error"] = f"{type(exc).__name__}: {exc}"
                # 실패 이유를 남긴다. 메모리에만 두면 회수된 뒤에는 무엇 때문에
                # 갱신이 끊겼는지 알 수 없고, 남는 것은 WORKER_LEASE_EXPIRED뿐이다.
                log.warning("임차 갱신 실패(%s, 마지막 성공 %.0f초 전): %s",
                            lease.run_id, monotonic() - state["ok_at"], state["error"])
                if expired():
                    log.error("임차 갱신을 %.0f초 동안 하지 못해 작업을 놓습니다(%s): %s",
                              store.lease_seconds, lease.run_id, state["error"])
                    lost.set()
                    return
                wait = retry_interval  # 일시적 장애로 보고 더 자주 다시 시도한다
                continue
            late = monotonic() - state["ok_at"] - interval
            if late > interval:
                # 예외 없이 늦었다면 스레드가 밀린 것이다. CPU 경합이나 GIL을
                # 오래 쥐는 구간이 있다는 뜻이고, 원인이 전혀 다르다.
                log.warning("임차 갱신이 %.0f초 늦었습니다(%s). 갱신 스레드가 밀리고 있습니다",
                            late, lease.run_id)
            state["ok_at"], state["error"] = monotonic(), ""
            wait = interval

    thread = threading.Thread(target=beat, daemon=True, name="lease-" + lease.run_id)
    thread.start()
    # 확인 간격의 하한. check()는 인용 한 건마다, 외부 조회 중에는 초당
    # 한 번 불린다. 매번 DB에 물으면 문서 하나에 수천 번의 조회가 된다.
    # 취소 감지가 1초 늦어지는 것은 화면 폴링 주기보다 짧아 드러나지 않는다.
    check_min = max(0.0, float(os.getenv("LV_JOB_CHECK_MIN_SECONDS", "1.0")))
    last_check = [float("-inf")]
    try:
        def check():
            if lost.is_set():
                raise JobOwnershipLost(f"{lease.run_id}: {state['error'] or '임차 갱신 실패'}")
            now = monotonic()
            if now - max(last_check[0], state["ok_at"]) < check_min:
                return
            try:
                store.check(lease)
                last_check[0] = monotonic()
            except JobOwnershipLost:
                raise
            except Exception:
                # 확인이 실패한 것과 소유권을 잃은 것은 다르다.
                # 최근 갱신이 살아 있으면 일시적 장애로 보고 진행한다.
                if expired():
                    raise
        yield check
    finally:
        stop.set()
        thread.join(timeout=5)


class FencedAuditSink:
    def __init__(self, store, lease):
        self.store, self.lease = store, lease

    def last(self):
        with self.store.session() as session:
            return DBAuditSink(session).last()

    def all(self):
        with self.store.session() as session:
            return DBAuditSink(session).all()

    def append(self, event):
        with write_session(self.store.factory) as session:
            self.store.fence(session, self.lease)
            DBAuditSink(session).append(event)

    def append_chained(self, build):
        for _ in range(MAX_APPEND_ATTEMPTS):
            try:
                with _SEQUENCE_LOCK, write_session(self.store.factory) as session:
                    self.store.fence(session, self.lease)
                    sink = DBAuditSink(session)
                    event = build(sink.last())
                    sink.append(event)
                    return event
            except IntegrityError:
                continue
        raise AuditChainConflict("Concurrent audit writers exhausted retries")

    def append_chained_many(self, builds):
        """여러 이벤트를 한 트랜잭션에 잇는다. fence도 한 번만 지난다."""
        for _ in range(MAX_APPEND_ATTEMPTS):
            try:
                with _SEQUENCE_LOCK, write_session(self.store.factory) as session:
                    self.store.fence(session, self.lease)
                    sink = DBAuditSink(session)
                    previous, created = sink.last(), []
                    for build in builds:
                        previous = build(previous)
                        sink.add(previous)
                        created.append(previous)
                    return created
            except IntegrityError:
                continue
        raise AuditChainConflict("Concurrent audit writers exhausted retries")


class WorkerAuditChain(AuditChain):
    def __init__(self, store, lease, submission):
        super().__init__(sink=FencedAuditSink(store, lease))
        self.run_id = lease.run_id
        self.submission = {key: submission.get(key) for key in ("actor_id", "organization_id", "authentication")}
        self.submission["actor_id"] = self.submission["actor_id"] or "system"

    def _builder(self, event_type, payload, **kwargs):
        """단건·묶음 양쪽이 같은 보강을 거치도록 여기서 감싼다."""
        kwargs["actor"] = "system:worker"
        return super()._builder(event_type, {**payload, "run_id": self.run_id,
                                             "submission": self.submission}, **kwargs)


def snapshot_settings(snapshot):
    current = get_settings()
    execution = snapshot["execution"]
    saved = execution["settings"]
    # These parsers still read global settings; refuse drift rather than silently retry new inputs.
    for name, value in saved.items():
        if name not in {"allow_network", "http_timeout"} and getattr(current, name) != value:
            raise ValueError("Snapshot execution setting changed: " + name)
    providers = {name: ProviderConfig(**value) for name, value in execution["providers"].items()}
    values = {**saved, "allow_network": saved["allow_network"] and current.allow_network}
    return replace(current, **values, providers=providers, pricing=copy.deepcopy(execution["pricing"]))


def execute(run_id, *, store=None):
    store = store or JobStore()
    store.ensure(run_id)
    lease = store.claim(run_id)
    if lease is None:
        return
    try:
        with heartbeat(store, lease) as check:
            with store.session() as session:
                job = session.get(DurableJob, run_id)
                run = session.get(VerificationRun, run_id)
                snapshot = copy.deepcopy(job.snapshot)
                key, project_id, budget_run_id = run.verification_key, run.project_id, job.budget_run_id
                if snapshot_hash(snapshot) != job.snapshot_hash:
                    raise ValueError("Durable snapshot integrity check failed")
                security = execution_security(session, project_id, snapshot["context"]["external_ai_policy"],
                                              saved=snapshot.get("security"))
            settings = snapshot_settings(snapshot)
            context = ProjectContext(**snapshot["context"])
            context.profile = VerificationProfile(context.profile)
            context.external_ai_policy = ExternalAIPolicy(security["external_ai_policy"])
            context.org_block_reveal = bool(context.org_block_reveal or security["block_sealed_reveal"])
            storage = get_storage()
            inputs = []
            for item in snapshot["documents"]:
                check()
                path = storage.path(item["storage_key"])
                if sha256_file(Path(path)) != item["sha256"]:
                    raise ValueError("Original bytes do not match the run snapshot")
                inputs.append(DocumentInput(document_id=item["document_id"], path=str(path),
                    filename=item["filename"], mime_type=item["mime_type"], sha256=item["sha256"],
                    is_own_document=item.get("is_own_document"), role=item.get("role")))

            class CheckpointPipeline(VerificationPipeline):
                def _run_document(self, *args, **kwargs):
                    check()
                    document = super()._run_document(*args, **kwargs)
                    # 체크포인트는 재개에 쓰이지 않는다. 읽히는 것은 건수뿐이다
                    # (_partial_summary). 그런데 예전에는 문서 결과 전체를
                    # 직렬화했다. 600문단 문서에서 17MB가 나왔고, 그 값이 JSON
                    # 칼럼에 들어가며 한 번 더 직렬화된다. json.dumps/loads는
                    # 그동안 GIL을 놓지 않으므로 임차 갱신 스레드가 실행되지
                    # 못한다. 0.5 CPU 배포에서 이 구간이 임차를 넘겨 작업이
                    # WORKER_LEASE_EXPIRED로 회수되고 처음부터 다시 실행됐다.
                    store.checkpoint(lease, document={
                        "document_id": document.document_id,
                        "finding_count": len(document.findings or []),
                        "page_count": len(getattr(document.normalized, "pages", None) or []),
                        "quarantined": bool(document.quarantined),
                    })
                    return document

            from apps.api.services import get_registry, link_snapshot_evidence, persist_result

            def provider_guard(provider, policy, *, session=None):
                def enforce(current_session):
                    try:
                        current = execution_security(current_session, project_id, context.external_ai_policy,
                                                     saved=security, lock=session is not None)
                    except JobConflict as exc:
                        raise PermissionError(str(exc)) from exc
                    security.update(current)
                    if set(current["blocked_providers"]).intersection({provider.name, provider.config.name}):
                        raise PermissionError("Provider is blocked by organization policy")
                    if (provider.config.kind != "local" and
                            restricted_policy(policy, current["external_ai_policy"]) != ExternalAIPolicy(policy)):
                        raise PermissionError("Request was prepared under a less restrictive AI policy")
                if session is not None:
                    enforce(session)
                else:
                    with store.session() as current_session:
                        enforce(current_session)

            router = LLMRouter(settings=settings, run_id=run_id, budget_run_id=budget_run_id,
                ledger=BudgetLedger(store.factory), limits=snapshot["execution"]["budget"],
                call_guard=check, dispatch_guard=lambda session: store.fence(session, lease),
                blocked_providers=security["blocked_providers"], provider_guard=provider_guard,
                on_execution=lambda execution: store.checkpoint(lease, execution=execution.to_dict()))
            audit = WorkerAuditChain(store, lease, snapshot.get("submission") or {})
            audit.record(AuditEventType.VERIFICATION, {"stage": "ATTEMPT_STARTED", "fence": lease.fence,
                         "effective_security": security}, project_id=project_id)
            pipeline = CheckpointPipeline(registry=get_registry(), router=router,
                                          audit=audit)
            pipeline.settings = settings
            result = pipeline.run(run_id, context, inputs,
                                  progress=lambda *args: store.progress(lease, *args), check=check)
            result.verification_key = key
            link_snapshot_evidence(result, snapshot)
            check()
            with write_session(store.factory) as session:
                store.fence(session, lease)
                run = session.get(VerificationRun, run_id)
                persist_result(session, run, result, lease=lease, store=store, commit=False)
                restricted = security != snapshot.get("security")
                run.result_json = {**run.result_json, "effective_security": copy.deepcopy(security),
                                   "security_restricted": restricted}
                store.complete(session, lease, result, reusable=not restricted)
    except JobOwnershipLost as exc:
        # 임차가 아직 살아 있다면 여기서 실패를 기록해야 만료를 기다리지 않고
        # 곧바로 다음 시도로 넘어간다. 그동안 화면은 마지막 단계에 멈춘 채로
        # 남아 이용자에게는 작업이 조용히 멈춘 것처럼 보였다.
        # 이미 다른 워커의 것이면 fence가 막으므로 남의 작업을 건드리지 않는다.
        try:
            store.fail(lease, f"LEASE_RENEWAL_FAILED: {exc}")
        except JobOwnershipLost:
            pass
        return
    except Exception as exc:
        try:
            store.fail(lease, str(exc))
        except JobOwnershipLost:
            pass
