"""Durable verification queue and fenced state transitions."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, or_, select, update
from sqlalchemy.exc import IntegrityError

from packages.common.config import get_settings
from packages.common.enums import ExternalAIPolicy
from packages.llm_router.budget import budget_settings, write_session

from .db import Base, Document, JSONType, Organization, Project, VerificationCheck, VerificationRun, get_session_factory
from .project_lifecycle import lock_project

TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "CANCELLED"}
READY = {"QUEUED", "BACKOFF"}


class JobOwnershipLost(BaseException):
    """Must escape the pipeline's per-document Exception handler."""


class JobConflict(ValueError):
    pass


def restricted_policy(*policies):
    order = {ExternalAIPolicy.ORIGINAL: 0, ExternalAIPolicy.MASKED: 1, ExternalAIPolicy.LOCAL_ONLY: 2}
    try:
        return max((ExternalAIPolicy(value) for value in policies if value), key=order.__getitem__)
    except (ValueError, TypeError):
        raise JobConflict("Invalid execution AI policy") from None


def execution_security(session, project_id, policy, *, saved=None, lock=False):
    """Workers enforce current restrictions without inventing an HTTP principal."""
    saved = saved or {}
    project = session.get(Project, project_id, with_for_update=lock)
    if project is None or project.deleted_at is not None:
        raise JobConflict("Execution project is unavailable")
    if saved.get("organization_id") and saved["organization_id"] != project.organization_id:
        raise JobConflict("Execution organization changed or was removed")
    organization = None
    if project.organization_id:
        organization = session.get(Organization, project.organization_id, with_for_update=lock)
        if organization is None:
            raise JobConflict("Execution organization policy is unavailable")
    blocked = saved.get("blocked_providers") or []
    current_blocked = (organization.blocked_providers or []) if organization else []
    if any(not isinstance(values, list) or any(not isinstance(value, str) for value in values)
           for values in (blocked, current_blocked)):
        raise JobConflict("Invalid organization provider policy")
    effective = restricted_policy(policy, saved.get("external_ai_policy"),
        project.external_ai_policy or "MASKED", organization.forced_ai_policy if organization else None)
    return {"organization_id": project.organization_id, "external_ai_policy": str(effective),
            "blocked_providers": sorted({value.lower() for value in [*blocked, *current_blocked]}),
            "block_sealed_reveal": bool(saved.get("block_sealed_reveal") or
                                         (organization and organization.block_sealed_reveal))}


