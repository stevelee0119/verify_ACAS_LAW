"""Shared execution path for local threads and the existing verification.run task."""
from __future__ import annotations

import copy
import json
import threading
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
from packages.common.enums import AuditEventType, ExternalAIPolicy, JobState, VerificationProfile
from packages.common.storage import get_storage, sha256_file
from packages.llm_router import LLMRouter
from packages.llm_router.budget import BudgetLedger, write_session
from packages.report_engine import to_json
from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline, VerificationRunResult


@contextmanager
def heartbeat(store, lease):
    stop = threading.Event()
    lost = threading.Event()

    def beat():
        while not stop.wait(max(0.02, store.lease_seconds / 3)):
            try:
                store.heartbeat(lease)
            except (JobOwnershipLost, Exception):
                lost.set()
                return

    thread = threading.Thread(target=beat, daemon=True, name="lease-" + lease.run_id)
    thread.start()
    try:
        def check():
            if lost.is_set():
                raise JobOwnershipLost(lease.run_id)
            store.check(lease)
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


class WorkerAuditChain(AuditChain):
    def __init__(self, store, lease, submission):
        super().__init__(sink=FencedAuditSink(store, lease))
        self.run_id = lease.run_id
        self.submission = {key: submission.get(key) for key in ("actor_id", "organization_id", "authentication")}
        self.submission["actor_id"] = self.submission["actor_id"] or "system"

    def record(self, event_type, payload, **kwargs):
        kwargs["actor"] = "system:worker"
        return super().record(event_type, {**payload, "run_id": self.run_id,
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
                    is_own_document=item.get("is_own_document")))

            class CheckpointPipeline(VerificationPipeline):
                def _run_document(self, *args, **kwargs):
                    check()
                    document = super()._run_document(*args, **kwargs)
                    partial = VerificationRunResult(run_id, project_id, JobState.PARTIAL_COMPLETED, key,
                                                    documents=[document])
                    payload = json.loads(to_json(partial))
                    store.checkpoint(lease, document=payload["documents"][0])
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
                                  progress=lambda *args: store.progress(lease, *args))
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
    except JobOwnershipLost:
        return
    except Exception as exc:
        try:
            store.fail(lease, str(exc))
        except JobOwnershipLost:
            pass
