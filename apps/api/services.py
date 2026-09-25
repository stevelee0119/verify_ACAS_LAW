"""검증 실행 서비스: 파이프라인 실행 결과를 DB에 적재한다."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import insert as sa_insert, select
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

# 결과 적재가 끝나야 최종 상태로 본다(제18.2장 Job State).
TERMINAL_JOB_STATES = {
    JobState.COMPLETED,
    JobState.PARTIAL_COMPLETED,
    JobState.FAILED,
    JobState.CANCELLED,
}

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
        issue_dates=project.key_dates or {},
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
            VerificationRun.state == str(JobState.COMPLETED),
        )
        .order_by(VerificationRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def execute_run(run_id: str, *, store=None) -> None:
    """Both Celery and local workers use the durable, fenced execution path."""
    from apps.worker.runtime import execute

    execute(run_id, store=store)


def link_snapshot_evidence(result, snapshot) -> None:
    from dataclasses import fields
    from packages.claim_engine.structure import EvidenceItem, extract_evidence_references, match_evidence_references
    from packages.common.schemas import Claim

    documents = {document.document_id: document for document in result.documents}
    catalog = []
    for item in snapshot.get("documents", []):
        document = documents.get(item["document_id"])
        if document is None or document.quarantined or not document.normalized or not item.get("sha256"):
            continue
        references = extract_evidence_references(item.get("evidence_number") or "")
        for reference in references:
            if reference["parse_status"] == "PARSED":
                catalog.append(EvidenceItem(result.project_id, reference["key"], item["document_id"],
                    result.run_id, item["sha256"],
                    tuple(page.page_number for page in document.normalized.pages)))
    claim_fields = {item.name for item in fields(Claim)}
    for document_result in result.documents:
        for claim in document_result.claims:
            structured = Claim(**{key: value for key, value in claim.items() if key in claim_fields})
            matches = match_evidence_references([structured], catalog, project_id=result.project_id)
            claim["evidence_matches"] = [match.to_dict() for match in matches]
            claim["evidence_links"] = [{"reference": match.reference["raw_text"],
                "document_ids": [item.document_id for item in match.candidates],
                "reference_status": match.status, "support_status": "NOT_ASSESSED"} for match in matches]


# result_json과 VerificationRun 칼럼에 같이 들어가던 값들. 칼럼이 정본이다.
RESULT_COLUMN_KEYS = ("scores", "timeline", "unavailable_sources", "unverified_items", "errors")


def _insert_all(session: Session, model, rows) -> None:
    """되읽지 않는 단순 적재는 ORM 객체를 만들지 않고 한 번에 넣는다."""
    if rows:
        session.execute(sa_insert(model), rows)


def run_result_view(run: VerificationRun) -> dict:
    """저장된 결과에 전용 칼럼 값을 합쳐 온전한 모양으로 돌려준다."""
    payload = dict(run.result_json or {})
    if not payload:
        return payload
    for key in RESULT_COLUMN_KEYS:
        payload.setdefault(key, getattr(run, key, None) or ([] if key != "scores" else {}))
    return payload


def persist_result(session: Session, run: VerificationRun, result: VerificationRunResult,
                   *, lease=None, store=None, commit=True) -> None:
    from packages.report_engine.exporters import to_payload
    from .job_control import DurableJob, JobOwnershipLost, JobStore

    store = store or JobStore()
    if lease is not None:
        store.fence(session, lease)
    elif session.get(DurableJob, run.id) is not None:
        raise JobOwnershipLost(run.id)

    run.state = str(result.state)
    run.progress = 1.0
    run.stage_message = "완료"
    run.verification_key = result.verification_key
    run.scores = result.scores
    run.timeline = result.timeline
    run.unavailable_sources = result.unavailable_sources
    run.unverified_items = result.unverified_items
    run.errors = list(dict.fromkeys([*(run.errors or []), *result.errors]))
    run.finished_at = result.finished_at or datetime.utcnow()
    # 문자열로 만들었다가 다시 읽지 않는다. JSON 칼럼이 알아서 직렬화한다.
    payload = to_payload(result)
    # 전용 칼럼에 이미 들어가는 값은 여기서 또 담지 않는다. 한 건에 수 MB가
    # 중복되고, 그만큼 직렬화 비용과 메모리가 늘어난다. 응답은 run_result_view가
    # 칼럼에서 되돌려 붙이므로 밖에서 보이는 모양은 그대로다.
    for key in RESULT_COLUMN_KEYS:
        payload.pop(key, None)
    run.result_json = payload
    run.result_json["input_snapshot"] = run.input_snapshot or {}

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
        _insert_all(session, CitationRow, [
            {"id": citation["citation_id"], "document_id": document_result.document_id,
              "project_id": run.project_id, "data": citation}
            for citation in document_result.citations])
        session.query(ClaimRow).filter(ClaimRow.document_id == document_result.document_id).delete()
        _insert_all(session, ClaimRow, [
            {"id": claim["claim_id"], "document_id": document_result.document_id,
              "project_id": run.project_id, "data": claim}
            for claim in document_result.claims])
        session.query(EventRow).filter(EventRow.document_id == document_result.document_id).delete()
        _insert_all(session, EventRow, [
            {"id": eventrow["event_id"], "document_id": document_result.document_id,
              "project_id": run.project_id, "data": eventrow}
            for eventrow in document_result.events])
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

    for execution in result.model_executions:
        allowed = {c.name for c in ModelExecutionRow.__table__.columns} - {"id", "run_id", "created_at"}
        session.add(ModelExecutionRow(run_id=run.id, **{k: v for k, v in execution.items() if k in allowed}))
    if commit:
        session.commit()


from apps.worker.runner import JobRunner


_runner = JobRunner()


def get_runner() -> JobRunner:
    return _runner
