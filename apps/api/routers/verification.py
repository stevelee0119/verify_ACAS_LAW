"""검증 실행·조회·Finding 엔드포인트 (제18.1장)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.config import get_settings
from packages.common.enums import AuditEventType, JobState, ReviewStatus, VerificationProfile
from packages.common.storage import get_storage
from packages.forensic_engine import PrivilegeGate
from packages.verification_engine import verification_key

from ..auth import (
    accessible_document,
    accessible_finding,
    accessible_project,
    accessible_run,
    current_user,
    editable_document,
    editable_project,
    is_editor,
)
from ..db import User, Document, EvidenceRow, FindingRow, Project, VerificationRun, get_db, get_session_factory
from ..identity import actor_id, current_principal, require_project, bind_analysis_session
from ..job_control import JobConflict, enqueue_run, execution_security, execution_settings_snapshot
from ..workspace import CaseIssue, FindingWorkflow, as_dict
from ..schemas import FindingOut, RevealRequest, ReviewRequest, RunOut, VerifyRequest
from ..services import build_context, get_runner, make_audit, get_registry

router = APIRouter(tags=["verification"])


def _run_out(run: VerificationRun, reused: bool = False) -> RunOut:
    return RunOut(
        id=run.id,
        project_id=run.project_id,
        state=run.state,
        progress=run.progress or 0.0,
        stage_message=run.stage_message or "",
        verification_key=run.verification_key,
        document_ids=list(run.document_ids or []),
        scores=run.scores or {},
        unavailable_sources=list(run.unavailable_sources or []),
        unverified_items=list(run.unverified_items or []),
        errors=list(run.errors or []),
        started_at=run.started_at,
        finished_at=run.finished_at,
        reused=reused,
        timeline=run.timeline or [],
        input_snapshot=run.input_snapshot or {},
    )


def _start_run(session: Session, project: Project, document_ids: List[str], payload: VerifyRequest) -> RunOut:
    require_project(session, project.id, "MEMBER")
    if not document_ids:
        raise HTTPException(400, "검증할 문서가 없다")
    settings = get_settings()
    document_ids = list(dict.fromkeys(document_ids))
    documents = session.execute(select(Document).where(Document.id.in_(document_ids),
        Document.project_id == project.id, Document.included_in_verification.is_(True)).order_by(Document.id)).scalars().all()
    if len(documents) != len(document_ids):
        raise HTTPException(404, "문서를 찾을 수 없다")

    profile = VerificationProfile(payload.profile or project.verification_profile or "STANDARD")
    context = build_context(project)
    try:
        security = execution_security(session, project.id, context.external_ai_policy)
        execution = execution_settings_snapshot()
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    context.external_ai_policy = security["external_ai_policy"]
    context.org_block_reveal = bool(context.org_block_reveal or security["block_sealed_reveal"])
    snapshot = {
        "scope_revision": project.scope_revision or 0,
        "project": {"name": project.name, "case_number": project.case_number, "court": project.court},
        "versions": {"rule": settings.rule_version, "prompt": settings.prompt_version,
                     "model_config": settings.model_config_version()},
        "context": {**context.__dict__, "profile": str(profile),
                    "enabled_advisory_signals": sorted(context.enabled_advisory_signals) if context.enabled_advisory_signals is not None else None},
        "documents": [{"document_id": d.id, "sha256": d.sha256, "filename": d.filename,
                       "evidence_number": d.evidence_number, "submitted_by": d.submitted_by,
                       "is_own_document": d.is_own_document, "storage_key": d.storage_key,
                       "mime_type": d.mime_type or ""} for d in documents],
        "source_states": [s.to_dict() for s in get_registry().states()],
        "execution": execution,
        "security": security,
        "issues": [as_dict(issue) for issue in session.scalars(
            select(CaseIssue).where(CaseIssue.project_id == project.id).order_by(CaseIssue.id))],
    }
    key = verification_key(
        [d.sha256 for d in documents],
        profile,
        rule_version=settings.rule_version,
        prompt_version=settings.prompt_version,
        model_config_version=settings.model_config_version(),
        context_snapshot=snapshot,
    )
    principal = current_principal()
    snapshot["submission"] = {"actor_id": principal.user_id, "organization_id": project.organization_id,
                              "authentication": principal.authentication}
    run = VerificationRun(
        project_id=project.id,
        document_ids=[d.id for d in documents],
        profile=str(profile),
        state=str(JobState.QUEUED),
        verification_key=key,
        input_snapshot=snapshot,
    )
    try:
        run, reused = enqueue_run(session, run, force=payload.force)
        bind_analysis_session(session, run, principal)
        session.commit()
    except JobConflict as exc:
        session.rollback()
        raise HTTPException(409, str(exc)) from exc
    get_runner().submit(run.id)
    return _run_out(run, reused=reused)


@router.post("/documents/{document_id}/verify", response_model=RunOut, status_code=202)
def verify_document(document_id: str, payload: VerifyRequest = VerifyRequest(),
                    user: User = Depends(current_user),
                    session: Session = Depends(get_db)) -> RunOut:
    document = editable_document(session, user, document_id)
    project = session.get(Project, document.project_id)
    return _start_run(session, project, [document.id], payload)


@router.post("/projects/{project_id}/verify", response_model=RunOut, status_code=202)
def verify_project(project_id: str, payload: VerifyRequest = VerifyRequest(),
                   user: User = Depends(current_user),
                   session: Session = Depends(get_db)) -> RunOut:
    project = editable_project(session, user, project_id)
    ids = payload.document_ids if payload.document_ids is not None else [
        d.id for d in session.execute(select(Document).where(Document.project_id == project_id,
            Document.included_in_verification.is_(True))).scalars().all()
    ]
    return _start_run(session, project, ids, payload)


@router.get("/projects/{project_id}/runs", response_model=List[RunOut])
def list_runs(project_id: str, limit: int = Query(default=10, le=100),
              user: User = Depends(current_user),
              session: Session = Depends(get_db)) -> List[RunOut]:
    """프로젝트의 검증 Run 목록(최신순). 화면 재진입 시 최신 결과를 복원하는 데 사용한다."""
    accessible_project(session, user, project_id)
    require_project(session, project_id)
    runs = (
        session.execute(
            select(VerificationRun)
            .where(VerificationRun.project_id == project_id)
            .order_by(VerificationRun.started_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_run_out(run) for run in runs]


@router.get("/verification-runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, user: User = Depends(current_user),
            session: Session = Depends(get_db)) -> RunOut:
    run = accessible_run(session, user, run_id)
    require_project(session, run.project_id)
    return _run_out(run)


@router.get("/verification-runs/{run_id}/result")
def get_run_result(run_id: str, user: User = Depends(current_user),
                   session: Session = Depends(get_db)) -> Dict[str, Any]:
    run = accessible_run(session, user, run_id)
    require_project(session, run.project_id)
    from ..services import run_result_view

    return run_result_view(run)


@router.get("/verification-runs/{run_id}/events")
async def stream_progress(
    run_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    """제18.2장 SSE 진행률.

    EventSource는 요청 헤더를 붙이지 못하므로 브라우저는 세션 쿠키로 인증한다.
    스트림을 열기 전에 접근 권한을 확인한다. 진행률·상태도 사건 정보이다.
    """
    accessible_run(session, user, run_id)
    # 요청 의존성의 세션은 응답(스트림)이 끝날 때까지 닫히지 않는다. 최대 5분 동안
    # 커넥션 하나를 붙잡으면 작은 풀(운영 5개)이 스트림 몇 개로 바닥나 다른 요청이
    # 풀 대기 시간 초과(HTTP 500)로 실패한다. 권한 확인이 끝났으니 바로 돌려준다.
    session.close()

    principal = current_principal()
    with get_session_factory()() as session:
        run = session.get(VerificationRun, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        require_project(session, run.project_id, principal=principal)

    async def generator():
        last = None
        # 0.5초마다 세션을 새로 열면 5분 스트림 하나가 DB를 600번 두드린다.
        # 진행 단계는 그보다 훨씬 느리게 바뀌므로 화면에 보이는 차이는 없다.
        for _ in range(150):  # 최대 5분
            session = get_session_factory()()
            try:
                run = session.get(VerificationRun, run_id)
                if run is None:
                    yield f"event: error\ndata: {json.dumps({'message': 'Run 없음'})}\n\n"
                    return
                require_project(session, run.project_id, principal=principal)
                payload = {
                    "state": run.state,
                    "progress": run.progress,
                    "message": run.stage_message,
                    "finished": run.state
                    in (str(JobState.COMPLETED), str(JobState.PARTIAL_COMPLETED), str(JobState.FAILED),
                        str(JobState.CANCELLED)),
                }
            finally:
                session.close()
            if payload != last:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last = payload
            if payload["finished"]:
                return
            await asyncio.sleep(2.0)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _finding_out(session: Session, row: FindingRow) -> FindingOut:
    data = row.data or {}
    evidence = [
        e.data for e in session.execute(select(EvidenceRow).where(EvidenceRow.finding_id == row.id)).scalars().all()
    ]
    # 봉인 원문은 기본 응답에서 제외한다(제7-A.6장)
    safe_evidence = []
    for item in evidence:
        item = dict(item)
        if item.get("sealed"):
            item["excerpt"] = None
            item["sealed_notice"] = "SEALED: 열람 요청 시에만 공개된다."
        safe_evidence.append(item)
    return FindingOut(
        id=row.id,
        run_id=row.run_id,
        project_id=row.project_id,
        document_id=row.document_id,
        type=row.type,
        status=row.status,
        severity=row.severity,
        evidence_grade=row.evidence_grade,
        confidence=row.confidence or 0.0,
        page=row.page,
        block_id=row.block_id,
        title=row.title or "",
        detail=row.detail or "",
        engine=row.engine,
        meta_message_type=row.meta_message_type,
        advisory_only=bool(row.advisory_only),
        tags=list(row.tags or []),
        review_status=row.review_status or "NEEDS_REVIEW",
        review_note=row.review_note or "",
        has_sealed_content=bool(row.sealed_excerpt),
        evidence=safe_evidence,
        sources=list(data.get("sources") or []),
        bbox=data.get("bbox"),
        citation_id=(data.get("confidence_features") or {}).get("citation_id"),
    )


@router.get("/projects/{project_id}/findings", response_model=List[FindingOut])
def list_findings(
    project_id: str,
    run_id: Optional[str] = None,
    severity: Optional[str] = None,
    type: Optional[str] = None,
    document_id: Optional[str] = None,
    review_status: Optional[str] = None,
    advisory: Optional[bool] = Query(default=None, description="true면 참고 신호(MM-4)만 반환한다"),
    tag: Optional[str] = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> List[FindingOut]:
    accessible_project(session, user, project_id)
    require_project(session, project_id)
    if run_id:
        selected_run = session.get(VerificationRun, run_id)
        if selected_run is None or selected_run.project_id != project_id:
            raise HTTPException(404, "Run not found")
    query = select(FindingRow).where(FindingRow.project_id == project_id)
    if run_id:
        query = query.where(FindingRow.run_id == run_id)
    else:
        latest = session.execute(
            select(VerificationRun)
            .where(VerificationRun.project_id == project_id)
            .order_by(VerificationRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            query = query.where(FindingRow.run_id == latest.id)
    if severity:
        query = query.where(FindingRow.severity == severity.upper())
    if type:
        query = query.where(FindingRow.type == type.upper())
    if document_id:
        query = query.where(FindingRow.document_id == document_id)
    if review_status:
        query = query.where(FindingRow.review_status == review_status.upper())
    if advisory is not None:
        query = query.where(FindingRow.advisory_only == advisory)

    rows = session.execute(query).scalars().all()
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    rows.sort(key=lambda r: (order.get(r.severity, 9), -(r.confidence or 0)))
    return [_finding_out(session, r) for r in rows]


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: str, user: User = Depends(current_user),
                session: Session = Depends(get_db)) -> FindingOut:
    row = accessible_finding(session, user, finding_id)
    require_project(session, row.project_id)
    return _finding_out(session, row)


@router.patch("/findings/{finding_id}/review", response_model=FindingOut)
def review_finding(finding_id: str, payload: ReviewRequest,
                   user: User = Depends(current_user),
                   session: Session = Depends(get_db)) -> FindingOut:
    """제19.4장. 사용자 판단은 AI Finding을 삭제하지 않고 별도 review layer로 남긴다."""
    row = accessible_finding(session, user, finding_id)
    if not is_editor(user):
        raise HTTPException(403, "읽기 전용 권한으로는 Review 상태를 바꿀 수 없다")
    try:
        status = ReviewStatus(payload.review_status.upper())
    except ValueError:
        raise HTTPException(400, f"허용되지 않는 review 상태이다: {payload.review_status}")

    require_project(session, row.project_id, "MEMBER")
    if session.get(FindingWorkflow, finding_id) is not None:
        raise HTTPException(409, "Structured review exists; use PUT /findings/{id}/workflow with its revision")
    from .workspace import WorkflowInput, update_workflow
    previous = row.review_status
    decision = {"ACCEPTED": "AGREED", "FALSE_POSITIVE": "FALSE_POSITIVE"}.get(str(status), "UNDECIDED")
    values = WorkflowInput(
        workflow_state="NOT_STARTED" if str(status) == "NEEDS_REVIEW" else "COMPLETED",
        decision=decision, note=payload.note, revision=0,
    )
    update_workflow(session, row, values, actor_id())
    session.commit()

    make_audit(session).record(
        AuditEventType.USER_OVERRIDE,
        {
            "finding_id": finding_id,
            "from": previous,
            "to": str(status),
            "note": payload.note,
            "notice": "원래 Finding과 Audit Trail은 삭제되지 않는다.",
        },
        actor=actor_id(),
        project_id=row.project_id,
        document_id=row.document_id,
    )
    return _finding_out(session, row)


@router.post("/findings/{finding_id}/reveal")
def reveal_sealed(finding_id: str, payload: RevealRequest,
                  user: User = Depends(current_user),
                  session: Session = Depends(get_db)) -> Dict[str, Any]:
    """제7-A.6장 특권·윤리 게이트. 사용자가 명시적으로 선택한 경우에만 원문을 공개하고 열람을 기록한다.

    봉인 원문은 이 시스템에서 가장 민감한 자료이므로 읽기 전용 권한으로는 열 수 없다.
    """
    row = accessible_finding(session, user, finding_id)
    if not is_editor(user):
        raise HTTPException(403, "읽기 전용 권한으로는 봉인 원문을 열람할 수 없다")
    settings = get_settings()
    project = require_project(session, row.project_id, "MEMBER")
    organization_block = False
    if project is not None and project.organization_id:
        from ..db import Organization

        organization = session.get(Organization, project.organization_id)
        organization_block = bool(organization and organization.block_sealed_reveal)

    gate = PrivilegeGate(org_block_reveal=organization_block, allow_reveal=settings.allow_sealed_reveal)

    # 봉인 여부만 확인하면 되므로 도메인 객체로 변환하지 않고 최소 형태를 전달한다
    class _SealedProbe:
        sealed_excerpt = row.sealed_excerpt
        evidence: List[Any] = []

    decision = gate.request_reveal(_SealedProbe(), user_confirmed=payload.confirmed)
    if not decision.allowed:
        raise HTTPException(403, decision.reason)

    make_audit(session).record(
        AuditEventType.SEALED_CONTENT_REVEALED,
        {"finding_id": finding_id, "reason": payload.reason, "type": row.type},
        actor=actor_id(),
        project_id=row.project_id,
        document_id=row.document_id,
    )
    return {
        "finding_id": finding_id,
        "sealed_excerpt": row.sealed_excerpt,
        "notice": "열람 사실이 감사추적(Audit Hash Chain)에 기록되었다.",
    }
