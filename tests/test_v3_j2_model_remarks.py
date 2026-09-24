"""추가지시 J2: AI 판별 모델이 찾은 날짜·금액·기간·수치 모순을 'AI 작성 참고 신호'로 격하하지 않는다.

모델 지적을 분리해 결정론 엔진의 재계산 결과와 맞춰 보고, 재계산으로 확인되면 그 판정(CONTRADICTED)에 근거로 붙인다.
확인되지 않으면 사람 확인이 필요한 별도 항목으로 남긴다.
"""
from __future__ import annotations

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Block, Finding, NormalizedDocument, Page
from packages.verification_engine.ai_document_detector import (
    AIDetectorResult,
    create_ai_detector_findings,
    reconcile_model_fact_remarks,
)


def _doc():
    page = Page(page_number=1, blocks=[Block(block_id="b0", text="본문", page=1)])
    return NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0", pages=[page])


def _result(reasons):
    return AIDetectorResult(score=0.55, verdict="AI_PARTIAL_GENERATION", reasons=reasons, used_llm=True,
                            signals={"llm_agreement": "SINGLE"})


REASONS = ["[anthropic] 입원기간 일수 오류: 2025. 3. 2.~3. 13.은 12일인데 21일로 기재",
           "[anthropic] 손해액 합계 33,000,000원이 세부 합계 26,350,000원과 다름",
           "[anthropic] 진술서 작성일 2026. 10. 15.이 서면 작성일보다 늦음",
           "[anthropic] 문장 구조가 기계적으로 반복됨"]


def test_fact_remarks_are_separated_from_the_authorship_finding():
    findings = create_ai_detector_findings(_doc(), _result(REASONS))
    authorship = [f for f in findings if f.type == FindingType.AI_AUTHORSHIP_LIKELY]
    remarks = [f for f in findings if f.type == FindingType.MODEL_FACT_REMARK]
    assert authorship and all("일수" not in f.detail and "합계" not in f.detail for f in authorship)
    assert {r.confidence_features["category"] for r in remarks} == {"PERIOD", "ARITHMETIC", "EVIDENCE_DATE"}
    assert all(str(r.status) == "UNVERIFIED" for r in remarks)


def _deterministic(rule, kind=FindingType.ARITHMETIC_MISMATCH):
    return Finding.create(type=kind, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
                          evidence_grade=EvidenceGrade.A, title="재계산 결과", detail="",
                          confidence_features={"rule_id": rule}, document_id="d")


def test_confirmed_remarks_are_folded_into_the_deterministic_verdict():
    findings = create_ai_detector_findings(_doc(), _result(REASONS)) + [
        _deterministic("CALC.DATE_RANGE_DAYS"), _deterministic("CALC.SUM"),
        _deterministic("EVI.EVIDENCE_TIMELINE_INVERSION", FindingType.EVIDENCE_TIMELINE_INVERSION)]
    out = reconcile_model_fact_remarks(findings)
    assert not [f for f in out if f.type == FindingType.MODEL_FACT_REMARK]
    confirmed = [f for f in out if f.confidence_features.get("model_remarks")]
    assert len(confirmed) == 3 and all(str(f.status) == "CONTRADICTED" for f in confirmed)


def test_unconfirmed_remark_stays_for_human_review():
    out = reconcile_model_fact_remarks(create_ai_detector_findings(_doc(), _result(REASONS[:1])))
    [remark] = [f for f in out if f.type == FindingType.MODEL_FACT_REMARK]
    assert "재계산으로 확인하지 못" in remark.detail
