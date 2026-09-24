"""finding 정리: 인용마다 최종 판정 하나, 모든 finding에 필수 필드(v2 Phase 1).

한 인용에서 여러 엔진이 각각 finding을 내면(예: 조회 범위 내 미발견 + 그 판례에 기댄 법률 주장 + 인용문
불일치) 보고서에 같은 인용이 서로 다른 경고처럼 여러 번 나온다. 인용마다 가장 강한 판정 하나를 최종
판정으로 남기고, 나머지는 그 최종 finding의 근거(하위 판정)로 합친다.

판정 우선순위: 형식상 성립 불가(A) > 원문과 불일치(A) > 불일치 > 조회 범위 내 미발견 > 미확인 > 그 밖
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from packages.common.enums import EvidenceGrade, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument


def verdict_rank(finding: Finding) -> tuple:
    features = finding.confidence_features or {}
    status = finding.status
    grade = finding.evidence_grade
    if features.get("number_format_valid") is False or features.get("format_violation") \
            or features.get("absence_scope") == "FORMAT_ONLY":
        base = 6
    elif status == VerificationStatus.CONTRADICTED and grade == EvidenceGrade.A:
        base = 5
    elif status == VerificationStatus.CONTRADICTED:
        base = 4
    elif status == VerificationStatus.NOT_FOUND:
        base = 3
    elif status in (VerificationStatus.UNVERIFIED, VerificationStatus.SUSPICIOUS):
        base = 2
    else:
        base = 1
    grade_order = {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(getattr(grade, "value", grade)), 0)
    return base, grade_order


def consolidate_citation_findings(findings: List[Finding]) -> List[Finding]:
    """인용 식별자가 같은 판정 finding을 하나로 합친다. 참고용(advisory) finding은 건드리지 않는다."""
    groups: Dict[str, List[Finding]] = {}
    for finding in findings:
        citation_id = (finding.confidence_features or {}).get("citation_id")
        if citation_id and not finding.advisory_only:
            groups.setdefault(citation_id, []).append(finding)
    dropped = set()
    for citation_id, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=verdict_rank, reverse=True)
        final, rest = members[0], members[1:]
        merged = final.confidence_features.setdefault("merged_findings", [])
        for other in rest:
            merged.append({"finding_id": other.finding_id, "type": str(other.type), "status": str(other.status),
                           "grade": str(getattr(other.evidence_grade, "value", other.evidence_grade)),
                           "title": other.title, "engine": other.engine})
            final.evidence.append(Evidence.create(
                description=f"같은 인용의 하위 판정: {other.type} — {other.title}"[:300],
                grade=other.evidence_grade, document_id=other.document_id, page=other.page,
                excerpt=(other.detail or "")[:300], supports=True))
            for tag in other.tags or []:
                if tag not in final.tags:
                    final.tags.append(tag)
            dropped.add(other.finding_id)
        final.confidence_features["final_verdict"] = True
    return [f for f in findings if f.finding_id not in dropped]


def fill_required_fields(findings: List[Finding], doc: Optional[NormalizedDocument], document_id: str) -> None:
    """document_id·page·bbox·rule_id를 채운다. 블록을 알면 그 블록의 쪽·좌표를 쓴다."""
    blocks = {b.block_id: b for b in doc.blocks} if doc is not None else {}
    for finding in findings:
        if not finding.document_id:
            finding.document_id = document_id
        block = blocks.get(finding.block_id) if finding.block_id else None
        if block is not None:
            if finding.page is None:
                finding.page = block.page
            if finding.bbox is None and block.bbox is not None:
                finding.bbox = block.bbox
        features = finding.confidence_features
        if features is None:
            finding.confidence_features = features = {}
        features.setdefault("rule_id", f"{finding.engine or 'engine'}:{finding.type}")


def finalize_document_findings(findings: List[Finding], doc: Optional[NormalizedDocument],
                               document_id: str) -> List[Finding]:
    out = consolidate_citation_findings(findings)
    fill_required_fields(out, doc, document_id)
    return out
