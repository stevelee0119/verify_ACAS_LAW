"""Case matrix, human review workflow and document lineage."""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType
from ..db import Document, FindingRow, Project, VerificationRun, get_db
from ..services import make_audit
from ..workspace import (CaseIssue, CaseProfile, ClaimAssessment, DocumentRelation,
                         FindingWorkflow, ReviewDraft, ReviewRevision, as_dict)

router = APIRouter(tags=["workspace"])


def actor(request: Request) -> str:
    from ..identity import current_principal
    return current_principal().user_id


def project_or_404(session, project_id):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다")
    return project


def run_or_404(session, project_id, run_id=None):
    run = session.get(VerificationRun, run_id) if run_id else session.scalar(
        select(VerificationRun).where(VerificationRun.project_id == project_id,
          VerificationRun.state.in_(["COMPLETED", "PARTIAL_COMPLETED"])).order_by(VerificationRun.started_at.desc()).limit(1))
    if run is None or run.project_id != project_id:
        raise HTTPException(404, "이 프로젝트의 완료된 검증 결과가 없습니다")
    if run.state not in ("COMPLETED", "PARTIAL_COMPLETED"):
        raise HTTPException(409, "완료된 검증 결과를 선택하세요")
    return run


def history(session, project_id, subject_type, subject_id, who, before, after):
    session.add(ReviewRevision(project_id=project_id, subject_type=subject_type,
        subject_id=subject_id, actor=who, before=before, after=after))


def save_versioned(session, model, pk, existing, values, revision, who):
    before = as_dict(existing)
    values = {**values, "updated_by": who, "updated_at": datetime.utcnow(), "revision": revision + 1}
    if existing:
        column = list(model.__table__.primary_key.columns)[0]
        changed = session.execute(update(model).where(column == pk, model.revision == revision).values(**values))
        if not changed.rowcount:
            raise HTTPException(409, "다른 검토자가 변경했습니다. 새로고침 후 다시 저장하세요")
        session.expire(existing)
    else:
        if revision != 0:
            raise HTTPException(409, "검토 기록의 버전이 일치하지 않습니다")
        existing = model(**values)
        session.add(existing)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "다른 검토자가 먼저 저장했습니다. 새로고침해 주세요")
    return existing, before


class IssueInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    elements: list[str] = Field(default_factory=list, max_length=30)
    reference_date: date | None = None
    legal_basis: str = Field(default="", max_length=10000)
    priority: int = Field(default=2, ge=1, le=3)
    note: str = Field(default="", max_length=10000)
    revision: int = Field(default=0, ge=0)

    @field_validator("title", "elements")
    @classmethod
    def nonempty(cls, value):
        if isinstance(value, list):
            if any(not v.strip() or len(v) > 1000 for v in value):
                raise ValueError("요건사실은 비어 있지 않은 1000자 이하 문장이어야 합니다")
            return [v.strip() for v in value]
        if not value.strip():
            raise ValueError("쟁점명을 입력하세요")
        return value.strip()


@router.get("/projects/{project_id}/issues")
def issues(project_id: str, session: Session = Depends(get_db)):
    project_or_404(session, project_id)
    return [as_dict(r) for r in session.scalars(select(CaseIssue).where(
        CaseIssue.project_id == project_id).order_by(CaseIssue.priority, CaseIssue.title))]


def save_issue(project_id, issue_id, payload, request, session):
    session.execute(update(Project).where(Project.id == project_id).values(scope_revision=Project.scope_revision))
    project = project_or_404(session, project_id)
    session.refresh(project)
    row = session.get(CaseIssue, issue_id) if issue_id else None
    if issue_id and (not row or row.project_id != project_id):
        raise HTTPException(404, "쟁점을 찾을 수 없습니다")
    values = payload.model_dump(exclude={"revision"})
    values["reference_date"] = payload.reference_date.isoformat() if payload.reference_date else None
    values["project_id"] = project_id
    row, before = save_versioned(session, CaseIssue, issue_id, row, values, payload.revision, actor(request))
    dates = dict(project.key_dates or {})
    if row.reference_date:
        dates[row.id] = row.reference_date
    else:
        dates.pop(row.id, None)
    project.key_dates = dates
    session.flush()
    session.execute(update(Project).where(Project.id == project_id).values(scope_revision=Project.scope_revision + 1))
    result = as_dict(row)
    history(session, project_id, "ISSUE", row.id, actor(request), before, result)
    session.commit()
    return result


