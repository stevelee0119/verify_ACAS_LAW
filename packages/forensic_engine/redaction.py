"""REDACTION_FAILURE 탐지 (제7-A.2장).

시각적으로 가려졌을 뿐 텍스트 레이어가 그대로 남아 있는 상태이며,
개인정보·군사보안 위험이 가장 크므로 CRITICAL로 취급한다.
비식별화 산출물(제8장)에도 동일 검사를 반복 적용한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import BBox, Evidence, Finding, NormalizedDocument

ENGINE_NAME = "forensic_engine.redaction"


def scan_redaction(doc: NormalizedDocument) -> List[Finding]:
    """검은 사각형 아래에 텍스트가 남아 있는지 판정한다."""
    out: List[Finding] = []
    for page in doc.pages:
        rects = page.attributes.get("filled_dark_rects") or []
        if not rects:
            continue
        covered: List[Dict[str, Any]] = []
        for rect in rects:
            rb = BBox(*rect["bbox"])
            if (rb.x1 - rb.x0) < 8 or (rb.y1 - rb.y0) < 4:
                continue
            for block in page.blocks:
                if block.bbox is None or not block.text.strip():
                    continue
                if rb.contains(block.bbox, tolerance=2.0):
                    covered.append(
                        {
                            "block_id": block.block_id,
                            "text": block.text,
                            "rect": rect["bbox"],
                            "bbox": block.bbox.as_tuple(),
                        }
                    )
        if not covered:
            continue
        features = {
            "deterministic_rule": True,
            "cross_layer_mismatch": True,
            "forensic_signal": len(covered),
            "covered_block_count": len(covered),
        }
        out.append(
            Finding.create(
                type=FindingType.REDACTION_FAILURE,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.CRITICAL,
                evidence_grade=EvidenceGrade.A,
                title=f"마스킹 실패: {page.page_number}면에서 가려진 텍스트 {len(covered)}건이 복원 가능하다",
                detail=(
                    "검은 사각형으로 시각적으로만 가려졌을 뿐 텍스트 레이어가 그대로 남아 있다. "
                    "개인정보·보안 위험이 크므로 원본을 재배포하기 전에 실제 삭제가 필요하다."
                ),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                page=page.page_number,
                block_id=covered[0]["block_id"],
                bbox=BBox(*covered[0]["bbox"]),
                engine=ENGINE_NAME,
                meta_message_type=MetaMessageType.MM2_RESIDUAL,
                forensic_level=ForensicLevel.CRITICAL,
                sealed_excerpt="\n".join(c["text"] for c in covered)[:2000],
                tags=["MM-2", "PRIVILEGE_CANDIDATE", "OUTBOUND_RISK"],
                evidence=[
                    Evidence.create(
                        description=f"{page.page_number}면 가림 영역 아래 텍스트",
                        grade=EvidenceGrade.A,
                        document_id=doc.document_id,
                        page=page.page_number,
                        excerpt=covered[0]["text"][:200],
                        sealed=True,
                    )
                ],
            )
        )
    return out