class DurableJob(Base):
    __tablename__ = "durable_jobs"
    run_id = Column(String(40), ForeignKey("verification_runs.id"), primary_key=True)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False, index=True)
    snapshot = Column(JSONType, nullable=False)
    snapshot_hash = Column(String(64), nullable=False)
    dedup_key = Column(String(64), unique=True)
    retry_of = Column(String(40), unique=True)
    budget_run_id = Column(String(40), nullable=False)
    state = Column(String(24), nullable=False, default="QUEUED", index=True)
    owner = Column(String(64))
    fence = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    lease_expires_at = Column(DateTime, index=True)
    heartbeat_at = Column(DateTime)
    dispatch_until = Column(DateTime)
    task_id = Column(String(80))
    last_error = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (UniqueConstraint("run_id", "fence"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"), nullable=False, index=True)
    fence = Column(Integer, nullable=False)
    owner = Column(String(64), nullable=False)
    state = Column(String(24), nullable=False, default="RUNNING")
    error = Column(Text, default="")
    partial_result = Column(JSONType, nullable=False, default=dict)
    executions = Column(JSONType, nullable=False, default=list)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)


def snapshot_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def execution_settings_snapshot():
    settings = get_settings()
    from urllib.parse import urlsplit

    for provider in settings.providers.values():
        endpoint = urlsplit(provider.base_url)
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise JobConflict("Provider base URLs must not contain credentials, queries, or fragments")
    return {
        "providers": {name: asdict(provider) for name, provider in settings.providers.items()},
        "pricing": copy.deepcopy(settings.pricing),
        "budget": budget_settings(settings),
        "settings": {name: getattr(settings, name) for name in (
            "rule_version", "prompt_version", "allow_network", "http_timeout", "source_lookup_budget_seconds", "ocr_lang",
            "source_lookup_max_document_seconds", "source_lookup_recovery_seconds", "source_lookup_attempts",
            "ocr_psm", "ocr_dpi", "ocr_min_confidence", "ocr_max_pages", "ocr_timeout_seconds", "independent_ocr_pages",
            "independent_ocr_mode", "seal_meta_message_content", "allow_sealed_reveal")},
    }


def capture_snapshot(session, run):
    snapshot = copy.deepcopy(run.input_snapshot or {})
    if not snapshot.get("context"):
        raise JobConflict("Run input_snapshot.context is required; historical inputs cannot be inferred")
    if snapshot["context"].get("project_id") != run.project_id:
        raise JobConflict("Run snapshot project does not match the run")
    documents = {d.id: d for d in session.execute(select(Document).where(
        Document.project_id == run.project_id, Document.id.in_(run.document_ids or []))).scalars()}
    frozen = snapshot.get("documents", [])
    if (not frozen or len({d["document_id"] for d in frozen}) != len(frozen)
            or {d["document_id"] for d in frozen} != set(run.document_ids or [])
            or set(documents) != set(run.document_ids or [])):
        raise JobConflict("Run snapshot must contain exactly the selected project documents")
    for item in frozen:
        document = documents[item["document_id"]]
        if item.get("sha256") != document.sha256:
            raise JobConflict("Document changed since the run snapshot was created")
        item.setdefault("storage_key", document.storage_key)
        item.setdefault("mime_type", document.mime_type or "")
        # Ownership is per document. None preserves an explicitly unspecified value.
        item.setdefault("is_own_document", document.is_own_document)
    snapshot["context"]["profile"] = run.profile
    if "security" not in snapshot:
        snapshot["security"] = execution_security(session, run.project_id,
                                                  snapshot["context"]["external_ai_policy"])
        snapshot["context"]["external_ai_policy"] = snapshot["security"]["external_ai_policy"]
        snapshot["context"]["org_block_reveal"] = bool(snapshot["context"].get("org_block_reveal") or
                                                        snapshot["security"]["block_sealed_reveal"])
    snapshot.setdefault("execution", execution_settings_snapshot())
    return snapshot


def _job_for(run, snapshot, *, force=False, retry_of=None, budget_run_id=None):
    key = None if force else hashlib.sha256(
        (run.project_id + ":" + (run.verification_key or snapshot_hash(snapshot))).encode()).hexdigest()
    return DurableJob(
        run_id=run.id, project_id=run.project_id, snapshot=snapshot, snapshot_hash=snapshot_hash(snapshot),
        dedup_key=key, retry_of=retry_of, budget_run_id=budget_run_id or run.id,
        max_attempts=max(1, int(os.getenv("LV_JOB_MAX_ATTEMPTS", "3"))),
    )


def enqueue_run(session, run, *, force=False):
    """Add an UNSAVED VerificationRun and its job atomically; caller commits.

    Returns (canonical_run, reused). A unique key resolves concurrent submits.
    """
    project = lock_project(session, run.project_id)
    if project is None or project.deleted_at is not None:
        raise JobConflict("Project is in the trash or unavailable")
    if not force:
        existing = session.execute(select(VerificationRun).where(
            VerificationRun.project_id == run.project_id,
            VerificationRun.verification_key == run.verification_key,
            VerificationRun.state == "COMPLETED",
        ).order_by(VerificationRun.started_at.desc()).limit(1)).scalar_one_or_none()
        if existing is not None and not (existing.result_json or {}).get("security_restricted"):
            return existing, True
    snapshot = capture_snapshot(session, run)
    run.input_snapshot = snapshot
    job = None
    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
            job = _job_for(run, snapshot, force=force)
            session.add(job)
            session.flush()
        return run, False
    except IntegrityError:
        if job is None or job.dedup_key is None:
            raise
        existing = session.execute(select(DurableJob).where(
            DurableJob.dedup_key == job.dedup_key)).scalar_one_or_none()
        if existing is None:
            raise
        return session.get(VerificationRun, existing.run_id), True


@dataclass(frozen=True)
class Lease:
    run_id: str
    owner: str
    fence: int


class JobStore:
    def __init__(self, factory=None, *, clock=datetime.utcnow, lease_seconds=None, backoff_seconds=None):
        self.factory = factory
        self.clock = clock
        # 단일 외부 조회 예산(문서당 기본 120초)보다 짧으면, 그 호출 하나가
        # C 확장 안에서 GIL을 쥐고 있는 동안 갱신 스레드가 밀려 임차가 만료된다.
        # 임차가 길면 진짜로 죽은 워커의 회수가 늦어질 뿐이지만, 임차가 짧으면
        # 멀쩡히 돌던 작업이 같은 단계에서 반복해서 버려진다.
        self.lease_seconds = float(os.getenv("LV_JOB_LEASE_SECONDS", "180")
                                   if lease_seconds is None else lease_seconds)
        self.backoff_seconds = float(os.getenv("LV_JOB_BACKOFF_SECONDS", "5")
                                     if backoff_seconds is None else backoff_seconds)
        if self.lease_seconds <= 0 or self.backoff_seconds < 0:
            raise ValueError("Invalid job lease/backoff configuration")
        # 같은 단계 안의 잦은 진행 갱신을 묶는 최소 간격. 진행률은 사람이
        # 보는 값이라 1초보다 잘게 기록할 이유가 없다. 묶지 않으면 문서
        # 한 건에 수천 번의 쓰기 트랜잭션이 발생해 쓰기 잠금을 독차지한다.
        # 임차의 1/10을 넘지 않게 묶는다. 이 간격이 임차에 가까워지면 진행
        # 기록이 생존 증거 구실을 못 해, 정상 실행 중인 작업이 회수된다.
        self.progress_min_seconds = min(
            float(os.getenv("LV_JOB_PROGRESS_MIN_SECONDS", "1.0")), self.lease_seconds / 10)
        self._progress_marks: dict = {}

    def session(self):
        return (self.factory or get_session_factory())()

    def ensure(self, run_id):
        """Compatibility for callers that already committed the run; new routes use enqueue_run."""
        with write_session(self.factory) as session:
            job = session.get(DurableJob, run_id)
            if job is not None:
                return job.run_id
            run = session.get(VerificationRun, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.state in TERMINAL:
                return run_id
            if not run.input_snapshot and run.state == "QUEUED":
                # A legacy QUEUED row has never executed. Freeze it once, at adoption.
                from .services import build_context
                project = session.get(Project, run.project_id)
                if project is None:
                    raise JobConflict("Project no longer exists")
                context = build_context(project).__dict__.copy()
                context["enabled_advisory_signals"] = (sorted(context["enabled_advisory_signals"])
                    if context["enabled_advisory_signals"] is not None else None)
                documents = session.scalars(select(Document).where(
                    Document.project_id == run.project_id, Document.id.in_(run.document_ids or []))).all()
                run.input_snapshot = {"context": context, "documents": [
                    {"document_id": d.id, "sha256": d.sha256, "filename": d.filename,
                     "is_own_document": d.is_own_document} for d in documents],
                     "adopted_legacy_queue": True}
            snapshot = capture_snapshot(session, run)
            # Existing run IDs are idempotent. Request-level dedup belongs to enqueue_run.
            session.add(_job_for(run, snapshot, force=True))
        return run_id

    def adopt_queued(self):
        with self.session() as session:
            ids = list(session.scalars(select(VerificationRun.id).outerjoin(
                DurableJob, DurableJob.run_id == VerificationRun.id).where(
                    DurableJob.run_id.is_(None), VerificationRun.state == "QUEUED")))
        for run_id in ids:
            try:
                self.ensure(run_id)
            except JobConflict as exc:
                with write_session(self.factory) as session:
                    run = session.get(VerificationRun, run_id)
                    if run and run.state == "QUEUED" and session.get(DurableJob, run_id) is None:
                        run.state, run.finished_at = "FAILED", self.clock()
                        run.errors = [*(run.errors or []), str(exc)]

    def claim(self, run_id, *, owner=None):
        owner = owner or uuid.uuid4().hex
        with write_session(self.factory) as session:
            # 시각은 쓰기 잠금을 얻은 뒤에 읽는다. 잠금 대기 전에 읽으면 기다린 만큼 임차가 짧아져,
            # 막 가져간 작업의 첫 진행 기록이 이미 만료된 임차에 부딪힌다(CI run 36090264005).
            now = self.clock()
            changed = session.execute(update(DurableJob).where(
                DurableJob.run_id == run_id, DurableJob.state.in_(READY),
                DurableJob.available_at <= now, DurableJob.attempts < DurableJob.max_attempts,
            ).values(state="RUNNING", owner=owner, fence=DurableJob.fence + 1,
                     attempts=DurableJob.attempts + 1, heartbeat_at=now, updated_at=now,
                     lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                     dispatch_until=None)).rowcount
            if changed != 1:
                return None
            job = session.get(DurableJob, run_id)
            session.add(JobAttempt(run_id=run_id, fence=job.fence, owner=owner, started_at=now))
            run = session.get(VerificationRun, run_id)
            run.finished_at = None
            run.state = "QUEUED"
            run.stage_message = f"{job.attempts}번째 시도를 시작합니다"
            run.progress = 0.0  # 재시도는 처음부터 다시 실행한다
            return Lease(run_id, owner, job.fence)

    def fence(self, session, lease):
        """소유권을 확인하면서 임차도 함께 연장한다.

        진행 상태 기록·체크포인트는 모두 이 관문을 지난다. 즉 일이 실제로
        나아가고 있다는 증거다. 그것으로 임차를 연장하면, 갱신 스레드가
        CPU 경합이나 GIL을 오래 쥐는 구간에 밀려도 정상 실행 중인 작업이
        회수되지 않는다. 별도 스레드 하나에만 생존 판정을 맡기지 않는다.
        """
        now = self.clock()
        changed = session.execute(update(DurableJob).where(
            DurableJob.run_id == lease.run_id, DurableJob.owner == lease.owner,
            DurableJob.fence == lease.fence, DurableJob.state == "RUNNING",
            DurableJob.lease_expires_at > now,
        ).values(updated_at=now, heartbeat_at=now,
                 lease_expires_at=now + timedelta(seconds=self.lease_seconds)
                 ).execution_options(synchronize_session=False)).rowcount
        if changed != 1:
            raise JobOwnershipLost(lease.run_id)

    def owns(self, lease):
        """소유 여부만 본다. 조건은 fence와 같되 쓰기 잠금을 잡지 않는다."""
        with self.session() as session:
            return session.execute(select(DurableJob.run_id).where(
                DurableJob.run_id == lease.run_id, DurableJob.owner == lease.owner,
                DurableJob.fence == lease.fence, DurableJob.state == "RUNNING",
                DurableJob.lease_expires_at > self.clock())).first() is not None

    def check(self, lease):
        """소유권 확인은 읽기로 충분하다.

        예전에는 fence()의 UPDATE를 그대로 썼다. 조건을 확인하기만 하면
        되는데 매번 쓰기 트랜잭션을 열었다. 외부 출처 조회 중에는 이 확인이
        초당 한 번 일어나므로(transport._fetch_with_deadline), 문서당 수백
        번의 불필요한 쓰기가 발생했고 WAL에서 쓰기 잠금을 다투었다. 임차
        갱신이 그 경합에 밀려 실패하던 원인 중 하나다.
        """
        if not self.owns(lease):
            raise JobOwnershipLost(lease.run_id)

    def heartbeat(self, lease):
        with write_session(self.factory) as session:
            self.fence(session, lease)
            now = self.clock()
            session.execute(update(DurableJob).where(DurableJob.run_id == lease.run_id).values(
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=self.lease_seconds)))

    def progress(self, lease, state, message, ratio):
        """진행 상태를 기록한다. 같은 단계 안의 잦은 갱신은 묶는다.

        파이프라인은 인용 한 건마다 진행을 알린다. 문서 하나에 5천 번을
        넘겼고, 그때마다 쓰기 트랜잭션과 VerificationCheck 행이 하나씩
        생겼다. 그 쓰기가 SQLite 쓰기 잠금을 계속 쥐고 있어 임차 갱신
        스레드가 끼어들지 못했고, 작업은 정상 실행 중에 회수되었다.

        단계가 바뀌거나 종료 상태면 반드시 기록한다. 사람이 보는 진행률은
        1초 간격이면 충분하다.
        """
        state = str(state)
        now = self.clock()
        key = (lease.run_id, lease.fence)
        previous = self._progress_marks.get(key)
        if (previous and previous[0] == state and state not in TERMINAL
                and (now - previous[1]).total_seconds() < self.progress_min_seconds):
            return False
        with write_session(self.factory) as session:
            self.fence(session, lease)
            run = session.get(VerificationRun, lease.run_id)
            if state not in TERMINAL:
                run.state, run.stage_message, run.progress = state, message, round(ratio, 3)
            session.add(VerificationCheck(run_id=lease.run_id, name=state,
                state="PERSISTING" if state in TERMINAL else "RUNNING",
                detail={"message": message, "progress": ratio, "fence": lease.fence}))
        self._progress_marks[key] = (state, now)
        return True

    def checkpoint(self, lease, *, document=None, execution=None):
        with write_session(self.factory) as session:
            self.fence(session, lease)
            attempt = session.execute(select(JobAttempt).where(
                JobAttempt.run_id == lease.run_id, JobAttempt.fence == lease.fence)).scalar_one()
            if document is not None:
                prior = attempt.partial_result or {}
                attempt.partial_result = {**prior, "documents": [*(prior.get("documents") or []), document]}
            if execution is not None:
                attempt.executions = [*(attempt.executions or []), execution]

    def complete(self, session, lease, result, *, reusable=True):
        """Caller must persist the result in this SAME transaction after fencing."""
        self.fence(session, lease)
        job = session.get(DurableJob, lease.run_id)
        job.state, job.owner, job.lease_expires_at = str(result.state), None, None
        # Retain successful keys when completion races an enqueue's cache lookup.
        if job.state != "COMPLETED" or not reusable:
            job.dedup_key = None
        job.updated_at = self.clock()
        attempt = session.execute(select(JobAttempt).where(
            JobAttempt.run_id == lease.run_id, JobAttempt.fence == lease.fence)).scalar_one()
        attempt.state, attempt.finished_at = str(result.state), self.clock()
        attempt.error = "\n".join(result.errors or [])

    def _failed(self, session, job, error):
        now = self.clock()
        attempt = session.execute(select(JobAttempt).where(
            JobAttempt.run_id == job.run_id, JobAttempt.fence == job.fence)).scalar_one_or_none()
        if attempt:
            attempt.state, attempt.error, attempt.finished_at = "FAILED", error, now
        retry = job.attempts < job.max_attempts
        job.state = "BACKOFF" if retry else "FAILED"
        job.owner, job.lease_expires_at, job.dispatch_until = None, None, None
        job.available_at = now + timedelta(seconds=min(300, self.backoff_seconds * 2 ** min(job.attempts - 1, 16)))
        job.last_error, job.updated_at = error, now
        if not retry:
            job.dedup_key = None
        run = session.get(VerificationRun, job.run_id)
        run.errors = [*(run.errors or []), error]
        run.state = "QUEUED" if retry else "FAILED"
        wait = max(0, round((job.available_at - now).total_seconds()))
        run.stage_message = (
            f"오류가 발생해 {wait}초 뒤 다시 시도합니다({job.attempts}/{job.max_attempts}회)"
            if retry else f"{job.max_attempts}회 시도가 모두 실패했습니다")
        run.finished_at = None if retry else now
        session.add(VerificationCheck(run_id=job.run_id, name="JOB_ATTEMPT", state=job.state,
                                      detail={"error": error, "attempt": job.attempts, "fence": job.fence}))

    def fail(self, lease, error):
        with write_session(self.factory) as session:
            self.fence(session, lease)
            self._failed(session, session.get(DurableJob, lease.run_id), str(error))

    def recover(self):
        """Expired workers lose ownership before any retry becomes dispatchable."""
        recovered = []
        with write_session(self.factory) as session:
            ids = session.execute(select(DurableJob.run_id).where(
                DurableJob.state == "RUNNING", DurableJob.lease_expires_at <= self.clock())).scalars().all()
            for run_id in ids:
                changed = session.execute(update(DurableJob).where(
                    DurableJob.run_id == run_id, DurableJob.state == "RUNNING",
                    DurableJob.lease_expires_at <= self.clock(),
                ).values(updated_at=self.clock())).rowcount
                if changed:
                    self._failed(session, session.get(DurableJob, run_id), "WORKER_LEASE_EXPIRED")
                    recovered.append(run_id)
        return recovered

    def due(self, limit=100):
        with self.session() as session:
            return list(session.execute(select(DurableJob.run_id).where(
                DurableJob.state.in_(READY), DurableJob.available_at <= self.clock(),
                or_(DurableJob.dispatch_until.is_(None), DurableJob.dispatch_until <= self.clock()),
            ).order_by(DurableJob.available_at).limit(limit)).scalars())

    def acquire_dispatch(self, run_id, *, seconds=30):
        with write_session(self.factory) as session:
            return session.execute(update(DurableJob).where(
                DurableJob.run_id == run_id, DurableJob.state.in_(READY),
                DurableJob.available_at <= self.clock(),
                or_(DurableJob.dispatch_until.is_(None), DurableJob.dispatch_until <= self.clock()),
            ).values(dispatch_until=self.clock() + timedelta(seconds=seconds))).rowcount == 1

    def dispatch_result(self, run_id, *, task_id=None, error=None, seconds=5):
        with write_session(self.factory) as session:
            values = {"task_id": task_id}
            if error is not None:
                values.update(last_error=str(error), dispatch_until=self.clock() + timedelta(seconds=max(1, seconds)))
            session.execute(update(DurableJob).where(
                DurableJob.run_id == run_id, DurableJob.state.in_(READY)).values(**values))

    def defer(self, run_id, running):
        """정원이 찼을 때 대기 중임을 화면에 알린다.

        동시 실행을 1로 두면 두 번째 검증은 시작하지 못하고 기다린다.
        아무 안내가 없으면 화면은 시작조차 못한 것과 멈춘 것을 구분할 수
        없다. 실행 중인 작업의 메시지는 건드리지 않는다.
        """
        with write_session(self.factory) as session:
            job = session.get(DurableJob, run_id)
            run = session.get(VerificationRun, run_id)
            if job is None or run is None or job.state not in READY or run.state in TERMINAL:
                return False
            run.stage_message = (f"앞선 검증 {running}건이 끝나면 시작합니다"
                                 if running else "순서를 기다리고 있습니다")
            return True

    def cancel(self, run_id, *, actor="system"):
        self.ensure(run_id)
        with write_session(self.factory) as session:
            # Lock first, then inspect. Completion and cancellation have one winner.
            session.execute(update(DurableJob).where(DurableJob.run_id == run_id).values(updated_at=self.clock()))
            job = session.get(DurableJob, run_id)
            run = session.get(VerificationRun, run_id)
            if run is None:
                raise KeyError(run_id)
            if job is None or job.state in TERMINAL:
                return run.state
            attempt = session.execute(select(JobAttempt).where(
                JobAttempt.run_id == run_id, JobAttempt.fence == job.fence)).scalar_one_or_none()
            if attempt and attempt.state == "RUNNING":
                attempt.state, attempt.finished_at = "CANCELLED", self.clock()
            job.state, job.owner, job.lease_expires_at, job.dedup_key = "CANCELLED", None, None, None
            job.fence += 1
            run.state, run.finished_at, run.stage_message = "CANCELLED", self.clock(), "Cancelled"
            session.add(VerificationCheck(run_id=run_id, name="CANCEL", state="CANCELLED",
                                          detail={"actor": actor}))
            return "CANCELLED"

    def retry(self, run_id, *, actor="system"):
        with write_session(self.factory) as session:
            session.execute(update(DurableJob).where(DurableJob.run_id == run_id).values(updated_at=self.clock()))
            source = session.get(VerificationRun, run_id)
            if source is None:
                raise KeyError(run_id)
            project = lock_project(session, source.project_id)
            if project is None or project.deleted_at is not None:
                raise JobConflict("Project is in the trash or unavailable")
            existing = session.execute(select(DurableJob).where(DurableJob.retry_of == run_id)).scalar_one_or_none()
            if existing:
                return existing.run_id
            if source.state not in {"FAILED", "CANCELLED", "PARTIAL_COMPLETED"}:
                raise JobConflict("Only failed, cancelled, or partially completed runs can be retried")
            source_job = session.get(DurableJob, run_id)
            if source_job is None:
                raise JobConflict("Legacy run has no durable execution snapshot; create a new verification")
            child = VerificationRun(project_id=source.project_id, document_ids=copy.deepcopy(source.document_ids),
                profile=source.profile, verification_key=source.verification_key, state="QUEUED",
                input_snapshot=copy.deepcopy(source.input_snapshot))
            session.add(child)
            session.flush()
            session.add(_job_for(child, copy.deepcopy(source_job.snapshot), force=True, retry_of=run_id,
                                 budget_run_id=source_job.budget_run_id))
            session.add(VerificationCheck(run_id=child.id, name="RETRY", state="QUEUED",
                                          detail={"actor": actor, "retry_of": run_id}))
            return child.id

    def status(self, run_id):
        with self.session() as session:
            job = session.get(DurableJob, run_id)
            if job is None:
                raise KeyError(run_id)
            run = session.get(VerificationRun, run_id)
            document_ids = set(run.document_ids or [])
            attempts = session.execute(select(JobAttempt).where(JobAttempt.run_id == run_id)
                                       .order_by(JobAttempt.fence)).scalars().all()
            return {"run_id": run_id, "project_id": job.project_id, "state": job.state,
                    "attempts": job.attempts, "max_attempts": job.max_attempts,
                    "available_at": job.available_at, "lease_expires_at": job.lease_expires_at,
                    "heartbeat_at": job.heartbeat_at, "dispatch_until": job.dispatch_until,
                    "next_dispatch_at": _next_dispatch_at(job),
                    "retry_of": job.retry_of,
                    "last_error": _status_error(job.last_error),
                    "history": [{"fence": a.fence, "state": a.state, "error": _status_error(a.error),
                                 "partial_result": _partial_summary(a.partial_result, document_ids),
                                 "executions": [_execution_summary(e) for e in (a.executions or []) if isinstance(e, dict)],
                                 "started_at": a.started_at, "finished_at": a.finished_at} for a in attempts]}


def _status_error(error):
    if not error:
        return ""
    code = str(error).split(":", 1)[0]
    return code if code in {"WORKER_LEASE_EXPIRED", "BUDGET_ADMISSION_FAILED", "INVALID_RESPONSE_SCHEMA",
                           "PROVIDER_EXCEPTION", "PROVIDER_POLICY_BLOCKED"} else "JOB_ATTEMPT_FAILED"


def _next_dispatch_at(job):
    candidates = [value for value in (job.available_at, job.dispatch_until) if value is not None]
    return max(candidates) if candidates else None


def _count_of(document, compact_key, legacy_key):
    """새 체크포인트는 건수를 바로 담는다. 예전 행은 목록을 담고 있다."""
    value = document.get(compact_key)
    if isinstance(value, int) and value >= 0:
        return value
    return len(document.get(legacy_key) or [])


def _partial_summary(partial, document_ids):
    # Attempt JSON is retained for recovery, but is not a trusted public response schema.
    documents = partial.get("documents", []) if isinstance(partial, dict) else []
    return {"retained": bool(partial), "documents": [
        {"document_id": d["document_id"],
         "finding_count": _count_of(d, "finding_count", "findings"),
         "page_count": _count_of(d, "page_count", "pages"),
         "quarantined": bool(d.get("quarantined"))}
        for d in documents if isinstance(d, dict) and d.get("document_id") in document_ids
    ]}


def _execution_summary(execution):
    from math import isfinite
    from packages.common.enums import LLMRole

    def number(key):
        value = execution.get(key, 0)
        return value if type(value) in (int, float) and isfinite(value) and value >= 0 else 0

    role = execution.get("role")
    provider = execution.get("provider")
    cost_status = execution.get("cost_status")
    return {"role": role if role in {str(r) for r in LLMRole} else "UNKNOWN",
            "provider": provider if provider in {"openai", "anthropic", "gemini", "local", "null"} else "other",
            "ok": bool(execution.get("ok")), "quarantined": bool(execution.get("quarantined")),
            "input_tokens": number("input_tokens"), "output_tokens": number("output_tokens"),
            "latency_ms": number("latency_ms"), "cost_usd": number("cost_usd"),
            "cost_status": cost_status if cost_status in {"REPORTED", "ESTIMATED", "LOCAL", "NOT_SENT",
                                                           "RESERVED_UNCERTAIN"} else "UNKNOWN",
            "error": _status_error(execution.get("error"))}