@router.post("/projects/{project_id}/issues", status_code=201)
def create_issue(project_id: str, payload: IssueInput, request: Request, session: Session = Depends(get_db)):
    return save_issue(project_id, None, payload, request, session)


@router.put("/projects/{project_id}/issues/{issue_id}")
def update_issue(project_id: str, issue_id: str, payload: IssueInput, request: Request, session: Session = Depends(get_db)):
    return save_issue(project_id, issue_id, payload, request, session)


class ProfileInput(BaseModel):
    lead_reviewer: str = Field(default="", max_length=120)
    represented_party: str = Field(default="", max_length=200)
    revision: int = Field(default=0, ge=0)


@router.get("/projects/{project_id}/case-profile")
def get_profile(project_id: str, session: Session = Depends(get_db)):
    project_or_404(session, project_id)
    return as_dict(session.get(CaseProfile, project_id)) or {"revision": 0}


@router.put("/projects/{project_id}/case-profile")
def save_profile(project_id: str, payload: ProfileInput, request: Request, session: Session = Depends(get_db)):
    project_or_404(session, project_id)
    row, before = save_versioned(session, CaseProfile, project_id, session.get(CaseProfile, project_id),
        {"project_id": project_id, **payload.model_dump(exclude={"revision"})}, payload.revision, actor(request))
    history(session, project_id, "CASE_PROFILE", project_id, actor(request), before, as_dict(row))
    session.commit()
    return as_dict(row)


class EvidenceLink(BaseModel):
    document_id: str
    page: int | None = Field(default=None, ge=1)
    excerpt: str = Field(default="", max_length=4000)
    relation: Literal["SUPPORTS", "REFUTES", "CONTEXT", "UNASSESSED"] = "UNASSESSED"


class AssessmentInput(BaseModel):
    run_id: str
    claim_id: str
    issue_id: str | None = None
    position: Literal["UNASSESSED", "ASSERTED", "ADMITTED", "DENIED", "UNKNOWN", "CONDITIONAL", "ALTERNATIVE"] = "UNASSESSED"
    support_status: Literal["UNASSESSED", "SUPPORTED", "PARTIAL", "CONFLICTING", "INSUFFICIENT", "REVIEWED"] = "UNASSESSED"
    evidence_links: list[EvidenceLink] = Field(default_factory=list, max_length=100)
    missing_material: str = Field(default="", max_length=10000)
    note: str = Field(default="", max_length=10000)
    revision: int = Field(default=0, ge=0)


def matrix_data(session, project_id, run):
    documents = {d.id: d for d in session.scalars(select(Document).where(Document.project_id == project_id))}
    assessments = {a.claim_id: a for a in session.scalars(select(ClaimAssessment).where(ClaimAssessment.run_id == run.id))}
    claims = []
    for doc in (run.result_json or {}).get("documents", []):
        for claim in doc.get("claims", []):
            assessment = as_dict(assessments.get(claim.get("claim_id")))
            excluded = [link["document_id"] for link in assessment.get("evidence_links", [])
                        if not documents.get(link["document_id"]) or not documents[link["document_id"]].included_in_verification]
            claims.append({"claim": claim, "document_id": doc["document_id"], "assessment": assessment,
                           "excluded_evidence": excluded, "review_status": "EVIDENCE_EXCLUDED" if excluded else assessment.get("support_status", "UNASSESSED")})
    return {"run_id": run.id, "issues": issues(project_id, session), "claims": claims,
            "scope_changed": (run.input_snapshot or {}).get("scope_revision") != project_or_404(session, project_id).scope_revision}


@router.get("/projects/{project_id}/case-matrix")
def get_matrix(project_id: str, run_id: str | None = None, session: Session = Depends(get_db)):
    return matrix_data(session, project_id, run_or_404(session, project_id, run_id))


