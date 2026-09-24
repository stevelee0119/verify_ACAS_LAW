"""프로젝트 및 문서 업로드 엔드포인트 (제18.1장)."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import uuid4
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from packages.common.config import get_settings
from packages.common.enums import AuditEventType
from packages.common.storage import get_storage, sha256_bytes
from packages.document_engine import ALLOWED_EXTENSIONS, guess_mime

from ..db import Document, DocumentVersion, Project, VerificationRun, get_db
from ..job_control import DurableJob, TERMINAL
from ..project_lifecycle import lock_project
from ..project_purge import purge_files, purge_rows
from ..workspace import ReportJob
from ..schemas import DocumentOut, ProjectCreate, ProjectOut, ProjectUpdate, DocumentUpdate, DocumentScopeUpdate
from ..services import make_audit
from ..security import scan_upload
from ..access import project_scoped
from ..identity import (actor_id, apply_organization_policy, filter_project_query,
                        project_creation_defaults, require_project, project_role)

router = APIRouter(tags=["projects"])
logger = logging.getLogger(__name__)


def _project_out(session: Session, project: Project) -> ProjectOut:
    count = session.execute(
        select(func.count(Document.id)).where(Document.project_id == project.id)
    ).scalar_one()
    return ProjectOut(
        id=project.id,
        name=project.name,
        case_number=project.case_number,
        court=project.court,
        case_type=project.case_type,
        parties=list(project.parties or []),
        incident_date=project.incident_date,
        purpose=project.purpose or "",
        tags=list(project.tags or []),
        memo=project.memo or "",
        external_ai_policy=project.external_ai_policy or "MASKED",
        verification_profile=project.verification_profile or "STANDARD",
        requested_issues=list(project.requested_issues or []),
        created_at=project.created_at,
        document_count=count,
        included_document_count=session.scalar(select(func.count(Document.id)).where(
            Document.project_id == project.id, Document.included_in_verification.is_(True))) or 0,
        scope_revision=project.scope_revision or 0,
        key_dates=project.key_dates or {},
        deleted_at=project.deleted_at,
        can_delete=project_role(session, project) == "ADMIN",
    )


@router.post("/projects", response_model=ProjectOut, status_code=201)
@project_scoped
def create_project(payload: ProjectCreate = ProjectCreate(), session: Session = Depends(get_db)) -> ProjectOut:
    defaults = project_creation_defaults(session)
    if payload.creation_key:
        existing = session.scalar(select(Project).where(Project.creation_key == payload.creation_key))
        if existing:
            require_project(session, existing.id, "MEMBER")
            return _project_out(session, existing)
    project = Project(
        name=payload.name or default_project_name(),
        creation_key=payload.creation_key,
        case_number=payload.case_number,
        court=payload.court,
        case_type=payload.case_type,
        parties=payload.parties,
        incident_date=payload.incident_date,
        key_dates=payload.key_dates,
        purpose=payload.purpose,
        tags=payload.tags,
        memo=payload.memo,
        external_ai_policy=apply_organization_policy(session, {"external_ai_policy": payload.external_ai_policy})["external_ai_policy"],
        verification_profile=payload.verification_profile,
        requested_issues=payload.requested_issues,
        enabled_advisory_signals=payload.enabled_advisory_signals,
        **defaults,
    )
    session.add(project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Project).where(Project.creation_key == payload.creation_key)) if payload.creation_key else None
        if existing is None:
            raise
        require_project(session, existing.id, "MEMBER")
        return _project_out(session, existing)
    make_audit(session).record(AuditEventType.USER_OVERRIDE, {"action": "PROJECT_CREATED"},
                              project_id=project.id, actor=actor_id())
    return _project_out(session, project)


def default_project_name() -> str:
    return f"새 검토 {datetime.now().astimezone():%Y-%m-%d} {uuid4().hex[:6]}"


@router.get("/project-defaults")
def project_defaults():
    return {**ProjectCreate().model_dump(), "name": default_project_name(), "creation_key": uuid4().hex}


def bump_scope(session: Session, project_id: str) -> None:
    session.execute(update(Project).where(Project.id == project_id).values(scope_revision=Project.scope_revision + 1))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, session: Session = Depends(get_db)):
    project = require_project(session, project_id, "MEMBER")
    changes = apply_organization_policy(session, payload.model_dump(exclude_unset=True, exclude={"creation_key"}), project)
    if "name" in changes and not changes["name"]:
        changes["name"] = default_project_name()
    for key, value in changes.items():
        setattr(project, key, value)
    if changes:
        session.flush()
        bump_scope(session, project_id)
    session.commit()
    session.refresh(project)
    make_audit(session).record(AuditEventType.USER_OVERRIDE, {"action": "PROJECT_UPDATED", "fields": list(changes)}, project_id=project_id, actor=actor_id())
    return _project_out(session, project)


@router.patch("/projects/{project_id}/document-scope", response_model=List[DocumentOut])
def update_scope(project_id: str, payload: DocumentScopeUpdate, session: Session = Depends(get_db)):
    require_project(session, project_id, "MEMBER")
    documents = session.scalars(select(Document).where(Document.project_id == project_id,
        Document.id.in_(set(payload.document_ids)))).all()
    if len(documents) != len(set(payload.document_ids)):
        raise HTTPException(404, "현재 사건에 속한 문서만 선택할 수 있습니다")
    changed = []
    for document in documents:
        if document.included_in_verification != payload.included_in_verification:
            document.included_in_verification = payload.included_in_verification
            document.exclusion_reason = payload.exclusion_reason if not payload.included_in_verification else ""
            document.scope_changed_at = datetime.utcnow()
            document.scope_changed_by = actor_id()
            changed.append(document.id)
    if changed:
        session.flush()
        bump_scope(session, project_id)
    session.commit()
    if changed:
        make_audit(session).record(AuditEventType.USER_OVERRIDE,
            {"action": "DOCUMENT_SCOPE_CHANGED", "document_ids": changed,
             "included": payload.included_in_verification, "reason": payload.exclusion_reason}, project_id=project_id, actor=actor_id())
    return [_document_out(session, d) for d in documents]


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(document_id: str, payload: DocumentUpdate, session: Session = Depends(get_db)):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    require_project(session, document.project_id, "MEMBER")
    changes = payload.model_dump(exclude_unset=True, exclude={"included_in_verification", "exclusion_reason"})
    for key, value in changes.items():
        if value is not None or key == "submitted_on":
            setattr(document, key, value)
    if payload.submitted_by:
        document.is_own_document = payload.submitted_by == "OWN"
    if changes:
        session.flush()
        bump_scope(session, document.project_id)
    session.commit()
    if changes:
        make_audit(session).record(AuditEventType.USER_OVERRIDE,
            {"action": "DOCUMENT_UPDATED", "fields": list(changes)}, project_id=document.project_id,
            document_id=document.id, actor=actor_id())
    if payload.included_in_verification is not None:
        update_scope(document.project_id, DocumentScopeUpdate(document_ids=[document.id],
            included_in_verification=payload.included_in_verification, exclusion_reason=payload.exclusion_reason), session)
    return _document_out(session, document)


@router.get("/projects", response_model=List[ProjectOut])
@project_scoped
def list_projects(deleted: bool = False, session: Session = Depends(get_db)) -> List[ProjectOut]:
    query = filter_project_query(select(Project), session, include_deleted=deleted)
    if deleted:
        query = query.where(Project.deleted_at.is_not(None))
    projects = session.execute(query.order_by(Project.created_at.desc())).scalars().all()
    if deleted:
        projects = [p for p in projects if project_role(session, p) == "ADMIN"]
    return [_project_out(session, p) for p in projects]


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, session: Session = Depends(get_db)):
    lock_project(session, project_id)
    project = require_project(session, project_id, "ADMIN", include_deleted=True)
    if project.deleted_at is None:
        active_run = session.scalar(select(VerificationRun.id).where(
            VerificationRun.project_id == project_id, VerificationRun.state.not_in(TERMINAL)).limit(1))
        active_job = session.scalar(select(DurableJob.run_id).where(
            DurableJob.project_id == project_id, DurableJob.state.not_in(TERMINAL)).limit(1))
        if active_run or active_job:
            raise HTTPException(409, "진행 중이거나 대기 중인 검증이 있습니다. 완료 후 또는 검증 취소 후 삭제하세요.")
        project.deleted_at, project.deleted_by = datetime.utcnow(), actor_id()
        session.commit()
        make_audit(session).record(AuditEventType.USER_OVERRIDE, {"action": "PROJECT_TRASHED"},
                                  project_id=project_id, actor=actor_id())
    return Response(status_code=204)


@router.post("/projects/{project_id}/restore", response_model=ProjectOut)
def restore_project(project_id: str, session: Session = Depends(get_db)):
    lock_project(session, project_id)
    project = require_project(session, project_id, "ADMIN", include_deleted=True)
    if project.deleted_at is not None:
        project.deleted_at = project.deleted_by = None
        session.commit()
        make_audit(session).record(AuditEventType.USER_OVERRIDE, {"action": "PROJECT_RESTORED"},
                                  project_id=project_id, actor=actor_id())
    return _project_out(session, project)


@router.delete("/projects/{project_id}/purge")
def purge_project(project_id: str, session: Session = Depends(get_db)):
    """휴지통에 있는 프로젝트를 영구 삭제한다. 되돌릴 수 없다.

    휴지통에 넣지 않은 프로젝트는 바로 지우지 않는다(실수로 한 번에 지우는 일을 막는다).
    감사기록은 남기고, 원본·보고서 파일과 가명 처리 보관소는 DB 삭제를 커밋한 뒤 지운다.
    """
    lock_project(session, project_id)
    project = require_project(session, project_id, "ADMIN", include_deleted=True)
    if project.deleted_at is None:
        raise HTTPException(409, "휴지통에 있는 프로젝트만 영구 삭제할 수 있습니다. 먼저 휴지통으로 이동하세요.")
    from .reports import expire_stale_jobs  # 서버 재시작 등으로 멈춘 작업이 삭제를 막지 않게 먼저 닫는다
    expire_stale_jobs(session, project_id)
    active_job = session.scalar(select(ReportJob.id).where(
        ReportJob.project_id == project_id, ReportJob.state.in_(("QUEUED", "RUNNING"))).limit(1))
    if active_job:
        raise HTTPException(409, "이 프로젝트의 보고서를 만드는 중입니다. 생성이 끝난 뒤 다시 시도하세요. 서버 재시작 등으로 멈춘 작업은 진행 기록이 2분간 없으면 중단된 것으로 정리됩니다.")
    counts = purge_rows(session, project_id)
    session.commit()
    files = purge_files(project_id)
    make_audit(session).record(AuditEventType.DELETE,
                               {"action": "PROJECT_PURGED", "rows": counts,
                                "files_removed": files["files_removed"], "file_errors": files["file_errors"]},
                               project_id=project_id, actor=actor_id())
    return {"project_id": project_id, "purged": True, "rows": counts, **files}


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_db)) -> ProjectOut:
    project = require_project(session, project_id)
    return _project_out(session, project)


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    project_id: str,
    response: Response,
    file: UploadFile = File(...),
    document_kind: str = Form(""),
    is_own_document: bool = Form(False),
    session: Session = Depends(get_db),
) -> DocumentOut:
    # FastAPI runs this blocking file/DB work in its thread pool, not the event loop.
    request_id = uuid4().hex
    response.headers["X-Request-ID"] = request_id
    try:
        return _store_document(project_id, file, document_kind, is_own_document, session)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "X-Request-ID": request_id}
        raise
    except (OSError, SQLAlchemyError) as exc:
        session.rollback()
        database_error = isinstance(exc, SQLAlchemyError)
        code = "UPLOAD_DATABASE_UNAVAILABLE" if database_error else "UPLOAD_STORAGE_UNAVAILABLE"
        message = ("자료 등록 정보를 저장하지 못했습니다. 등록 내역을 확인한 뒤 다시 시도하세요."
                   if database_error else "서버에서 파일을 읽거나 저장하지 못했습니다. 관리자가 저장소 권한과 남은 공간을 확인해야 합니다.")
        # Never log exception values: SQL parameters and file paths may contain case data.
        logger.error("upload_failed request_id=%s code=%s error_type=%s errno=%s",
                     request_id, code, type(exc).__name__, getattr(exc, "errno", None))
        raise HTTPException(503, {"code": code, "message": message, "request_id": request_id},
                            headers={"X-Request-ID": request_id}) from None


def _store_document(project_id: str, file: UploadFile, document_kind: str,
                    is_own_document: bool, session: Session) -> DocumentOut:
    """업로드 → 검증 → SHA-256 → Immutable Original 저장 (제6장, 제15.1장)."""
    project = require_project(session, project_id, "MEMBER")

    settings = get_settings()
    filename = _safe_filename(file.filename or "unnamed")
    chunks, size = [], 0
    while chunk := file.file.read(1024 * 1024):
        size += len(chunk)
        if size > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"파일 크기가 {settings.max_upload_mb}MB를 초과합니다")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "빈 파일이다")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"파일 크기가 {settings.max_upload_mb}MB를 초과한다")

    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            415,
            f"지원하지 않는 형식이다: {suffix or '확장자 없음'}. 지원 형식: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    issue = scan_upload(filename, data)
    if issue:
        raise HTTPException(400, issue)

    digest = sha256_bytes(data)
    lock_project(session, project_id)
    require_project(session, project_id, "MEMBER")
    storage = get_storage()
    storage_key = storage.put_original(f"{project_id}/{digest}{suffix}", data)

    existing = session.execute(
        select(Document).where(Document.project_id == project_id, Document.sha256 == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return _document_out(session, existing)

    document = Document(
        project_id=project_id,
        filename=filename,
        mime_type=guess_mime(filename, file.content_type or ""),
        size_bytes=len(data),
        sha256=digest,
        storage_key=storage_key,
        document_kind=document_kind,
        is_own_document=is_own_document,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentVersion(document_id=document.id, version=1, sha256=digest, storage_key=storage_key,
                        kind="ORIGINAL", note="최초 업로드 원본")
    )
    bump_scope(session, project_id)
    session.commit()

    audit = make_audit(session)
    audit.record(
        AuditEventType.UPLOAD,
        {"filename": filename, "size": len(data), "mime": document.mime_type, "storage_key": storage_key},
        project_id=project_id,
        document_id=document.id,
        actor=actor_id(),
    )
    audit.record(
        AuditEventType.HASH_CREATED,
        {"algorithm": "SHA-256", "sha256": digest},
        project_id=project_id,
        document_id=document.id,
        actor=actor_id(),
    )
    return _document_out(session, document)


@router.get("/projects/{project_id}/documents", response_model=List[DocumentOut])
def list_documents(project_id: str, session: Session = Depends(get_db)) -> List[DocumentOut]:
    require_project(session, project_id)
    documents = (
        session.execute(
            select(Document).where(Document.project_id == project_id).order_by(Document.uploaded_at)
        )
        .scalars()
        .all()
    )
    return [_document_out(session, d) for d in documents]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: Session = Depends(get_db)) -> DocumentOut:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "문서를 찾을 수 없다")
    require_project(session, document.project_id)
    return _document_out(session, document)


def _document_out(session: Session, document: Document) -> DocumentOut:
    versions = session.execute(
        select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == document.id)
    ).scalar_one()
    return DocumentOut(
        id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        mime_type=document.mime_type or "",
        size_bytes=document.size_bytes or 0,
        sha256=document.sha256,
        document_kind=document.document_kind or "",
        is_own_document=bool(document.is_own_document),
        quarantined=bool(document.quarantined),
        rag_indexable=bool(document.rag_indexable),
        uploaded_at=document.uploaded_at,
        version_count=versions or 1,
        included_in_verification=bool(document.included_in_verification),
        exclusion_reason=document.exclusion_reason or "",
        evidence_number=document.evidence_number or "",
        submitted_by=document.submitted_by or "UNSPECIFIED",
        submitted_on=document.submitted_on,
    )


UNSAFE_NAME_RE = re.compile(r"[\\/\x00-\x1f]")


def _safe_filename(name: str) -> str:
    """Path traversal 방어 (제21.1장)."""
    cleaned = UNSAFE_NAME_RE.sub("_", name).strip()
    cleaned = cleaned.replace("..", "_")
    return cleaned[:300] or "unnamed"
