"""제20.1장 결과 집계.

모든 점수를 하나로 합치지 않고 축별로 분리해 제시한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from packages.common.schemas import Finding
from packages.common.enums import (
    ADVERSARIAL_FINDING_TYPES,
    LEGAL_FINDING_TYPES,
    MM4_ADVISORY_TYPES,
    FindingType,
    MetaMessageType,
    Severity,
    VerificationStatus,
)

from .gate import evaluate_gate

RISK_ORDER = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

FORGERY_TYPES = {
    FindingType.MODIFIED_AFTER_SIGNATURE,
    FindingType.SIGNATURE_INVALID,
    FindingType.PAGE_STRUCTURE_OUTLIER,
    FindingType.METADATA_ANOMALY,
    FindingType.PRIOR_VERSION_RECOVERABLE,
    FindingType.CROPPED_IMAGE_RESIDUE,
}
# 사실 주장의 근거(첨부·증거·해시)와 관련된 관찰. 허위 판정이 아니라 '검증되지 않은 사실'의 근거다.
EVIDENCE_TYPES = {
    FindingType.FACT_UNSUPPORTED,
    FindingType.EVIDENCE_NOT_PROVIDED,
    FindingType.EVIDENCE_REFERENCE_MISSING,
    FindingType.HASH_FORMAT_INVALID,
    FindingType.HASH_MISMATCH,
    FindingType.EVIDENCE_DATE_INVALID,
    FindingType.EVIDENCE_NUMBERING_GAP,
    FindingType.EVIDENCE_LIST_MISMATCH,
    FindingType.EVIDENCE_FORM_DEFECT,
    FindingType.EVIDENCE_PURPOSE_MISMATCH,
    FindingType.STATEMENT_BEYOND_PERCEPTION,
}
CONSISTENCY_TYPES = {
    FindingType.FACT_CONTRADICTION,
    FindingType.CROSS_DOCUMENT_CONTRADICTION,
    FindingType.TIMELINE_CONTRADICTION,
    FindingType.ARITHMETIC_MISMATCH,
    FindingType.EVIDENCE_TIMELINE_INVERSION,
    FindingType.EVIDENCE_PERSON_INCONSISTENT,
    FindingType.CROSS_DOC_COPY,
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


def unified_authorship(document: Any) -> Dict[str, Any]:
    """문서 하나의 AI 작성 판단. 교차판정 결과를 우선하고 문체 통계는 보조 신호로 붙인다."""
    detector = document.ai_detector_result or {}
    stylometry = (document.authorship or {}).get("verdict")
    verdict = detector.get("verdict") or stylometry or "UNCERTAIN"
    return {"document_id": document.document_id, "verdict": verdict,
            "basis": "AI_DETECTOR" if detector.get("verdict") else "STYLOMETRY",
            "score": detector.get("score"), "stylometry_signal": stylometry}


def _sum_components(documents: List[Any]) -> Dict[str, int]:
    total: Dict[str, int] = {}
    for document in documents:
        summary = (document.engine_data.get("legal") or {}).get("component_summary") or {}
        for key, value in summary.items():
            total[key] = total.get(key, 0) + int(value or 0)
    return total


def _factual_axis(documents: List[Any], consistency: List[Any], evidence: List[Any], content_risk) -> Dict[str, Any]:
    """사실 신뢰성 축. '이슈 0건'이 '검사해서 이상 없음'인지 '검사할 수 없었음'인지 구분한다."""
    claims = [c for d in documents for c in (d.claims or [])]
    facts = [c for c in claims if str(c.get("type")) == "FACT"]
    relations = [(c.get("attributes") or {}).get("evidence_relationship") for c in facts]
    not_provided = sum(r in ("EVIDENCE_NOT_PROVIDED", "REFERENCE_MISSING") for r in relations)
    attached = sum(r == "ATTACHED_NOT_ASSESSED" for r in relations)
    issues = consistency + evidence
    if not facts:
        coverage = "NOT_ASSESSED"          # 사실 주장을 찾지 못했다. '이상 없음'이 아니다.
    elif issues:
        coverage = "ISSUES_FOUND"
    elif attached or any(d.engine_data.get("attachments", {}).get("items") for d in documents):
        coverage = "NO_ISSUES_IN_SCOPE"    # 검사한 범위 안에서는 이상이 없었다
    else:
        coverage = "INSUFFICIENT"          # 사실 주장은 있으나 대조할 근거 자료가 없었다
    return {
        "issue_count": len(issues),
        "contradiction_issues": len(consistency),
        "evidence_issues": len(evidence),
        "fact_claims": len(facts),
        "facts_without_provided_evidence": not_provided,
        "facts_with_attached_evidence": attached,
        "coverage": coverage,
        "risk": content_risk(issues) if coverage != "INSUFFICIENT" else "UNVERIFIED",
        "note": "근거 자료가 없는 사실은 '검증되지 않은 사실'이며 허위·위조 판정이 아니다.",
    }


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
        1 for item in result.unverified_items
        if item.get("kind") == "citation" and item.get("scope") != "PARTIAL"
    )
    verified_citations = sum(
        int((d.engine_data.get("legal") or {}).get("verified_count", 0)) for d in result.documents
    )

    # AI 작성 판단은 문서마다 하나로 낸다(v2 R10). 규칙·모델 교차판정(ai_detector_result)이 있으면 그것이
    # 판정이고, 문체 통계(authorship)는 보조 신호로만 붙인다. 두 값을 따로 내보내면 축은 '판단 보류'인데
    # 문서 결과는 'AI 작성 유력'처럼 서로 모순되게 읽힌다.
    authorship_verdicts = [unified_authorship(d) for d in result.documents if d.authorship or d.ai_detector_result]

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

    # 제8~9장. 축별 위험도와 별도로 배포 가능 여부를 하나의 판정으로 낸다.
    # 읽지 못한 문서가 있으면 PASS를 주지 않는다.
    gate = evaluate_gate(
        findings,
        unverified_items=result.unverified_items,
        nothing_analyzed=nothing_analyzed,
        intended_external_submission=bool(
            getattr(result, "intended_external_submission", False)
        ),
    )

    return {
        "release_gate": gate.to_dict(),
        "severity_counts": severity_counts,
        "status_counts": status_counts,
        "finding_total": len(findings),
        "advisory_total": len(advisory),
        "axes": {
            "ai_authorship": {
                "verdicts": [v["verdict"] for v in authorship_verdicts],
                "documents": authorship_verdicts,
                "note": "확정판정이 아니며 사용자 판단이 필요하다. 문서별 판정은 규칙·모델 교차판정 하나로 내고 "
                        "문체 통계는 보조 신호로만 표시한다.",
            },
            "legal_citation_accuracy": {
                "citation_total": citation_total,
                # 사건 적용을 뺀 모든 단계가 확인된 인용 수. 기준일이 없으면 0이 되는 값이다.
                "verified": verified_citations,
                "unverified": unverified_citations,
                # 단계별 집계. 인용 대상(법령·조문, 판례)을 공식 원문으로 확인한 수와
                # 시간적 적용만 남은 수를 따로 센다. '확인 0건'이 '아무것도 못 찾음'으로
                # 읽히지 않게 한다.
                "components": _sum_components(result.documents),
                # 인용 대상과 문서가 주장한 내용까지 공식 원문으로 확인한 수(기준일 확인은 별도).
                "content_confirmed": _sum_components(result.documents).get("content_confirmed", 0),
                "issue_count": len(legal),
                "risk": content_risk(legal),
                "note": "verified는 사건 적용을 뺀 모든 단계가 확인된 인용 수이고, "
                        "components.identity_confirmed는 인용 대상 자체를 공식 원문으로 확인한 수다.",
            },
            "factual_reliability": _factual_axis(result.documents, consistency,
                                                 [f for f in findings if f.type in EVIDENCE_TYPES], content_risk),
            "internal_consistency": {
                "cross_document_issues": sum(
                    1 for f in findings if f.type in (FindingType.CROSS_DOCUMENT_CONTRADICTION,
                                                      FindingType.CROSS_DOC_COPY,
                                                      FindingType.EVIDENCE_PERSON_INCONSISTENT)
                ),
                "timeline_issues": sum(1 for f in findings if f.type in (FindingType.TIMELINE_CONTRADICTION,
                                                                         FindingType.EVIDENCE_TIMELINE_INVERSION)),
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
                # 이번 실행의 검증에 실제로 영향을 준 출처만 따로 적는다.
                "unavailable_sources_affecting": [s["name"] for s in result.unavailable_sources
                                                  if s.get("impact", "AFFECTS_VERIFICATION") != "NOT_NEEDED"],
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