@router.put("/projects/{project_id}/claim-assessments")
def save_assessment(project_id: str, payload: AssessmentInput, request: Request, session: Session = Depends(get_db)):
    run = run_or_404(session, project_id, payload.run_id)
    document_id = next((d["document_id"] for d in (run.result_json or {}).get("documents", [])
        if any(c.get("claim_id") == payload.claim_id for c in d.get("claims", []))), None)
    if not document_id:
        raise HTTPException(404, "선택한 검증 결과에 해당 주장이 없습니다")
    if payload.issue_id:
        issue = session.get(CaseIssue, payload.issue_id)
        if not issue or issue.project_id != project_id:
            raise HTTPException(404, "이 사건에 속한 쟁점만 연결할 수 있습니다")
    for link in payload.evidence_links:
        doc = session.get(Document, link.document_id)
        if not doc or doc.project_id != project_id or not doc.included_in_verification:
            raise HTTPException(400, "현재 검토에 포함된 같은 사건의 증거만 연결할 수 있습니다")
        entry = next((d for d in (run.result_json or {}).get("documents", []) if d["document_id"] == doc.id), None)
        if not entry:
            raise HTTPException(400, "선택한 실행에 포함되지 않은 증거입니다. 다시 검증하세요")
        if link.page and link.page not in {p["page_number"] for p in entry.get("pages", [])}:
            raise HTTPException(400, "증거의 쪽수를 확인할 수 없습니다")
    row = session.scalar(select(ClaimAssessment).where(ClaimAssessment.run_id == run.id, ClaimAssessment.claim_id == payload.claim_id))
    values = {**payload.model_dump(exclude={"revision"}), "project_id": project_id, "document_id": document_id}
    row, before = save_versioned(session, ClaimAssessment, row.id if row else None, row, values, payload.revision, actor(request))
    history(session, project_id, "CLAIM", row.id, actor(request), before, as_dict(row))
    session.commit()
    return as_dict(row)


class WorkflowInput(BaseModel):
    workflow_state: Literal["NOT_STARTED", "IN_PROGRESS", "ACTION_REQUIRED", "COMPLETED", "DEFERRED"] = "NOT_STARTED"
    decision: Literal["UNDECIDED", "AGREED", "FALSE_POSITIVE", "PARTLY_AGREED"] = "UNDECIDED"
    priority: int = Field(default=2, ge=1, le=3)
    assignee: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=20000)
    revision: int = Field(default=0, ge=0)


def workflow_value(session, finding):
    saved = session.get(FindingWorkflow, finding.id)
    if saved:
        return as_dict(saved)
    legacy = finding.review_status or "NEEDS_REVIEW"
    return {"finding_id": finding.id, "revision": 0,
            "workflow_state": "NOT_STARTED" if legacy == "NEEDS_REVIEW" else "COMPLETED",
            "decision": {"ACCEPTED": "AGREED", "FALSE_POSITIVE": "FALSE_POSITIVE"}.get(legacy, "UNDECIDED"),
            "priority": 2, "assignee": "", "note": finding.review_note or "",
            "updated_by": finding.reviewed_by, "updated_at": finding.reviewed_at.isoformat() if finding.reviewed_at else None}


def finding_or_404(session, finding_id):
    row = session.get(FindingRow, finding_id)
    if not row:
        raise HTTPException(404, "검토 항목을 찾을 수 없습니다")
    return row


@router.get("/findings/{finding_id}/workflow")
def get_workflow(finding_id: str, request: Request, session: Session = Depends(get_db)):
    result = workflow_value(session, finding_or_404(session, finding_id))
    draft = session.get(ReviewDraft, (finding_id, actor(request)))
    result["draft"] = as_dict(draft) if draft and draft.base_revision == result["revision"] else {}
    return result


