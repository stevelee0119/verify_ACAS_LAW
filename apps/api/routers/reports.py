"""보고서 생성·다운로드 엔드포인트 (제18.1장, 제20장)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType
from packages.common.storage import get_storage, sha256_bytes
from packages.report_engine import build_highlight_pdf, build_report_pdf, to_csv, to_json, to_manifest, to_xlsx

from ..db import (
    Document,
    EvidenceRow,
    ExportArtifactRow,
    FindingRow,
    Project,
    ReportRow,
    VerificationRun,
    get_db,
)
from ..schemas import ReportRequest
from ..services import make_audit

router = APIRouter(tags=["reports"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "highlight": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "manifest": "application/json",
}


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
        self.documents = documents
        self.project_findings = [f for f in findings if not f.document_id]
        self._findings = findings

    @property
    def all_findings(self) -> List[Any]:
        return self._findings


class _DocumentView:
    def __init__(self, row: Document, findings: List[Any], result_json: Dict[str, Any]) -> None:
        self.document_id = row.id
        self.filename = row.filename
        self.quarantined = bool(row.quarantined)
        self.rag_indexable = bool(row.rag_indexable)
        entry = next((d for d in (result_json.get("documents") or []) if d.get("document_id") == row.id), {})
        self.citations = entry.get("citations", [])
        self.claims = entry.get("claims", [])
        self.entities = entry.get("entities", [])
        self.events = entry.get("events", [])
        self.authorship = entry.get("authorship", {})
        self.masked_preview = entry.get("masked_preview", {})
        self.warnings = entry.get("warnings", [])
        self.engine_data = entry.get("engine_data", {})
        self.findings = findings
        self.source_records: List[Any] = []

        class _N:
            sha256 = row.sha256
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
        self.tags = list(row.tags or [])
        self._data = dict(row.data or {})
        self.sealed_excerpt = row.sealed_excerpt if reveal_sealed else None
        bbox = self._data.get("bbox")
        self.bbox = BBox(*bbox) if bbox else None
        self._evidence = evidence
        self._reveal = reveal_sealed

    def to_dict(self, reveal_sealed: bool = False) -> Dict[str, Any]:
        data = dict(self._data)
        data["review_status"] = self.review_status
        data["sealed_excerpt"] = self.sealed_excerpt if (reveal_sealed and self._reveal) else None
        data["has_sealed_content"] = bool(self.sealed_excerpt) or bool(data.get("has_sealed_content"))
        data["evidence"] = self._evidence
        return data


def _load_run_view(session: Session, run: VerificationRun, reveal_sealed: bool) -> _RunView:
    rows = session.execute(select(FindingRow).where(FindingRow.run_id == run.id)).scalars().all()
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
        if document_row is None:
            continue
        documents.append(
            _DocumentView(document_row, [f for f in findings if f.document_id == document_id], result_json)
        )
    return _RunView(run, findings, documents)


@router.post("/projects/{project_id}/reports", status_code=201)
def create_report(project_id: str, payload: ReportRequest, session: Session = Depends(get_db)) -> Dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없다")

    run = (
        session.get(VerificationRun, payload.run_id)
        if payload.run_id
        else session.execute(
            select(VerificationRun)
            .where(VerificationRun.project_id == project_id)
            .order_by(VerificationRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    )
    if run is None:
        raise HTTPException(404, "검증 Run이 없다")

    view = _load_run_view(session, run, payload.include_sealed)
    audit = make_audit(session)
    manifest = audit.manifest(project_id=project_id)
    storage = get_storage()

    report = ReportRow(project_id=project_id, run_id=run.id, formats=payload.formats,
                       include_sealed=payload.include_sealed)
    session.add(report)
    session.flush()

    artifacts: Dict[str, Any] = {}
    for fmt in payload.formats:
        try:
            data = _render(fmt, view, project, manifest, audit, session, payload.include_sealed)
        except Exception as exc:  # 하나의 포맷 실패가 전체를 실패시키지 않는다
            artifacts[fmt] = {"error": str(exc)}
            continue
        if data is None:
            continue
        key = storage.put_derivative(f"{project_id}/{report.id}/report.{_extension(fmt)}", data)
        digest = sha256_bytes(data)
        session.add(
            ExportArtifactRow(report_id=report.id, format=fmt, storage_key=key, sha256=digest, size_bytes=len(data))
        )
        artifacts[fmt] = {"storage_key": key, "sha256": digest, "size_bytes": len(data),
                          "download": f"/api/reports/{report.id}/download/{fmt}"}

    report.artifacts = artifacts
    session.commit()

    audit.record(
        AuditEventType.REPORT_GENERATED,
        {"report_id": report.id, "run_id": run.id, "formats": payload.formats,
         "include_sealed": payload.include_sealed},
        project_id=project_id,
    )
    return {"report_id": report.id, "run_id": run.id, "artifacts": artifacts,
            "include_sealed": payload.include_sealed}


def _extension(fmt: str) -> str:
    return {"pdf": "pdf", "highlight": "highlight.pdf", "xlsx": "xlsx", "csv": "csv",
            "json": "json", "manifest": "manifest.json"}.get(fmt, fmt)


def _render(fmt: str, view: _RunView, project: Project, manifest: Dict[str, Any], audit: Any,
            session: Session, include_sealed: bool) -> Optional[bytes]:
    if fmt == "json":
        return to_json(view, reveal_sealed=include_sealed)
    if fmt == "csv":
        return to_csv(view.all_findings, reveal_sealed=include_sealed)
    if fmt == "xlsx":
        return to_xlsx(view, reveal_sealed=include_sealed)
    if fmt == "manifest":
        return json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    if fmt == "pdf":
        return build_report_pdf(
            view,
            project={"name": project.name, "case_number": project.case_number, "court": project.court},
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
            return build_highlight_pdf(source, document.findings)
        return None
    raise ValueError(f"지원하지 않는 형식이다: {fmt}")


@router.get("/reports/{report_id}")
def get_report(report_id: str, session: Session = Depends(get_db)) -> Dict[str, Any]:
    report = session.get(ReportRow, report_id)
    if report is None:
        raise HTTPException(404, "보고서를 찾을 수 없다")
    return {
        "report_id": report.id,
        "project_id": report.project_id,
        "run_id": report.run_id,
        "formats": report.formats,
        "artifacts": report.artifacts,
        "include_sealed": report.include_sealed,
        "created_at": report.created_at.isoformat(),
    }


@router.get("/reports/{report_id}/download/{fmt}")
def download_report(report_id: str, fmt: str, session: Session = Depends(get_db)) -> Response:
    report = session.get(ReportRow, report_id)
    if report is None:
        raise HTTPException(404, "보고서를 찾을 수 없다")
    artifact = (report.artifacts or {}).get(fmt)
    if not artifact or "storage_key" not in artifact:
        raise HTTPException(404, f"{fmt} 산출물이 없다")
    data = get_storage().get(artifact["storage_key"])
    make_audit(session).record(
        AuditEventType.EXPORT,
        {"report_id": report_id, "format": fmt, "sha256": artifact.get("sha256")},
        project_id=report.project_id,
    )
    filename = f"verification_{report_id}.{_extension(fmt)}"
    return Response(
        content=data,
        media_type=MEDIA_TYPES.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
