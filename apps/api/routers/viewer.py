"""Document Viewer 지원 엔드포인트 (제19.2장) 및 Outbound Guard(제7-A.7장)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType
from packages.common.storage import get_storage, sha256_bytes
from packages.document_engine import parse_document
from packages.forensic_engine import ForensicContext, ForensicEngine, inspect_outbound, sanitize

from ..auth import accessible_document, current_user, editable_document
from ..db import User, Document, DocumentBlock, DocumentPage, DocumentVersion, Project, VerificationRun, get_db
from ..identity import actor_id, filter_project_query, require_project
from ..schemas import OutboundRequest
from ..services import make_audit

router = APIRouter(tags=["viewer"])


def _authorized_document(session: Session, document_id: str, minimum: str = "VIEWER") -> Document:
    query = filter_project_query(
        select(Document).where(Document.id == document_id), session, Document.project_id)
    document = session.scalar(query)
    if document is None:
        raise HTTPException(404, "Document not found")
    require_project(session, document.project_id, minimum)
    return document


@router.get("/documents/{document_id}/blocks")
def get_blocks(
    document_id: str,
    page: Optional[int] = None,
    include_hidden: bool = Query(default=False, description="보호된 레이어는 별도 열람 승인 필요"),
    run_id: Optional[str] = None,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    document = _authorized_document(session, document_id)
    accessible_document(session, user, document_id)
    if include_hidden:
        raise HTTPException(403, "보호된 내용은 확인 항목의 개별 열람 절차를 이용해야 합니다")
    if run_id:
        run = session.scalar(select(VerificationRun).where(
            VerificationRun.id == run_id, VerificationRun.project_id == document.project_id))
        if run is None:
            raise HTTPException(404, "검증 결과를 찾을 수 없습니다")
        entry = next((d for d in (run.result_json or {}).get("documents", [])
                      if d.get("document_id") == document_id), None)
        if entry and "pages" in entry:
            pages = entry["pages"]
            return {"document_id": document_id, "filename": document.filename,
                    "pages": [{k: v for k, v in p.items() if k != "blocks"} for p in pages],
                    "blocks": [b for p in pages if page is None or p["page_number"] == page
                               for b in p.get("blocks", []) if b.get("visible") is True
                               and b.get("source_layer") in ("visible_text", "ocr_layer")]}
    query = select(DocumentBlock).where(
        DocumentBlock.document_id == document.id, DocumentBlock.visible.is_(True),
        DocumentBlock.source_layer.in_(("visible_text", "ocr_layer")))
    if page is not None:
        query = query.where(DocumentBlock.page == page)
    blocks = session.execute(query).scalars().all()
    pages = session.execute(
        select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.page_number)
    ).scalars().all()
    return {
        "document_id": document_id,
        "filename": document.filename,
        "quarantined": bool(document.quarantined),
        "pages": [
            {"page_number": p.page_number, "width": p.width, "height": p.height, "attributes": p.attributes}
            for p in pages
        ],
        "blocks": [
            {
                "block_id": b.id,
                "page": b.page,
                "text": b.text,
                "bbox": b.bbox,
                "source_layer": b.source_layer,
                "block_type": b.block_type,
                "visible": b.visible,
                "attributes": b.attributes,
            }
            for b in blocks
        ],
    }


@router.get("/documents/{document_id}/original")
def get_original(document_id: str, session: Session = Depends(get_db),
                 user: User = Depends(current_user)) -> Response:
    document = _authorized_document(session, document_id)
    accessible_document(session, user, document_id)
    data = get_storage().get(document.storage_key)
    make_audit(session).record(
        AuditEventType.EXPORT, {"action": "ORIGINAL_DOWNLOAD", "sha256": document.sha256},
        actor=actor_id(), project_id=document.project_id, document_id=document.id)
    return Response(
        content=data,
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}",
                 "Cache-Control": "no-store"},
    )


@router.get("/documents/{document_id}/pages/{page_number}.png")
def render_page(document_id: str, page_number: int, session: Session = Depends(get_db)):
    document = _authorized_document(session, document_id)
    if not document.filename.lower().endswith(".pdf"):
        raise HTTPException(404, "PDF 문서를 찾을 수 없습니다")
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(get_storage().get(document.storage_key))
    try:
        if not 1 <= page_number <= len(pdf):
            raise HTTPException(404, "페이지를 찾을 수 없습니다")
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            bitmap = page.render(scale=min(1.5, 2000 / max(width, height)))
            try:
                image = bitmap.to_pil()
                output = BytesIO()
                image.save(output, format="PNG")
                image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()
    make_audit(session).record(
        AuditEventType.EXPORT, {"action": "PAGE_RENDER", "page_number": page_number},
        actor=actor_id(), project_id=document.project_id, document_id=document.id)
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/documents/{document_id}/versions")
def list_versions(document_id: str, session: Session = Depends(get_db),
                 user: User = Depends(current_user)) -> List[Dict[str, Any]]:
    document = _authorized_document(session, document_id)
    accessible_document(session, user, document_id)
    versions = session.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version)
    ).scalars().all()
    return [
        {
            "id": v.id,
            "version": v.version,
            "kind": v.kind,
            "sha256": v.sha256,
            "note": v.note,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.post("/documents/{document_id}/outbound-guard")
def outbound_guard(document_id: str, payload: OutboundRequest,
                   session: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> Dict[str, Any]:
    """발신 전 자체검사. 원본은 보존하고 정제본을 새 버전으로 등록한다(제7-A.7장)."""
    document = _authorized_document(session, document_id, "MEMBER")
    document = editable_document(session, user, document_id)

    storage = get_storage()
    path = str(storage.path(document.storage_key))
    normalized = parse_document(
        path,
        document_id=document.id,
        filename=document.filename,
        mime_type=document.mime_type or "",
        sha256=document.sha256,
    )
    project = session.get(Project, document.project_id)
    forensic = ForensicEngine().scan(
        normalized,
        ForensicContext(
            project_case_number=project.case_number if project else None,
            project_court=project.court if project else None,
            counterparty_document=False,  # 자기 측 문서 모드
            source_path=path,
        ),
    )
    report = inspect_outbound(normalized, forensic.findings)

    result: Dict[str, Any] = {
        "document_id": document_id,
        "risk_items": report.risk_items,
        "manual_actions": report.manual_actions,
        "finding_count": len(forensic.findings),
    }

    if payload.generate_sanitized and report.risk_items:
        suffix = "." + document.filename.rsplit(".", 1)[-1].lower() if "." in document.filename else ""
        temp_path = storage.path(document.storage_key).parent / f"sanitized_{document.sha256[:12]}{suffix}"
        sanitized = sanitize(normalized, path, str(temp_path))
        data = temp_path.read_bytes()
        digest = sha256_bytes(data)
        key = storage.put_derivative(f"{document.project_id}/{document.id}/sanitized{suffix}", data)
        temp_path.unlink(missing_ok=True)

        next_version = (
            session.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id)
            ).scalars().all()
        )
        session.add(
            DocumentVersion(
                document_id=document.id,
                version=len(next_version) + 1,
                sha256=digest,
                storage_key=key,
                kind="SANITIZED",
                note=f"Outbound Guard 정제본. 제거 내역: {sanitized.removed}",
            )
        )
        session.commit()
        result["sanitized"] = {
            "storage_key": key,
            "sha256": digest,
            "removed": sanitized.removed,
            "manual_actions": sanitized.manual_actions,
            "notice": "원본은 Immutable Original로 그대로 보존된다.",
        }
        result["manual_actions"].extend(sanitized.manual_actions)

        make_audit(session).record(
            AuditEventType.EXPORT,
            {"document_id": document.id, "action": "OUTBOUND_SANITIZE", "removed": sanitized.removed,
             "sanitized_sha256": digest},
            project_id=document.project_id,
            document_id=document.id,
            actor=actor_id(),
        )
    return result
