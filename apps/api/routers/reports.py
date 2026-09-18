"""보고서 생성·다운로드 엔드포인트 (제18.1장, 제20장)."""
from __future__ import annotations

import json
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType
from packages.common.storage import get_storage, sha256_bytes
from packages.common.terminology import report_label, terminology_catalog
from packages.report_engine import build_highlight_pdf, build_report_pdf, to_csv, to_json, to_manifest, to_xlsx
from packages.report_engine.snapshot import canonical_hash, remove_sealed, shareable_snapshot, view_from_snapshot

from ..db import (
    Document,
    EvidenceRow,
    ExportArtifactRow,
    FindingRow,
    Project,
    ReportRow,
    VerificationRun,
    get_db,
    new_uuid,
)
from ..schemas import ReportRequest, ReportFinalizeRequest
from ..services import make_audit
from ..identity import current_principal, require_project
from ..workspace import ReportReview, ReviewRevision, CaseProfile, as_dict
from .workspace import matrix_data, workflow_value
from .audit import get_manifest as project_manifest

router = APIRouter(tags=["reports"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "highlight": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "manifest": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/projects/{project_id}/report-terminology")
def report_terminology(project_id: str, session: Session = Depends(get_db)):
    require_project(session, project_id)
    return terminology_catalog()


class _RunView:
    """report_engine이 기대하는 형태로 DB 결과를 감싼다."""

    def __init__(self, run: VerificationRun, findings: List[Any], documents: List[Any]) -> None:
        self.run_id = run.id
        self.project_id = run.project_id
        self.state = run.state
        self.verification_key = run.verification_key
        self.started_at = run.started_at
        self.finished_at = run.finished_at
        self.scores = run.scores or {}
        self.timeline = run.timeline or []
        self.unavailable_sources = run.unavailable_sources or []
        self.unverified_items = run.unverified_items or []
        self.errors = run.errors or []
        self.input_snapshot = run.input_snapshot or {}
        self.model_executions = (run.result_json or {}).get("model_executions", [])
        self.documents = documents
        self.project_findings = [f for f in findings if not f.document_id]
        self._findings = findings

    @property
    def all_findings(self) -> List[Any]:
        return self._findings


class _DocumentView:
    def __init__(self, row: Document, findings: List[Any], result_json: Dict[str, Any]) -> None:
        self.document_id = row.id
        entry = next((d for d in (result_json.get("documents") or []) if d.get("document_id") == row.id), {})
        self.filename = entry.get("filename", row.filename)
        self.quarantined = bool(entry.get("quarantined", row.quarantined))
        self.rag_indexable = bool(entry.get("rag_indexable", row.rag_indexable))
        self.citations = entry.get("citations", [])
        self.claims = entry.get("claims", [])
        self.entities = entry.get("entities", [])
        self.events = entry.get("events", [])
        self.authorship = entry.get("authorship", {})
        self.masked_preview = entry.get("masked_preview", {})
        self.warnings = entry.get("warnings", [])
        self.engine_data = entry.get("engine_data", {})
        self.findings = findings
        self.source_records = entry.get("source_records", [])
        self.pages = entry.get("pages", [])

        class _N:
            sha256 = entry.get("sha256", row.sha256)
            parser_name = entry.get("parser") or ""

        self.normalized = _N()


class _FindingView:
    """FindingRow를 report_engine의 Finding 인터페이스로 변환한다."""

    def __init__(self, row: FindingRow, evidence: List[Dict[str, Any]], reveal_sealed: bool) -> None:
        from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
        from packages.common.schemas import BBox

        self.finding_id = row.id
        self.type = FindingType(row.type)
        self.status = VerificationStatus(row.status)
        self.severity = Severity(row.severity)
        self.evidence_grade = EvidenceGrade(row.evidence_grade or "U")
        self.confidence = row.confidence or 0.0
        self.document_id = row.document_id
        self.block_id = row.block_id
        self.page = row.page
        self.title = row.title or ""
        self.detail = row.detail or ""
        self.engine = row.engine or ""
        self.advisory_only = bool(row.advisory_only)
        self.review_status = row.review_status
        self.review_note = row.review_note
        self.tags = list(row.tags or [])
        self._data = dict(row.data or {})
        self._has_sealed = bool(row.sealed_excerpt) or bool(self._data.get("has_sealed_content"))
        self.sealed_excerpt = row.sealed_excerpt if reveal_sealed else None
        bbox = self._data.get("bbox")
        self.bbox = BBox(*bbox) if bbox else None
        self._evidence = evidence
        self._reveal = reveal_sealed

    def to_dict(self, reveal_sealed: bool = False) -> Dict[str, Any]:
        data = dict(self._data)
        for key in ("finding_id", "type", "status", "severity", "evidence_grade", "confidence",
                    "document_id", "block_id", "page", "title", "detail", "engine", "advisory_only", "tags"):
            value = getattr(self, key)
            data[key] = str(value) if key in ("type", "status", "severity", "evidence_grade") else value
        data["review_status"] = self.review_status
        data["review_note"] = self.review_note
        data["sealed_excerpt"] = self.sealed_excerpt if (reveal_sealed and self._reveal) else None
        data["has_sealed_content"] = self._has_sealed
        data["evidence"] = self._evidence
        return data if reveal_sealed else remove_sealed(data)


def _load_run_view(session: Session, run: VerificationRun, reveal_sealed: bool) -> _RunView:
    rows = session.execute(select(FindingRow).where(FindingRow.run_id == run.id,
                                                  FindingRow.project_id == run.project_id)).scalars().all()
    findings: List[_FindingView] = []
    for row in rows:
        evidence = [
            e.data for e in session.execute(select(EvidenceRow).where(EvidenceRow.finding_id == row.id)).scalars().all()
        ]
        if not reveal_sealed:
            evidence = [
                {**item, "excerpt": None} if item.get("sealed") else item for item in evidence
            ]
        findings.append(_FindingView(row, evidence, reveal_sealed))

    result_json = run.result_json or {}
    documents: List[_DocumentView] = []
    for document_id in run.document_ids or []:
        document_row = session.get(Document, document_id)
        if document_row is None or document_row.project_id != run.project_id:
            continue
        documents.append(
            _DocumentView(document_row, [f for f in findings if f.document_id == document_id], result_json)
        )
    return _RunView(run, findings, documents)


@router.post("/projects/{project_id}/reports", status_code=201)
def create_report(project_id: str, payload: ReportRequest, session: Session = Depends(get_db)) -> Dict[str, Any]:
    project = require_project(session, project_id, "MEMBER")
    run = (
        session.get(VerificationRun, payload.run_id)
        if payload.run_id
        else session.execute(
            select(VerificationRun)
            .where(VerificationRun.project_id == project_id,
                   VerificationRun.state.in_(("COMPLETED", "PARTIAL_COMPLETED")))
            .order_by(VerificationRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    )
    if run is None:
        raise HTTPException(404, "검증 Run이 없다")
    if run.project_id != project_id:
        raise HTTPException(404, "현재 프로젝트의 검증 결과가 아닙니다")
    if run.state not in ("COMPLETED", "PARTIAL_COMPLETED"):
        raise HTTPException(409, "완료된 검증 결과만 보고서로 생성할 수 있습니다")
    if payload.include_sealed:
        raise HTTPException(403, "보호된 내용은 개별 열람 승인 후에만 확인할 수 있습니다")
    if payload.audience == "SHAREABLE" and "highlight" in payload.formats:
        raise HTTPException(422, "원본 내용을 포함하는 highlight 형식은 공유용 보고서에서 제외하세요")

    view = _load_run_view(session, run, False)
    engine = remove_sealed(json.loads(to_json(view)))
    # Store the draft's engine evidence once. Finalization never reloads engine output.
    if run.result_json:
        for key in ("documents", "project_findings"):
            if key in run.result_json:
                engine[key] = remove_sealed(copy.deepcopy(run.result_json[key]))
    audit = make_audit(session)
    manifest = project_manifest(project_id, session=session)
    manifest["input_snapshot"] = run.input_snapshot or {}
    report = ReportRow(id=new_uuid("rpt_"), created_at=datetime.utcnow(),
                       project_id=project_id, run_id=run.id, formats=payload.formats, include_sealed=False)
    metadata = {"report_id": report.id, "source_report_id": None, "state": "DRAFT",
                "audience": payload.audience, "created_by": current_principal().user_id,
                "created_at": report.created_at.isoformat(), "finalized_by": None, "finalized_at": None,
                "note": "", "source_run_id": run.id, "source_run_hash": canonical_hash(engine)}
    snapshot = _snapshot(session, project, run, engine, metadata, manifest)
    review = _save_review(session, report, snapshot)
    _generate_artifacts(session, report, review, project, audit, strict=False)
    session.commit()
    audit.record(
        AuditEventType.REPORT_GENERATED,
        {"report_id": report.id, "run_id": run.id, "formats": payload.formats,
         "include_sealed": False, "state": "DRAFT", "snapshot_hash": review.snapshot_hash},
        actor=current_principal().user_id, project_id=project_id,
    )
    return _report_response(report, review)


@router.get("/projects/{project_id}/reports")
def list_reports(project_id: str, session: Session = Depends(get_db)):
    require_project(session, project_id)
    rows = session.scalars(select(ReportRow).where(ReportRow.project_id == project_id)
                           .order_by(ReportRow.created_at.desc())).all()
    return [_report_response(r, session.get(ReportReview, r.id)) for r in rows]


def _human_review(session, project, run, engine=None):
    rows = session.scalars(select(FindingRow).where(FindingRow.run_id == run.id,
        FindingRow.project_id == project.id).order_by(FindingRow.id)).all()
    by_id = {row.id: row for row in rows}
    frozen_findings = ([f for d in engine.get("documents", []) for f in d.get("findings", [])]
                       + engine.get("project_findings", [])) if engine else []
    workflow = []
    for finding in frozen_findings:
        row = by_id.get(finding.get("finding_id"))
        value = workflow_value(session, row) if row else {"finding_id": finding.get("finding_id"),
            "workflow_state": "NOT_STARTED", "decision": "UNDECIDED", "revision": 0}
        workflow.append({**value, "title": finding.get("title"), "system_status": finding.get("status")})
    if engine is None:
        workflow = [{**workflow_value(session, row), "title": row.title, "system_status": row.status} for row in rows]
    if engine is not None:
        from types import SimpleNamespace
        matrix_run = SimpleNamespace(id=run.id, result_json=engine, input_snapshot=engine.get("input_snapshot", {}))
    else:
        matrix_run = run
    matrix = matrix_data(session, project.id, matrix_run)
    return {"workflow": workflow, "matrix": matrix,
            "case_profile": as_dict(session.get(CaseProfile, project.id)),
            "review_history": [as_dict(row) for row in session.scalars(select(ReviewRevision).where(
                ReviewRevision.project_id == project.id).order_by(ReviewRevision.id))]}


def _preflight(project, engine, human):
    findings = [f for d in engine.get("documents", []) for f in d.get("findings", [])]
    findings += engine.get("project_findings", [])
    incomplete = [row for row in human["workflow"] if row["workflow_state"] != "COMPLETED"
                  or row.get("decision") == "UNDECIDED"]
    claims = human["matrix"]["claims"]
    incomplete_claims = [row for row in claims if row["review_status"] in ("UNASSESSED", "EVIDENCE_EXCLUDED")
                         or row.get("assessment", {}).get("position", "UNASSESSED") == "UNASSESSED"]
    unresolved_claims = [row for row in claims if row["review_status"] in
                         ("UNASSESSED", "PARTIAL", "CONFLICTING", "INSUFFICIENT", "EVIDENCE_EXCLUDED")
                         or row.get("assessment", {}).get("missing_material")]
    unresolved = [f for f in findings if f.get("status") != "VERIFIED"]
    sensitive_types = {"REDACTION_FAILURE", "PRIVILEGE_EXPOSURE_RISK", "OUTBOUND_LEAK_RISK",
                       "AUTHORSHIP_METADATA_LEAK", "GEOLOCATION_METADATA_LEAK", "RESIDUAL_COMMENT",
                       "RESIDUAL_TRACKED_CHANGE", "DELETED_TEXT_RECOVERABLE"}
    concerns = [{"finding_id": f.get("finding_id"), "type": f.get("type"), "title": f.get("title"),
                 "has_sealed_content": bool(f.get("has_sealed_content"))}
                for f in findings if f.get("has_sealed_content") or f.get("type") in sensitive_types]
    from packages.pii_engine import detect
    for doc in engine.get("documents", []):
        matches = detect(json.dumps(doc, ensure_ascii=False, default=str))
        if matches:
            concerns.append({"type": "PERSONAL_DATA", "document_id": doc.get("document_id"),
                             "title": "탐지된 개인정보", "kinds": sorted({m.kind for m in matches}),
                             "count": len(matches)})
    if any(item.get("note") for item in human["workflow"]) or human.get("review_history"):
        concerns.append({"type": "INTERNAL_REVIEW", "title": "내부 검토 메모와 이력이 포함되어 있습니다"})
    expected = engine.get("input_snapshot", {}).get("scope_revision")
    stale = expected is None or expected != project.scope_revision
    missing_sources = engine.get("unavailable_sources", [])
    unverified_items = engine.get("unverified_items", [])
    unavailable_stages = []
    unavailable_codes = {"UNVERIFIED", "PARTIALLY_VERIFIED", "UNAVAILABLE", "UNSUPPORTED", "BLOCKED",
                         "FAILED", "ERROR", "TIMEOUT", "MISSING_KEY", "DISABLED", "RATE_LIMITED", "NOT_REQUESTED"}

    def recorded_limits(value, path="", key=""):
        if key == "unavailable_stages" and value:
            unavailable_stages.append({"path": path, "record": value})
        elif isinstance(value, dict):
            for name, item in value.items():
                recorded_limits(item, f"{path}.{name}", name)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                recorded_limits(item, f"{path}[{index}]", key)
        elif isinstance(value, str) and (key in {"status", "verdict", "state"} or key.endswith("_status") or ".levels." in path):
            if value.upper() in unavailable_codes:
                unavailable_stages.append({"path": path, "recorded_status": value})

    for doc in engine.get("documents", []):
        for key in ("engine_data", "source_records", "authorship"):
            recorded_limits(doc.get(key, {}), f"documents[{doc.get('document_id')}].{key}")
    needs_unresolved = bool(incomplete or incomplete_claims or unresolved_claims or unresolved or unverified_items
                            or unavailable_stages or missing_sources or engine.get("errors") or engine.get("state") == "PARTIAL_COMPLETED")
    data = {"incomplete_reviews": incomplete, "incomplete_claim_reviews": incomplete_claims,
            "unresolved_claims": unresolved_claims,
            "unresolved_findings": unresolved, "unverified_items": unverified_items,
            "unavailable_stages": unavailable_stages,
            "unavailable_sources": missing_sources, "errors": engine.get("errors", []),
            "stale_scope": stale, "run_scope_revision": expected, "current_scope_revision": project.scope_revision,
            "sensitive_concerns": concerns,
            "privacy_notice": "보고서에는 사건 정보가 포함될 수 있습니다. 공유 범위와 마스킹 결과를 직접 확인하세요.",
            "required_acknowledgments": {"acknowledge_unresolved": needs_unresolved,
                                         "acknowledge_stale_scope": stale, "acknowledge_privacy": True}}
    data["preflight_hash"] = canonical_hash({"checks": data, "human_review": human,
                                            "source_run_hash": canonical_hash(engine)})
    return data


def _snapshot(session, project, run, engine, metadata, manifest, human=None):
    human = human or _human_review(session, project, run, engine)
    snapshot = remove_sealed({"schema_version": 2, "report": metadata, "engine_result": engine,
                **human, "preflight": _preflight(project, engine, human), "manifest": manifest,
                "terminology": terminology_catalog()})
    return snapshot


def _save_review(session, report, snapshot):
    meta = snapshot["report"]
    review = ReportReview(report_id=report.id, audience=meta["audience"], state=meta["state"],
                          created_by=meta["created_by"], finalized_by=meta.get("finalized_by"),
                          finalized_at=datetime.fromisoformat(meta["finalized_at"]) if meta.get("finalized_at") else None,
                          note=meta.get("note", ""), review_snapshot=copy.deepcopy(snapshot),
                          snapshot_hash=canonical_hash(snapshot))
    return review


def _report_response(report, review):
    meta = (review.review_snapshot or {}).get("report", {}) if review else {}
    return {"report_id": report.id, "project_id": report.project_id, "run_id": report.run_id,
            "formats": report.formats, "artifacts": report.artifacts, "include_sealed": report.include_sealed,
            "created_at": report.created_at.isoformat(), "state": review.state if review else "DRAFT",
            "audience": review.audience if review else "INTERNAL", "created_by": review.created_by if review else None,
            "finalized_by": review.finalized_by if review else None,
            "finalized_at": review.finalized_at.isoformat() if review and review.finalized_at else None,
            "note": review.note if review else "", "snapshot_hash": review.snapshot_hash if review else None,
            "source_report_id": meta.get("source_report_id"),
            "label": report_label(review.state if review else "DRAFT", review.audience if review else "INTERNAL")}


def _report_or_404(session, report_id, minimum="VIEWER"):
    report = session.get(ReportRow, report_id)
    if report is None:
        raise HTTPException(404, "보고서를 찾을 수 없습니다")
    require_project(session, report.project_id, minimum)
    run = session.get(VerificationRun, report.run_id)
    if not run or run.project_id != report.project_id:
        raise HTTPException(404, "현재 프로젝트의 검증 결과가 아닙니다")
    return report, run


def _checked_snapshot(review):
    if not review or not review.review_snapshot:
        raise HTTPException(409, "이전 보고서에는 고정 스냅샷이 없습니다. 새 초안을 생성하세요")
    if canonical_hash(review.review_snapshot) != review.snapshot_hash:
        raise HTTPException(409, "보고서 스냅샷 무결성을 확인할 수 없습니다")
    return copy.deepcopy(review.review_snapshot)


@router.get("/reports/{report_id}/preflight")
def report_preflight(report_id: str, session: Session = Depends(get_db)):
    report, run = _report_or_404(session, report_id)
    review = session.get(ReportReview, report.id)
    snapshot = _checked_snapshot(review)
    project = session.get(Project, report.project_id)
    human = _human_review(session, project, run, snapshot["engine_result"])
    result = _preflight(project, snapshot["engine_result"], human)
    return {**result, "report_id": report_id, "state": review.state, "audience": review.audience,
            "snapshot_hash": review.snapshot_hash}


@router.post("/reports/{report_id}/finalize", status_code=201)
def finalize_report(report_id: str, payload: ReportFinalizeRequest, session: Session = Depends(get_db)):
    draft, run = _report_or_404(session, report_id, "MEMBER")
    previous = session.get(ReportReview, draft.id)
    frozen = _checked_snapshot(previous)
    if previous.state != "DRAFT":
        raise HTTPException(409, "확정본은 변경하거나 다시 확정할 수 없습니다")
    project = session.get(Project, draft.project_id)
    human = _human_review(session, project, run, frozen["engine_result"])
    checks = _preflight(project, frozen["engine_result"], human)
    if payload.expected_preflight_hash and payload.expected_preflight_hash != checks["preflight_hash"]:
        raise HTTPException(409, {"message": "검토 또는 범위가 변경되었습니다. 사전 점검을 다시 확인하세요", "preflight": checks})
    missing = [name for name, required in checks["required_acknowledgments"].items()
               if required and not getattr(payload, name)]
    if missing:
        raise HTTPException(409, {"message": "잔여 검토와 공유 범위를 명시적으로 확인하세요",
                                  "missing_acknowledgments": missing, "preflight": checks})
    final = ReportRow(id=new_uuid("rpt_"), created_at=datetime.utcnow(),
                      project_id=draft.project_id, run_id=draft.run_id,
                      formats=list(draft.formats), include_sealed=False)
    now = datetime.utcnow().isoformat()
    metadata = {**frozen["report"], "report_id": final.id, "source_report_id": draft.id,
                "source_snapshot_hash": previous.snapshot_hash, "state": "FINAL",
                "created_at": final.created_at.isoformat(), "draft_created_at": draft.created_at.isoformat(),
                "finalized_by": current_principal().user_id, "finalized_at": now, "note": payload.note,
                "acknowledgments": payload.model_dump(exclude={"note", "expected_preflight_hash"})}
    audit = make_audit(session)
    snapshot = _snapshot(session, project, run, frozen["engine_result"], metadata,
                         project_manifest(project.id, session=session), human=human)
    review = _save_review(session, final, snapshot)
    _generate_artifacts(session, final, review, project, audit, strict=True)
    session.commit()
    audit.record(AuditEventType.REPORT_GENERATED, {"report_id": final.id, "source_report_id": draft.id,
                 "state": "FINAL", "snapshot_hash": review.snapshot_hash},
                 actor=current_principal().user_id, project_id=project.id)
    return _report_response(final, review)


def _generate_artifacts(session, report, review, project, audit, *, strict):
    snapshot = _checked_snapshot(review)
    # The private review snapshot remains complete; exports receive a documented projection.
    if review.audience == "SHAREABLE":
        snapshot = shareable_snapshot(snapshot)
    export_hash = canonical_hash(snapshot)
    view = view_from_snapshot(snapshot, review.snapshot_hash)
    view.report_metadata["export_snapshot_hash"] = export_hash
    manifest = {**snapshot["manifest"], "report": view.report_metadata,
                "input_snapshot": view.input_snapshot, "terminology": terminology_catalog()}
    rendered, artifacts = {}, {}
    for fmt in report.formats:
        try:
            data = _render(fmt, view, project, manifest, audit, session, False)
            if data is None:
                raise ValueError("이 실행에는 해당 형식으로 출력할 문서가 없습니다")
            rendered[fmt] = data
        except Exception as exc:
            if strict:
                session.rollback()
                raise HTTPException(409, {"message": "산출물 생성 실패로 확정되지 않았습니다", "format": fmt,
                                          "error": type(exc).__name__}) from exc
            artifacts[fmt] = {"error": f"{type(exc).__name__}: 산출물을 생성하지 못했습니다"}
    storage = get_storage()
    artifact_rows = []
    try:
        for fmt, data in rendered.items():
            digest = sha256_bytes(data)
            key = storage.put_derivative(f"{report.project_id}/{report.id}/{digest}.{_extension(fmt)}", data)
            artifact_rows.append(ExportArtifactRow(report_id=report.id, format=fmt, storage_key=key,
                                                  sha256=digest, size_bytes=len(data)))
            artifacts[fmt] = {"storage_key": key, "sha256": digest, "size_bytes": len(data),
                              "download": f"/api/reports/{report.id}/download/{fmt}"}
    except Exception:
        session.rollback()
        raise
    report.artifacts = artifacts
    # Rendering and object storage must not hold SQLite's writer lock or block job heartbeats.
    session.add(report)
    session.flush()
    session.add(review)
    session.flush()
    session.add_all(artifact_rows)


def _extension(fmt: str) -> str:
    return {"pdf": "pdf", "highlight": "highlight.pdf", "xlsx": "xlsx", "csv": "csv",
            "json": "json", "manifest": "manifest.json"}.get(fmt, fmt)


def _render(fmt: str, view: _RunView, project: Project, manifest: Dict[str, Any], audit: Any,
            session: Session, include_sealed: bool) -> Optional[bytes]:
    if fmt == "json":
        return to_json(view, reveal_sealed=include_sealed)
    if fmt == "csv":
        return to_csv(view.all_findings, reveal_sealed=include_sealed,
                      report_metadata=getattr(view, "report_metadata", None))
    if fmt == "xlsx":
        return to_xlsx(view, reveal_sealed=include_sealed)
    if fmt == "manifest":
        return json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    if fmt == "docx":
        from packages.report_engine import build_report_docx
        return build_report_docx(view, project=view.input_snapshot.get("project") or {"name": project.name},
                                 manifest=manifest)
    if fmt == "pdf":
        return build_report_pdf(
            view,
            project=view.input_snapshot.get("project") or {"name": project.name, "case_number": project.case_number, "court": project.court},
            manifest=manifest,
            reveal_sealed=include_sealed,
        )
    if fmt == "highlight":
        storage = get_storage()
        for document in view.documents:
            row = session.get(Document, document.document_id)
            if row is None or not row.filename.lower().endswith(".pdf"):
                continue
            source = storage.get(row.storage_key)
            if sha256_bytes(source) != document.normalized.sha256:
                raise ValueError("원본 문서의 해시가 실행 시점과 다릅니다")
            highlighted = build_highlight_pdf(source, document.findings)
            if hasattr(view, "report_metadata"):
                import io
                from pypdf import PdfReader, PdfWriter
                writer = PdfWriter()
                cover = build_report_pdf(view, project=view.input_snapshot.get("project"), manifest=manifest)
                for part in (cover, highlighted):
                    for page in PdfReader(io.BytesIO(part)).pages:
                        writer.add_page(page)
                output = io.BytesIO()
                writer.write(output)
                return output.getvalue()
            return highlighted
        return None
    raise ValueError(f"지원하지 않는 형식이다: {fmt}")


@router.get("/reports/{report_id}")
def get_report(report_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    report, _ = _report_or_404(session, report_id)
    return _report_response(report, session.get(ReportReview, report.id))


@router.get("/reports/{report_id}/download/{fmt}")
def download_report(report_id: str, fmt: str, session: Session = Depends(get_db)) -> Response:
    report, _ = _report_or_404(session, report_id)
    artifact = (report.artifacts or {}).get(fmt)
    if not artifact or "storage_key" not in artifact:
        raise HTTPException(404, f"{fmt} 산출물이 없다")
    data = get_storage().get(artifact["storage_key"])
    if sha256_bytes(data) != artifact.get("sha256"):
        raise HTTPException(409, "저장된 보고서의 무결성을 확인할 수 없습니다")
    make_audit(session).record(
        AuditEventType.EXPORT,
        {"report_id": report_id, "format": fmt, "sha256": artifact.get("sha256")},
        actor=current_principal().user_id, project_id=report.project_id,
    )
    filename = f"verification_{report_id}.{_extension(fmt)}"
    return Response(
        content=data,
        media_type=MEDIA_TYPES.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