def update_workflow(session, finding, payload, who):
    session.execute(update(FindingRow).where(FindingRow.id == finding.id).values(reviewed_by=FindingRow.reviewed_by))
    previous = session.get(FindingWorkflow, finding.id)
    row, before = save_versioned(session, FindingWorkflow, finding.id, previous,
        {"finding_id": finding.id, **payload.model_dump(exclude={"revision"})}, payload.revision, who)
    if row.workflow_state == "COMPLETED":
        finding.review_status = {"FALSE_POSITIVE": "FALSE_POSITIVE", "AGREED": "ACCEPTED"}.get(row.decision, "RESOLVED")
    else:
        finding.review_status = "NEEDS_REVIEW"
    finding.review_note, finding.reviewed_by, finding.reviewed_at = row.note, who, datetime.utcnow()
    draft = session.get(ReviewDraft, (finding.id, who))
    if draft:
        session.delete(draft)
    history(session, finding.project_id, "FINDING", finding.id, who, before, as_dict(row))
    return as_dict(row)


@router.put("/findings/{finding_id}/workflow")
def put_workflow(finding_id: str, payload: WorkflowInput, request: Request, session: Session = Depends(get_db)):
    finding = finding_or_404(session, finding_id)
    result = update_workflow(session, finding, payload, actor(request))
    session.commit()
    make_audit(session).record(AuditEventType.USER_OVERRIDE,
        {"action": "REVIEW_WORKFLOW", "finding_id": finding_id, "revision": result["revision"]},
        actor=actor(request), project_id=finding.project_id)
    return result


class DraftInput(BaseModel):
    note: str = Field(default="", max_length=20000)
    revision: int = Field(default=0, ge=0)


@router.put("/findings/{finding_id}/review-draft")
def save_draft(finding_id: str, payload: DraftInput, request: Request, session: Session = Depends(get_db)):
    session.execute(update(FindingRow).where(FindingRow.id == finding_id).values(reviewed_by=FindingRow.reviewed_by))
    finding = finding_or_404(session, finding_id)
    if workflow_value(session, finding)["revision"] != payload.revision:
        raise HTTPException(409, "검토 기록이 변경되어 이전 초안을 저장하지 않았습니다")
    who = actor(request)
    row = session.get(ReviewDraft, (finding_id, who))
    if not row:
        row = ReviewDraft(finding_id=finding_id, user_id=who)
        session.add(row)
    row.note, row.updated_at = payload.note, datetime.utcnow()
    row.base_revision = payload.revision
    session.commit()
    return {"saved_at": row.updated_at.isoformat()}


class BulkReview(BaseModel):
    finding_ids: list[str] = Field(min_length=1, max_length=300)
    expected_revisions: dict[str, int]
    values: WorkflowInput


@router.post("/projects/{project_id}/reviews")
def bulk_review(project_id: str, payload: BulkReview, request: Request, session: Session = Depends(get_db)):
    ids = set(payload.finding_ids)
    rows = session.scalars(select(FindingRow).where(FindingRow.project_id == project_id, FindingRow.id.in_(ids))).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "현재 프로젝트에 속한 검토 항목만 선택하세요")
    if set(payload.expected_revisions) != ids:
        raise HTTPException(422, "선택한 각 항목의 검토 버전이 필요합니다")
    results = []
    for row in rows:
        values = payload.values.model_copy(update={"revision": payload.expected_revisions[row.id]})
        results.append(update_workflow(session, row, values, actor(request)))
    session.commit()
    make_audit(session).record(AuditEventType.USER_OVERRIDE,
        {"action": "BULK_REVIEW", "finding_ids": sorted(ids)}, actor=actor(request), project_id=project_id)
    return results


@router.get("/projects/{project_id}/review-workflows")
def list_workflows(project_id: str, run_id: str, session: Session = Depends(get_db)):
    run_or_404(session, project_id, run_id)
    return [workflow_value(session, f) for f in session.scalars(select(FindingRow).where(
        FindingRow.project_id == project_id, FindingRow.run_id == run_id))]


@router.get("/projects/{project_id}/review-history")
def review_history(project_id: str, subject_id: str | None = None, limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_db)):
    project_or_404(session, project_id)
    query = select(ReviewRevision).where(ReviewRevision.project_id == project_id)
    if subject_id:
        query = query.where(ReviewRevision.subject_id == subject_id)
    return [as_dict(r) for r in session.scalars(query.order_by(ReviewRevision.id.desc()).limit(limit))]
