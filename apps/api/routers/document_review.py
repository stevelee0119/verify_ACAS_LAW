"""Visible-text comparisons and explicit document version lineage."""
import difflib
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import Document, Project, VerificationRun, get_db
from ..workspace import DocumentRelation, as_dict
from .workspace import actor, history, project_or_404, run_or_404

router = APIRouter(tags=["document-review"])


class RelationInput(BaseModel):
    parent_id: str
    child_id: str
    kind: Literal["DRAFT", "REVISION", "FILED", "DERIVATIVE"] = "REVISION"
    note: str = Field(default="", max_length=2000)


@router.get("/projects/{project_id}/document-relations")
def relations(project_id: str, session: Session = Depends(get_db)):
    project_or_404(session, project_id)
    return [as_dict(r) for r in session.scalars(select(DocumentRelation).where(DocumentRelation.project_id == project_id))]


@router.post("/projects/{project_id}/document-relations", status_code=201)
def link_version(project_id: str, payload: RelationInput, request: Request, session: Session = Depends(get_db)):
    # Lock the project before checking edges, including concurrent new relations.
    session.execute(update(Project).where(Project.id == project_id).values(scope_revision=Project.scope_revision))
    ids = {payload.child_id, payload.parent_id}
    docs = session.scalars(select(Document).where(Document.project_id == project_id, Document.id.in_(ids))).all()
    if len(ids) != 2 or len(docs) != 2:
        raise HTTPException(400, "같은 사건의 서로 다른 두 문서를 선택하세요")
    edges = {r.child_id: r.parent_id for r in session.scalars(select(DocumentRelation).where(DocumentRelation.project_id == project_id))}
    if payload.child_id in edges:
        raise HTTPException(409, "이미 이전 버전이 연결된 문서입니다")
    current, visited = payload.parent_id, set()
    while current:
        if current == payload.child_id or current in visited:
            raise HTTPException(409, "문서 버전 관계가 순환할 수 없습니다")
        visited.add(current)
        current = edges.get(current)
    row = DocumentRelation(**payload.model_dump(), project_id=project_id, created_by=actor(request))
    session.add(row)
    session.flush()
    history(session, project_id, "DOCUMENT_RELATION", row.child_id, actor(request), {}, as_dict(row))
    session.commit()
    return as_dict(row)


def snapshot_document(session, project_id, document_id, run_id=None):
    doc = session.get(Document, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(404, "이 프로젝트의 문서가 아닙니다")
    candidates = [run_or_404(session, project_id, run_id)] if run_id else session.scalars(
        select(VerificationRun).where(VerificationRun.project_id == project_id,
        VerificationRun.state.in_(["COMPLETED", "PARTIAL_COMPLETED"])).order_by(VerificationRun.started_at.desc()).limit(100))
    for run in candidates:
        entry = next((d for d in (run.result_json or {}).get("documents", []) if d.get("document_id") == document_id), None)
        if entry:
            return run, entry
    raise HTTPException(409, "본문 비교 전에 해당 자료를 검증해 주세요")


def visible_blocks(entry):
    return [{"page": p["page_number"], "block_id": b.get("block_id"), "text": b.get("text", "")}
            for p in entry.get("pages", []) for b in p.get("blocks", [])
            if b.get("visible", True) and b.get("source_layer", "visible_text") in ("visible_text", "ocr_layer")]


@router.get("/projects/{project_id}/compare")
def compare(project_id: str, left_id: str, right_id: str, left_run: str | None = None,
            right_run: str | None = None, session: Session = Depends(get_db)):
    lhs, left = snapshot_document(session, project_id, left_id, left_run)
    rhs, right = snapshot_document(session, project_id, right_id, right_run)
    a, b = visible_blocks(left), visible_blocks(right)
    if any(len(v) > 2000 or sum(len(x["text"]) for x in v) > 500000 for v in (a, b)):
        raise HTTPException(413, "문서 비교 범위를 초과했습니다. 문서를 나누어 검토하세요")
    if not a or not b:
        raise HTTPException(409, "양쪽 문서에 추출된 본문이 있어야 비교할 수 있습니다")
    changes = []
    matcher = difflib.SequenceMatcher(None, [v["text"] for v in a], [v["text"] for v in b], autojunk=False)
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag != "equal":
            joined = " ".join(v["text"] for v in a[i:j] + b[k:l])
            changes.append({"kind": tag, "before": a[i:j], "after": b[k:l],
                "numeric_change": bool(re.search(r"\d", joined)),
                "citation_change": bool(re.search(r"제\s*\d+\s*조|\d{2,4}[가-힣]{1,3}\d+", joined))})
    return {"left_run_id": lhs.id, "right_run_id": rhs.id, "left_document_id": left_id,
            "right_document_id": right_id, "changes": changes, "unchanged": not changes,
            "notice": "추출된 가시 본문의 차이입니다. 서식·이미지·숨은 내용 및 법적 효력의 동일성을 판단하지 않습니다."}


@router.get("/projects/{project_id}/search")
def search(project_id: str, q: str = Query(min_length=2, max_length=200), run_id: str | None = None,
           session: Session = Depends(get_db)):
    run = run_or_404(session, project_id, run_id)
    included = set(session.scalars(select(Document.id).where(Document.project_id == project_id,
        Document.included_in_verification.is_(True))))
    terms = set(re.findall(r"[\w가-힣]+", q.lower()))
    if not terms:
        raise HTTPException(422, "검색할 단어를 입력하세요")
    result = []
    for doc in (run.result_json or {}).get("documents", []):
        if doc["document_id"] not in included or doc.get("quarantined"):
            continue
        for block in visible_blocks(doc):
            matches = sum(t in block["text"].lower() for t in terms)
            if matches:
                result.append({**block, "text": block["text"][:2000], "document_id": doc["document_id"],
                    "matched_terms": matches, "method": "LEXICAL_TERM_OVERLAP"})
    result.sort(key=lambda r: r["matched_terms"], reverse=True)
    return {"run_id": run.id, "results": result[:50], "notice": "단어 일치 후보이며 법률적 유사성·입증력 판단이 아닙니다."}
