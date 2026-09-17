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
    FindingType.SPECIMEN_DOCUMENT_DECLARED,
    FindingType.INVALID_IDENTIFIER,
    FindingType.PLACEHOLDER_IDENTIFIER,
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

    # 본문을 읽지 못한 문서. 내용 기반 축은 "위험 없음"이 아니라 "판정 불가"이다.
    # 이 구분이 없으면, 검증해서 깨끗한 문서와 아무것도 못 읽은 문서가 같은 보고서를 낳는다.
    unreadable = [
        item.get("document_id")
        for item in result.unverified_items
        if item.get("kind") in ("document", "document_body")
    ]
    analyzed_documents = [d for d in result.documents if d.document_id not in unreadable]
    nothing_analyzed = bool(result.documents) and not analyzed_documents

    def content_risk(items: List[Finding]) -> str:
        """내용 기반 축의 위험도. 읽은 문서가 하나도 없으면 NONE을 쓰지 않는다."""
        risk = _risk_from(items)
        if risk == "NONE" and nothing_analyzed:
            return "UNVERIFIED"
        return risk

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
                "risk": content_risk(legal),
            },
            "factual_reliability": {"issue_count": len(consistency), "risk": content_risk(consistency)},
            "internal_consistency": {
                "cross_document_issues": sum(
                    1 for f in findings if f.type == FindingType.CROSS_DOCUMENT_CONTRADICTION
                ),
                "timeline_issues": sum(1 for f in findings if f.type == FindingType.TIMELINE_CONTRADICTION),
                "arithmetic_issues": sum(1 for f in findings if f.type == FindingType.ARITHMETIC_MISMATCH),
            },
            "authenticity_risk": {"issue_count": len(authenticity), "risk": content_risk(authenticity)},
            "forgery_risk": {
                "issue_count": len(forgery),
                "risk": _risk_from(forgery),
                "note": "포렌식 휴리스틱만으로 위조를 단정하지 않는다.",
            },
            "adversarial_manipulation_risk": {
                "issue_count": len(adversarial),
                "risk": content_risk(adversarial),
            },
            "unverified_ratio": {
                "unverified_items": len(result.unverified_items),
                "unavailable_sources": [s["name"] for s in result.unavailable_sources],
                "ratio": round(len(result.unverified_items) / citation_total, 3) if citation_total else None,
                "unreadable_documents": [d for d in unreadable if d],
                "analyzed_documents": len(analyzed_documents),
                "total_documents": len(result.documents),
            },
        },
        "quarantined_documents": [d.document_id for d in result.documents if d.quarantined],
        "note": (
            "축별 위험도를 하나의 종합점수로 합산하지 않는다(제20.1장). "
            + (
                "본문을 읽지 못해 내용 검증을 수행하지 못했다. 내용 기반 축의 UNVERIFIED는 "
                "'이상 없음'이 아니라 '확인하지 못함'이다."
                if nothing_analyzed
                else ""
            )
        ).strip(),
    }
