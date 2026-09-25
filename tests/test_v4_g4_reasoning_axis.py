"""G4 보강: 제소기간 예외 규칙의 부정 표현 처리와 법리 검토 결과의 요약 점수 반영."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Finding
from packages.legal_engine.legal_rules import review_legal_rules
from packages.verification_engine.scoring import aggregate_scores
from tests.test_v3_g4_claims import _doc


def deadline(text):
    return [f for f in review_legal_rules(_doc(text)) if f.confidence_features.get("rule_id") == "ADMIN.DEADLINE_EXCEPTION"]


@pytest.mark.parametrize("text", [
    "무효확인소송이 아닌 이 취소소송에는 제소기간 제한이 적용되지 않는다.",
    "원고는 무효등확인이 아니라 취소를 구하므로 제소기간은 무관하다.",
    "이 사건 영업정지처분 취소소송은 제소기간의 제한을 받지 않는다.",
])
def test_deadline_exception_claim_is_flagged_even_when_nullity_is_mentioned_negatively(text):
    assert deadline(text)


@pytest.mark.parametrize("text", [
    "무효확인소송에는 제소기간이 적용되지 않는다(행정소송법 제38조 제1항).",
    "이 사건은 무효확인의 소이므로 제소기간 제한을 받지 않는다.",
    "원고에게 정당한 사유가 있으므로 제소기간이 적용되지 않는다.",
])
def test_nullity_suit_and_justified_reason_are_not_flagged(text):
    assert not deadline(text)


def _finding(finding_type, doc_id, **features):
    return Finding.create(type=finding_type, status=VerificationStatus.SUSPICIOUS, severity=Severity.MEDIUM,
                          evidence_grade=EvidenceGrade.B, title="t", detail="d", document_id=doc_id,
                          confidence_features=features)


def _result(findings):
    document = SimpleNamespace(document_id="d1", citations=[], claims=[], engine_data={}, findings=findings,
                               authorship=None, ai_detector_result=None, quarantined=False)
    return SimpleNamespace(all_findings=findings, documents=[document], unverified_items=[], unavailable_sources=[],
                           project_findings=[])


@pytest.mark.parametrize("finding_type", [FindingType.UNSUPPORTED_GENERALIZATION,   # 민사 전칭 일반화
                                          FindingType.LEGAL_ARGUMENT_INVALID,       # 행정 제소기간 예외
                                          FindingType.OVERCLAIM])                   # 형사 과장 주장
def test_reasoning_findings_change_the_legal_axis(finding_type):
    axes = aggregate_scores(_result([_finding(finding_type, "d1")]))["axes"]["legal_citation_accuracy"]
    assert axes["reasoning_issues"] == 1 and axes["reasoning_by_type"] == {str(finding_type): 1}


def test_ai_response_residue_is_counted_in_the_authorship_axis():
    residue = _finding(FindingType.DRAFT_ARTIFACT, "d1", defect_code="AI_RESPONSE_RESIDUE", residue_category="SOURCE_TOKEN")
    axis = aggregate_scores(_result([residue]))["axes"]["ai_authorship"]["response_residue"]
    assert axis == {"count": 1, "categories": ["SOURCE_TOKEN"], "documents": ["d1"]}
