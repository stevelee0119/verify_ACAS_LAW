"""검증 실행 서비스: 파이프라인 실행 결과를 DB에 적재한다."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.audit_engine import AuditChain
from packages.common.enums import (
    AuditEventType,
    ExternalAIPolicy,
    JobState,
    VerificationProfile,
)
from packages.common.config import get_settings
from packages.common.storage import get_storage
from packages.llm_router import LLMRouter
from packages.source_adapters import SourceRegistry
from packages.verification_engine import (
    DocumentInput,
    ProjectContext,
    VerificationPipeline,
    VerificationRunResult,
)

from .audit_sink import DBAuditSink
from .db import (
    CitationRow,
    ClaimRow,
    Document,
    DocumentBlock,
    DocumentPage,
    EntityRow,
    EventRow,
    EvidenceRow,
    FindingRow,
    ModelExecutionRow,
    Project,
    SourceRecordRow,
    VerificationCheck,
    VerificationRun,
    get_session_factory,
)

_registry: Optional[SourceRegistry] = None


def get_registry() -> SourceRegistry:
    global _registry
    if _registry is None:
        _registry = SourceRegistry()
    return _registry


def set_registry(registry: SourceRegistry) -> None:  # 테스트용
    global _registry
    _registry = registry


def make_audit(session: Session) -> AuditChain:
    return AuditChain(sink=DBAuditSink(session))


def build_context(project: Project) -> ProjectContext:
    return ProjectContext(
        project_id=project.id,
        case_number=project.case_number,
        court=project.court,
        parties=list(project.parties or []),
        case_date=project.incident_date,
        external_ai_policy=ExternalAIPolicy(project.external_ai_policy or "MASKED"),
        profile=VerificationProfile(project.verification_profile or "STANDARD"),
        enabled_advisory_signals=set(project.enabled_advisory_signals)
        if project.enabled_advisory_signals is not None
        else None,
        requested_issues=list(project.requested_issues or []),
    )


def find_reusable_run(session: Session, project_id: str, key: str) -> Optional[VerificationRun]:
    """제18.3장 Idempotency: 동일 문서·동일 설정의 완료된 Run을 재사용한다."""
    return session.execute(
        select(VerificationRun)
        .where(
            VerificationRun.project_id == project_id,
            VerificationRun.verification_key == key,
            VerificationRun.state.in_([str(JobState.COMPLETED), str(JobState.PARTIAL_COMPLETED)]),
        )
        .order_by(VerificationRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def execute_run(run_id: str) -> None:
    """Worker에서 호출되는 실행 함수. 자체 세션을 연다."""
    session = get_session_factory()()
    try:
        run = session.get(VerificationRun, run_id)
        if run is None:
            return
        project = session.get(Project, run.project_id)
        if project is None:
            run.state = str(JobState.FAILED)
            session.commit()
            return

        documents = (
            session.execute(select(Document).where(Document.id.in_(run.document_ids or []))).scalars().all()
        )
        storage = get_storage()
        inputs: List[DocumentInput] = []
        for document in documents:
            inputs.append(
                DocumentInput(
                    document_id=document.id,
                    path=str(storage.path(document.storage_key)),
                    filename=document.filename,
                    mime_type=document.mime_type or "",
                    sha256=document.sha256,
                )
            )

        audit = make_audit(session)
        pipeline = VerificationPipeline(registry=get_registry(), router=LLMRouter(), audit=audit)

        def progress(state: JobState, message: str, ratio: float) -> None:
            run.state = str(state)
            run.stage_message = message
            run.progress = round(ratio, 3)
            session.add(VerificationCheck(run_id=run.id, name=str(state), state="RUNNING",
                                          detail={"message": message, "progress": ratio}))
            session.commit()

        context = build_context(project)
        result = pipeline.run(run.id, context, inputs, progress=progress)
        persist_result(session, run, result)
    except Exception as exc:  # pragma: no cover - 방어적
        session.rollback()
        run = session.get(VerificationRun, run_id)
        if run is not None:
            run.state = str(JobState.FAILED)
            run.errors = (run.errors or []) + [str(exc)]
            run.finished_at = datetime.utcnow()
            session.commit()
    finally:
        session.close()


def persist_result(session: Session, run: VerificationRun, result: VerificationRunResult) -> None:
    from packages.report_engine import to_json

    run.state = str(result.state)
    run.progress = 1.0
    run.stage_message = "완료"
    run.verification_key = result.verification_key
    run.scores = result.scores
    run.timeline = result.timeline
    run.unavailable_sources = result.unavailable_sources
    run.unverified_items = result.unverified_items
    run.errors = result.errors
    run.finished_at = result.finished_at or datetime.utcnow()
    import json as _json

    run.result_json = _json.loads(to_json(result).decode("utf-8"))

    for document_result in result.documents:
        document = session.get(Document, document_result.document_id)
        if document is not None:
            document.quarantined = document_result.quarantined
            document.rag_indexable = document_result.rag_indexable

        normalized = document_result.normalized
        if normalized is not None:
            session.query(DocumentPage).filter(DocumentPage.document_id == normalized.document_id).delete()
            session.query(DocumentBlock).filter(DocumentBlock.document_id == normalized.document_id).delete()
            for page in normalized.pages:
                session.add(
                    DocumentPage(
                        document_id=normalized.document_id,
                        page_number=page.page_number,
                        width=page.width,
                        height=page.height,
                        attributes=page.attributes,
                    )
                )
                for block in page.blocks:
                    session.add(
                        DocumentBlock(
                            id=block.block_id,
                            document_id=normalized.document_id,
                            page=block.page,
                            text=block.text,
                            bbox=list(block.bbox.as_tuple()) if block.bbox else None,
                            source_layer=block.source_layer,
                            block_type=block.block_type,
                            visible=block.visible,
                            attributes=block.attributes,
                        )
                    )

        session.query(CitationRow).filter(CitationRow.document_id == document_result.document_id).delete()
        for citation in document_result.citations:
            session.add(
                CitationRow(id=citation["citation_id"], document_id=document_result.document_id,
                            project_id=run.project_id, data=citation)
            )
        session.query(ClaimRow).filter(ClaimRow.document_id == document_result.document_id).delete()
        for claim in document_result.claims:
            session.add(
                ClaimRow(id=claim["claim_id"], document_id=document_result.document_id,
                         project_id=run.project_id, data=claim)
            )
        session.query(EventRow).filter(EventRow.document_id == document_result.document_id).delete()
        for eventrow in document_result.events:
            session.add(
                EventRow(id=eventrow["event_id"], document_id=document_result.document_id,
                         project_id=run.project_id, data=eventrow)
            )
        for entity in document_result.entities:
            if session.get(EntityRow, entity["entity_id"]) is None:
                session.add(EntityRow(id=entity["entity_id"], project_id=run.project_id, data=entity))

        for record in document_result.source_records:
            if session.get(SourceRecordRow, record.source_record_id) is None:
                session.add(
                    SourceRecordRow(
                        id=record.source_record_id,
                        run_id=run.id,
                        adapter=record.adapter,
                        query=record.query,
                        status=str(record.status),
                        result_id=record.result_id,
                        response_hash=record.response_hash,
                        url=record.url,
                        used_fields=record.used_fields,
                        retrieved_at=record.retrieved_at,
                    )
                )

    # Finding을 먼저 flush해야 Evidence의 FK 제약이 성립한다
    for finding in result.all_findings:
        row = FindingRow(
            id=finding.finding_id,
            run_id=run.id,
            project_id=run.project_id,
            document_id=finding.document_id,
            type=str(finding.type),
            status=str(finding.status),
            severity=str(finding.severity),
            evidence_grade=str(finding.evidence_grade),
            confidence=finding.confidence,
            page=finding.page,
            block_id=finding.block_id,
            title=finding.title,
            detail=finding.detail,
            engine=finding.engine,
            meta_message_type=str(finding.meta_message_type) if finding.meta_message_type else None,
            advisory_only=finding.advisory_only,
            tags=finding.tags,
            data=finding.to_dict(),
            sealed_excerpt=finding.sealed_excerpt,
            review_status=str(finding.review_status),
        )
        session.add(row)
    session.flush()

    for finding in result.all_findings:
        for evidence in finding.evidence:
            if session.get(EvidenceRow, evidence.evidence_id) is None:
                session.add(
                    EvidenceRow(
                        id=evidence.evidence_id,
                        finding_id=finding.finding_id,
                        data=evidence.to_dict(reveal_sealed=True),
                    )
                )

    session.commit()


class JobRunner:
    """검증 Job 실행기 (제3.1장).

    브로커가 설정되어 있으면 Celery로 디스패치하고, 없으면 인프로세스 스레드로 실행한다.
    두 경로 모두 동일한 execute_run()을 호출하므로 Verification Core는 하나이다.
    """

    def __init__(self) -> None:
        self._threads: Dict[str, threading.Thread] = {}
        self._task_ids: Dict[str, str] = {}

    # -- 모드 판정 --------------------------------------------------------
    @property
    def mode(self) -> str:
        settings = get_settings()
        configured = (settings.worker_mode or "auto").lower()
        if configured == "celery":
            return "celery"
        if configured == "inprocess":
            return "inprocess"
        from workers.celery_app import broker_url, celery_available

        return "celery" if (broker_url() and celery_available()) else "inprocess"

    # -- 제출 -------------------------------------------------------------
    def submit(self, run_id: str) -> str:
        if self.mode == "celery":
            try:
                from workers.celery_app import VERIFICATION_TASK, get_celery_app

                app = get_celery_app()
                if app is None:
                    raise RuntimeError("celery를 사용할 수 없다")
                result = app.send_task(VERIFICATION_TASK, args=[run_id], queue="verification")
                self._task_ids[run_id] = result.id
                return "celery"
            except Exception:
                # 브로커 장애 시 전체 기능을 잃지 않도록 인프로세스로 강등한다
                # (제2장 Graceful Degradation)
                pass
        thread = threading.Thread(target=execute_run, args=(run_id,), daemon=True, name=f"run-{run_id}")
        self._threads[run_id] = thread
        thread.start()
        return "inprocess"

    def task_id(self, run_id: str) -> Optional[str]:
        return self._task_ids.get(run_id)

    def wait(self, run_id: str, timeout: float = 120.0) -> None:
        """인프로세스 실행을 기다린다. Celery 경로에서는 Run 상태를 폴링한다."""
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout)
            return
        if run_id not in self._task_ids:
            return
        import time

        from packages.common.enums import JobState

        terminal = {str(JobState.COMPLETED), str(JobState.PARTIAL_COMPLETED),
                    str(JobState.FAILED), str(JobState.CANCELLED)}
        deadline = time.time() + timeout
        while time.time() < deadline:
            session = get_session_factory()()
            try:
                run = session.get(VerificationRun, run_id)
                if run is not None and run.state in terminal:
                    return
            finally:
                session.close()
            time.sleep(0.3)

    def busy(self) -> List[str]:
        return [rid for rid, t in self._threads.items() if t.is_alive()]


_runner = JobRunner()


def get_runner() -> JobRunner:
    return _runner
