"""템플릿 잔재 탐지 (제7-A.2장 공통 항목).

프로젝트 기본정보와 다른 사건번호·당사자명·법원명이 문서에 남아 있는지 확인한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "forensic_engine.template"

CASE_NO_RE = re.compile(r"\d{4}\s*[가-힣]{1,3}\s*\d{1,6}")
COURT_RE = re.compile(r"([가-힣]{2,10}(?:지방|고등|가정|행정|회생|특허|군사)?법원(?:\s*[가-힣]{2,6}지원)?|대법원|헌법재판소)")


def _canon(text: str) -> str:
    return re.sub(r"\s+", "", text)


def scan_template_residue(
    doc: NormalizedDocument,
    *,
    project_case_number: Optional[str] = None,
    project_court: Optional[str] = None,
    project_parties: Optional[List[str]] = None,
) -> List[Finding]:
    out: List[Finding] = []
    text = doc.full_text
    if not text.strip():
        return out

    found_cases = {_canon(m) for m in CASE_NO_RE.findall(text)}
    found_courts = {_canon(m) for m in COURT_RE.findall(text)}

    if project_case_number:
        target = _canon(project_case_number)
        foreign = sorted(c for c in found_cases if c != target)
        if foreign:
            features = {"deterministic_rule": True, "forensic_signal": len(foreign)}
            out.append(
                Finding.create(
                    type=FindingType.TEMPLATE_RESIDUE,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.A,
                    title=f"프로젝트 사건번호와 다른 사건번호 {len(foreign)}건이 문서에 있다",
                    detail=(
                        f"프로젝트 사건번호는 {project_case_number}이나 문서에는 {', '.join(foreign[:5])} 등이 나타난다. "
                        "인용된 판례 사건번호일 수 있으므로 위치를 확인해야 한다."
                    ),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM2_RESIDUAL,
                    forensic_level=ForensicLevel.NOTABLE,
                    tags=["MM-2", "TEMPLATE"],
                    evidence=[
                        Evidence.create(
                            description="문서에서 관찰된 타 사건번호",
                            grade=EvidenceGrade.A,
                            document_id=doc.document_id,
                            excerpt=", ".join(foreign[:10]),
                        )
                    ],
                )
            )

    if project_court:
        target = _canon(project_court)
        foreign_courts = sorted(c for c in found_courts if c != target and c not in ("대법원", "헌법재판소"))
        if foreign_courts:
            features = {"deterministic_rule": True, "forensic_signal": len(foreign_courts)}
            out.append(
                Finding.create(
                    type=FindingType.TEMPLATE_RESIDUE,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=Severity.LOW,
                    evidence_grade=EvidenceGrade.A,
                    title=f"프로젝트 법원과 다른 법원명 {len(foreign_courts)}건이 있다",
                    detail=f"프로젝트 법원은 {project_court}이나 {', '.join(foreign_courts[:5])} 등이 함께 나타난다.",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM2_RESIDUAL,
                    forensic_level=ForensicLevel.NOTABLE,
                    tags=["MM-2", "TEMPLATE"],
                )
            )

    # 문서요약정보의 title/subject가 본문 사건과 다른 경우
    meta_title = str(doc.metadata.get("title") or doc.metadata.get("Title") or "")
    if meta_title and project_case_number and _canon(project_case_number) not in _canon(meta_title):
        other = CASE_NO_RE.findall(meta_title)
        if other:
            features = {"deterministic_rule": True, "forensic_signal": 1}
            out.append(
                Finding.create(
                    type=FindingType.TEMPLATE_RESIDUE,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.A,
                    title="문서 제목 메타데이터에 타 사건번호가 남아 있다",
                    detail=f"제목 메타데이터: {meta_title[:200]}. 타 사건 서면을 재사용한 흔적일 수 있다.",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM2_RESIDUAL,
                    forensic_level=ForensicLevel.NOTABLE,
                    tags=["MM-2", "TEMPLATE"],
                )
            )
    return out
