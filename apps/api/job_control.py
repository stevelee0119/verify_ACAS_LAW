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
    if project is None:
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
    if session.get_bind().dialect.name == "sqlite":
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
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
        self.lease_seconds = float(os.getenv("LV_JOB_LEASE_SECONDS", "90") if lease_seconds is None else lease_seconds)
        self.backoff_seconds = float(os.getenv("LV_JOB_BACKOFF_SECONDS", "5")
                                     if backoff_seconds is None else backoff_seconds)
        if self.lease_seconds <= 0 or self.backoff_seconds < 0:
            raise ValueError("Invalid job lease/backoff configuration")

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
        now = self.clock()
        owner = owner or uuid.uuid4().hex
        with write_session(self.factory) as session:
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
            run.stage_message = "Worker claimed attempt " + str(job.attempts)
            return Lease(run_id, owner, job.fence)

    def fence(self, session, lease):
        changed = session.execute(update(DurableJob).where(
            DurableJob.run_id == lease.run_id, DurableJob.owner == lease.owner,
            DurableJob.fence == lease.fence, DurableJob.state == "RUNNING",
            DurableJob.lease_expires_at > self.clock(),
        ).values(updated_at=self.clock()).execution_options(synchronize_session=False)).rowcount
        if changed != 1:
            raise JobOwnershipLost(lease.run_id)

    def check(self, lease):
        with write_session(self.factory) as session:
            self.fence(session, lease)

    def heartbeat(self, lease):
        with write_session(self.factory) as session:
            self.fence(session, lease)
            now = self.clock()
            session.execute(update(DurableJob).where(DurableJob.run_id == lease.run_id).values(
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=self.lease_seconds)))

    def progress(self, lease, state, message, ratio):
        with write_session(self.factory) as session:
            self.fence(session, lease)
            run = session.get(VerificationRun, lease.run_id)
            state = str(state)
            if state not in TERMINAL:
                run.state, run.stage_message, run.progress = state, message, round(ratio, 3)
            session.add(VerificationCheck(run_id=lease.run_id, name=state,
                state="PERSISTING" if state in TERMINAL else "RUNNING",
                detail={"message": message, "progress": ratio, "fence": lease.fence}))

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
        run.stage_message = "Retry scheduled" if retry else "Attempts exhausted"
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

    def dispatch_result(self, run_id, *, task_id=None, error=None):
        with write_session(self.factory) as session:
            values = {"task_id": task_id}
            if error is not None:
                values.update(last_error=str(error), dispatch_until=self.clock() + timedelta(seconds=5))
            session.execute(update(DurableJob).where(
                DurableJob.run_id == run_id, DurableJob.state.in_(READY)).values(**values))

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
                    "heartbeat_at": job.heartbeat_at, "retry_of": job.retry_of,
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


def _partial_summary(partial, document_ids):
    # Attempt JSON is retained for recovery, but is not a trusted public response schema.
    documents = partial.get("documents", []) if isinstance(partial, dict) else []
    return {"retained": bool(partial), "documents": [
        {"document_id": d["document_id"], "finding_count": len(d.get("findings") or []),
         "page_count": len(d.get("pages") or []), "quarantined": bool(d.get("quarantined"))}
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
