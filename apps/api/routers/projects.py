"""프로젝트 및 문서 업로드 엔드포인트 (제18.1장)."""
from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.config import get_settings
from packages.common.enums import AuditEventType
from packages.common.storage import get_storage, sha256_bytes
from packages.document_engine import ALLOWED_EXTENSIONS, guess_mime

from ..db import Document, DocumentVersion, Project, get_db
from ..schemas import DocumentOut, ProjectCreate, ProjectOut, ProjectUpdate, DocumentUpdate, DocumentScopeUpdate
from ..services import make_audit
from ..security import scan_upload
from ..access import project_scoped
from ..identity import (actor_id, apply_organization_policy, filter_project_query,
                        project_creation_defaults, require_project)

router = APIRouter(tags=["projects"])


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
def list_projects(session: Session = Depends(get_db)) -> List[ProjectOut]:
    projects = session.execute(filter_project_query(select(Project), session).order_by(Project.created_at.desc())).scalars().all()
    return [_project_out(session, p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_db)) -> ProjectOut:
    project = require_project(session, project_id)
    return _project_out(session, project)


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    document_kind: str = Form(""),
    is_own_document: bool = Form(False),
    session: Session = Depends(get_db),
) -> DocumentOut:
    """업로드 → 검증 → SHA-256 → Immutable Original 저장 (제6장, 제15.1장)."""
    project = require_project(session, project_id, "MEMBER")

    settings = get_settings()
    filename = _safe_filename(file.filename or "unnamed")
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
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
