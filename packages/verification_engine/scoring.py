"""제20.1장 결과 집계.

모든 점수를 하나로 합치지 않고 축별로 분리해 제시한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from packages.common.enums import (
    ADVERSARIAL_FINDING_TYPES,
    LEGAL_FINDING_TYPES,
    MM4_ADVISORY_TYPES,
    FindingType,
    MetaMessageType,
    Severity,
    VerificationStatus,
)

RISK_ORDER = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

FORGERY_TYPES = {
    FindingType.MODIFIED_AFTER_SIGNATURE,
    FindingType.SIGNATURE_INVALID,
    FindingType.PAGE_STRUCTURE_OUTLIER,
    FindingType.METADATA_ANOMALY,
    FindingType.PRIOR_VERSION_RECOVERABLE,
    FindingType.CROPPED_IMAGE_RESIDUE,
}
CONSISTENCY_TYPES = {
    FindingType.FACT_CONTRADICTION,
    FindingType.CROSS_DOCUMENT_CONTRADICTION,
    FindingType.TIMELINE_CONTRADICTION,
    FindingType.ARITHMETIC_MISMATCH,
}
AUTHENTICITY_TYPES = {
    FindingType.REDACTION_FAILURE,
    FindingType.HIDDEN_TEXT_MISMATCH,
    FindingType.OCR_LAYER_MISMATCH,
    FindingType.DELETED_TEXT_RECOVERABLE,
    FindingType.TEMPLATE_RESIDUE,
}


def _risk_from(findings: List[Any]) -> str:
    if any(f.severity == Severity.CRITICAL for f in findings):
        return "CRITICAL"
    if any(f.severity == Severity.HIGH for f in findings):
        return "HIGH"
    if any(f.severity == Severity.MEDIUM for f in findings):
        return "MEDIUM"
    if findings:
        return "LOW"
    return "NONE"


def aggregate_scores(result: Any) -> Dict[str, Any]:
    findings = result.all_findings
    severity_counts = {str(s): sum(1 for f in findings if f.severity == s) for s in Severity}
    status_counts = {str(s): sum(1 for f in findings if f.status == s) for s in VerificationStatus}

    adversarial = [f for f in findings if f.type in ADVERSARIAL_FINDING_TYPES]
    legal = [f for f in findings if f.type in LEGAL_FINDING_TYPES]
    consistency = [f for f in findings if f.type in CONSISTENCY_TYPES]
    authenticity = [f for f in findings if f.type in AUTHENTICITY_TYPES]
    forgery = [f for f in findings if f.type in FORGERY_TYPES]
    advisory = [f for f in findings if f.type in MM4_ADVISORY_TYPES or f.advisory_only]

    citation_total = sum(len(d.citations) for d in result.documents)
    unverified_citations = sum(
        1 for item in result.unverified_items if item.get("kind") == "citation"
    )
    verified_citations = sum(
        int((d.engine_data.get("legal") or {}).get("verified_count", 0)) for d in result.documents
    )

    authorship_verdicts = [d.authorship.get("verdict") for d in result.documents if d.authorship]

    return {
        "severity_counts": severity_counts,
        "status_counts": status_counts,
        "finding_total": len(findings),
        "advisory_total": len(advisory),
        "axes": {
            "ai_authorship": {
                "verdicts": authorship_verdicts,
                "note": "확정판정이 아니며 사용자 판단이 필요하다.",
            },
            "legal_citation_accuracy": {
                "citation_total": citation_total,
                "verified": verified_citations,
                "unverified": unverified_citations,
                "issue_count": len(legal),
                "risk": _risk_from(legal),
            },
            "factual_reliability": {"issue_count": len(consistency), "risk": _risk_from(consistency)},
            "internal_consistency": {
                "cross_document_issues": sum(
                    1 for f in findings if f.type == FindingType.CROSS_DOCUMENT_CONTRADICTION
                ),
                "timeline_issues": sum(1 for f in findings if f.type == FindingType.TIMELINE_CONTRADICTION),
                "arithmetic_issues": sum(1 for f in findings if f.type == FindingType.ARITHMETIC_MISMATCH),
            },
            "authenticity_risk": {"issue_count": len(authenticity), "risk": _risk_from(authenticity)},
            "forgery_risk": {
                "issue_count": len(forgery),
                "risk": _risk_from(forgery),
                "note": "포렌식 휴리스틱만으로 위조를 단정하지 않는다.",
            },
            "adversarial_manipulation_risk": {
                "issue_count": len(adversarial),
                "risk": _risk_from(adversarial),
            },
            "unverified_ratio": {
                "unverified_items": len(result.unverified_items),
                "unavailable_sources": [s["name"] for s in result.unavailable_sources],
                "ratio": round(len(result.unverified_items) / citation_total, 3) if citation_total else None,
            },
        },
        "quarantined_documents": [d.document_id for d in result.documents if d.quarantined],
        "note": "축별 위험도를 하나의 종합점수로 합산하지 않는다(제20.1장).",
    }
