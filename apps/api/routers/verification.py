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

from ..db import Document, EvidenceRow, FindingRow, Project, VerificationRun, get_db, get_session_factory
from ..schemas import FindingOut, RevealRequest, ReviewRequest, RunOut, VerifyRequest
from ..services import build_context, find_reusable_run, get_runner, make_audit

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
    )


def _start_run(session: Session, project: Project, document_ids: List[str], payload: VerifyRequest) -> RunOut:
    if not document_ids:
        raise HTTPException(400, "검증할 문서가 없다")
    settings = get_settings()
    documents = session.execute(select(Document).where(Document.id.in_(document_ids))).scalars().all()
    if len(documents) != len(document_ids):
        raise HTTPException(404, "문서를 찾을 수 없다")

    profile = VerificationProfile(payload.profile or project.verification_profile or "STANDARD")
    key = verification_key(
        [d.sha256 for d in documents],
        profile,
        rule_version=settings.rule_version,
        prompt_version=settings.prompt_version,
        model_config_version=settings.model_config_version(),
    )
    if not payload.force:
        existing = find_reusable_run(session, project.id, key)
        if existing is not None:
            return _run_out(existing, reused=True)

    run = VerificationRun(
        project_id=project.id,
        document_ids=[d.id for d in documents],
        profile=str(profile),
        state=str(JobState.QUEUED),
        verification_key=key,
    )
    session.add(run)
    session.commit()
    get_runner().submit(run.id)
    return _run_out(run)


@router.post("/documents/{document_id}/verify", response_model=RunOut, status_code=202)
def verify_document(document_id: str, payload: VerifyRequest = VerifyRequest(),
                    session: Session = Depends(get_db)) -> RunOut:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "문서를 찾을 수 없다")
    project = session.get(Project, document.project_id)
    return _start_run(session, project, [document.id], payload)


@router.post("/projects/{project_id}/verify", response_model=RunOut, status_code=202)
def verify_project(project_id: str, payload: VerifyRequest = VerifyRequest(),
                   session: Session = Depends(get_db)) -> RunOut:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없다")
    ids = payload.document_ids or [
        d.id for d in session.execute(select(Document).where(Document.project_id == project_id)).scalars().all()
    ]
    return _start_run(session, project, ids, payload)


@router.get("/projects/{project_id}/runs", response_model=List[RunOut])
def list_runs(project_id: str, limit: int = Query(default=10, le=100),
              session: Session = Depends(get_db)) -> List[RunOut]:
    """프로젝트의 검증 Run 목록(최신순). 화면 재진입 시 최신 결과를 복원하는 데 사용한다."""
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
def get_run(run_id: str, session: Session = Depends(get_db)) -> RunOut:
    run = session.get(VerificationRun, run_id)
    if run is None:
        raise HTTPException(404, "Run을 찾을 수 없다")
    return _run_out(run)


@router.get("/verification-runs/{run_id}/result")
def get_run_result(run_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    run = session.get(VerificationRun, run_id)
    if run is None:
        raise HTTPException(404, "Run을 찾을 수 없다")
    return run.result_json or {}


@router.get("/verification-runs/{run_id}/events")
async def stream_progress(run_id: str) -> StreamingResponse:
    """제18.2장 SSE 진행률."""

    async def generator():
        last = None
        for _ in range(600):  # 최대 5분
            session = get_session_factory()()
            try:
                run = session.get(VerificationRun, run_id)
                if run is None:
                    yield f"event: error\ndata: {json.dumps({'message': 'Run 없음'})}\n\n"
                    return
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
            await asyncio.sleep(0.5)

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
    session: Session = Depends(get_db),
) -> List[FindingOut]:
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
def get_finding(finding_id: str, session: Session = Depends(get_db)) -> FindingOut:
    row = session.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, "Finding을 찾을 수 없다")
    return _finding_out(session, row)


@router.patch("/findings/{finding_id}/review", response_model=FindingOut)
def review_finding(finding_id: str, payload: ReviewRequest, session: Session = Depends(get_db)) -> FindingOut:
    """제19.4장. 사용자 판단은 AI Finding을 삭제하지 않고 별도 review layer로 남긴다."""
    row = session.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, "Finding을 찾을 수 없다")
    try:
        status = ReviewStatus(payload.review_status.upper())
    except ValueError:
        raise HTTPException(400, f"허용되지 않는 review 상태이다: {payload.review_status}")

    previous = row.review_status
    row.review_status = str(status)
    row.review_note = payload.note
    row.reviewed_by = payload.reviewer
    row.reviewed_at = datetime.utcnow()
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
        actor=payload.reviewer,
        project_id=row.project_id,
        document_id=row.document_id,
    )
    return _finding_out(session, row)


@router.post("/findings/{finding_id}/reveal")
def reveal_sealed(finding_id: str, payload: RevealRequest, session: Session = Depends(get_db)) -> Dict[str, Any]:
    """제7-A.6장 특권·윤리 게이트. 사용자가 명시적으로 선택한 경우에만 원문을 공개하고 열람을 기록한다."""
    row = session.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, "Finding을 찾을 수 없다")
    settings = get_settings()
    project = session.get(Project, row.project_id)
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
        actor=payload.reviewer,
        project_id=row.project_id,
        document_id=row.document_id,
    )
    return {
        "finding_id": finding_id,
        "sealed_excerpt": row.sealed_excerpt,
        "notice": "열람 사실이 감사추적(Audit Hash Chain)에 기록되었다.",
    }
