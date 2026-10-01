"""TK-09: 모델 의견 후보 제안 및 결정적 검증기 승격 단위 시험.

규칙:
- 특정 사건 고유 리터럴(당사자명, 사건번호, 금액, 특정 서면 문구)을 하드코딩하지 않는다.
- 양성 예시 4건, 대조군 5건으로 구성하여 합성된 텍스트로 철저히 검증한다.
- 한국어 주석 포함.
"""
from __future__ import annotations

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Block, Finding, NormalizedDocument, Page
from packages.verification_engine.ai_document_detector import (
    _fact_category,
    _fact_remark_finding,
    reconcile_model_fact_remarks,
)
from packages.verification_engine.candidate_verifier import (
    ModelCandidate,
    verify_model_fact_recalculation,
    verify_rag_candidate,
)


def _make_doc(text: str, doc_id: str = "doc_test") -> NormalizedDocument:
    """합성 테스트용 NormalizedDocument 생성."""
    page = Page(page_number=1, blocks=[Block(block_id="b0", text=text, page=1)])
    return NormalizedDocument(
        document_id=doc_id, filename="test.pdf", mime_type="application/pdf", sha256="test", pages=[page]
    )


# ==============================================================================
# 양성 시험군 (Positive Controls, 4건)
# ==============================================================================


def test_positive_rag_candidate_grounded_contradiction():
    """양성 1: RAG 모순 후보의 서면 주장과 참고자료 규정이 모두 원문과 일치하면 정식 Finding(SUSPICIOUS, B등급)으로 승격."""
    doc_text = "원고는 피고의 지시를 성실히 이행하였으므로 계약상 납품 기한을 도과하지 않았다고 주장합니다."
    sources = [
        {
            "source_id": "R01",
            "title": "물품구매계약특수조건",
            "text": "제12조 제1항: 계약상대자가 납품 기한을 도과한 경우 매 1일당 지체상금을 부과한다.",
        }
    ]
    candidate = ModelCandidate(
        candidate_id="c_01",
        claim_quote="납품 기한을 도과하지 않았다고 주장",
        defect_type="FACT_CONTRADICTION",
        basis_quote="납품 기한을 도과한 경우 매 1일당 지체상금을 부과한다",
        source_id="R01",
        explanation="서면은 기한 미도과를 주장하나 계약 규정상 지체상금 부과 대상입니다.",
        model_name="anthropic",
    )
    finding, rejected = verify_rag_candidate(candidate, doc_text, sources, document_id="doc_test")

    assert rejected is None
    assert finding is not None
    assert finding.status == VerificationStatus.SUSPICIOUS
    assert finding.evidence_grade == EvidenceGrade.B
    assert finding.severity == Severity.HIGH
    assert finding.advisory_only is False
    assert finding.confidence_features["rule_id"] == "RAG.GROUNDED_CONTRADICTION"
    assert len(finding.evidence) == 2


def test_positive_temporal_post_disposition_amendment_recalculated():
    """양성 2: 처분일(2023. 5. 10.)보다 뒤에 시행된 개정 규정(2024. 1. 1.)을 적용하라는 모델 지적이 서면 내부 날짜로 재계산 확인되어 승격."""
    doc_text = "처분청은 2023년 5월 10일 원고에게 처분을 내렸으나, 2024년 1월 1일 시행된 개정 규정에 의하면 이는 위법합니다."
    remark_text = "[anthropic] 2024. 1. 1. 시행된 개정 규정을 2023. 5. 10. 처분에 소급 적용하라고 주장하는 모순"

    finding, rejected = verify_model_fact_recalculation(
        remark_text, doc_text, reference_date_str="2023-05-10", document_id="doc_test"
    )

    assert rejected is None
    assert finding is not None
    assert finding.status == VerificationStatus.SUSPICIOUS
    assert finding.evidence_grade == EvidenceGrade.B
    assert finding.type == FindingType.TEMPORAL_LAW_MISMATCH
    assert finding.advisory_only is False
    assert finding.confidence_features["recalculated"] == "RECALCULATED_VERIFIED"


def test_positive_temporal_statute_of_limitations_days_exceeded():
    """양성 3: 송달일(2023. 3. 1.)부터 제소일(2023. 6. 1., 92일)까지 기간이 60일 이내 제소 주장을 초과함이 서면 내부 날짜로 재계산 확인."""
    doc_text = "원고는 처분서를 2023. 3. 1. 송달받았고, 본 소는 2023. 6. 1. 제기되었으므로 60일 이내에 적법하게 제소되었습니다."
    remark_text = "[gemini] 송달일 2023. 3. 1.부터 제소일 2023. 6. 1.까지 92일이 경과하여 60일 이내 제소 주장은 날짜 계산상 모순"

    finding, rejected = verify_model_fact_recalculation(
        remark_text, doc_text, reference_date_str=None, document_id="doc_test"
    )

    assert rejected is None
    assert finding is not None
    assert finding.status == VerificationStatus.SUSPICIOUS
    assert finding.evidence_grade == EvidenceGrade.B
    assert finding.type == FindingType.TEMPORAL_LAW_MISMATCH
    assert finding.advisory_only is False
    assert finding.confidence_features["recalculated"] == "RECALCULATED_VERIFIED"


def test_positive_evidence_timeline_inversion_recalculated():
    """양성 4: 서면 제출일(2023. 4. 1.)보다 뒤인 증거 작성일(2023. 4. 20.)이 모델 지적에서 재계산 확인되어 시점 역전 Finding으로 승격."""
    doc_text = "본 준비서면은 2023. 4. 1. 제출되었으며, 첨부된 확인서는 2023. 4. 20. 작성되었습니다."
    remark_text = "[openai] 확인서 작성일 2023. 4. 20.이 서면 제출일 2023. 4. 1.보다 늦음으로 시점 역전 모순"

    finding, rejected = verify_model_fact_recalculation(
        remark_text, doc_text, reference_date_str=None, document_id="doc_test"
    )

    assert rejected is None
    assert finding is not None
    assert finding.status == VerificationStatus.SUSPICIOUS
    assert finding.evidence_grade == EvidenceGrade.B
    assert finding.type == FindingType.EVIDENCE_TIMELINE_INVERSION
    assert finding.advisory_only is False
    assert finding.confidence_features["recalculated"] == "RECALCULATED_VERIFIED"


# ==============================================================================
# 대조군 시험군 (Negative Controls, 5건)
# ==============================================================================


def test_negative_rag_hallucinated_claim_quote_rejected():
    """대조군 1: 서면 원문에 존재하지 않는 가짜(환각) 주장 인용문은 검증기에서 거부(rejected)되고 Finding 미등록."""
    doc_text = "원고는 신의성실의 원칙에 따라 납품 의무를 다하였습니다."
    sources = [{"source_id": "R01", "title": "참고자료", "text": "계약 해제 사유에 관한 규정입니다."}]
    candidate = ModelCandidate(
        candidate_id="c_fake",
        claim_quote="존재하지 않는 가상의 서면 문구입니다",  # 서면에 없음
        defect_type="FACT_CONTRADICTION",
        basis_quote="계약 해제 사유에 관한 규정입니다",
        source_id="R01",
        explanation="가짜 문구 기반 모순 주장",
    )
    finding, rejected = verify_rag_candidate(candidate, doc_text, sources)

    assert finding is None
    assert rejected is not None
    assert rejected["reason"] == "CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT"


def test_negative_rag_hallucinated_basis_quote_rejected():
    """대조군 2: 참고자료 원문에 존재하지 않는 가짜(환각) 규정 인용문은 검증기에서 거부(rejected)되고 Finding 미등록."""
    doc_text = "원고는 계약 해제 사유가 없다고 주장합니다."
    sources = [{"source_id": "R01", "title": "참고자료", "text": "제1조 목적 및 제2조 정의 규정"}]
    candidate = ModelCandidate(
        candidate_id="c_fake_basis",
        claim_quote="계약 해제 사유가 없다고 주장",
        defect_type="FACT_CONTRADICTION",
        basis_quote="참고자료에 전혀 적혀 있지 않은 허위 조항 원문입니다",  # 참고자료에 없음
        source_id="R01",
        explanation="허위 조항 기반 모순 지적",
    )
    finding, rejected = verify_rag_candidate(candidate, doc_text, sources)

    assert finding is None
    assert rejected is not None
    assert rejected["reason"] == "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE"


def test_negative_temporal_valid_prior_law_not_contradicted():
    """대조군 3: 처분일(2024. 5. 10.) 이전의 정당한 구법(2023. 1. 1.) 적용은 모순이 아니므로 재계산 미승인(rejected)."""
    doc_text = "2024년 5월 10일 처분 당시, 2023년 1월 1일 시행된 관련 규정이 적용되었습니다."
    remark_text = "[anthropic] 2023. 1. 1. 시행 규정을 2024. 5. 10. 처분에 적용한 것의 타당성 검토"

    finding, rejected = verify_model_fact_recalculation(
        remark_text, doc_text, reference_date_str="2024-05-10", document_id="doc_test"
    )

    assert finding is None
    assert rejected is not None
    assert rejected["reason"] == "RECALCULATION_UNCONFIRMED"


def test_negative_model_dates_not_present_in_document():
    """대조군 4: 모델 지적에 적힌 날짜가 서면 본문 어디에도 없는 경우 재계산 미승인(rejected)."""
    doc_text = "원고는 성실하게 근무하였으며 아무런 징계 사유가 없습니다."
    remark_text = "[openai] 2029. 12. 31. 날짜와 2030. 1. 1. 날짜가 서로 상충됨"

    finding, rejected = verify_model_fact_recalculation(
        remark_text, doc_text, reference_date_str=None, document_id="doc_test"
    )

    assert finding is None
    assert rejected is not None
    assert rejected["reason"] == "REMARK_DATES_NOT_IN_DOCUMENT"


def test_negative_reconcile_integration_promotes_only_verified():
    """대조군 5: 통합 reconcile_model_fact_remarks에서 재계산 검증 통과 건만 승격되고, 미검증 건은 UNCONFIRMED로 남음."""
    doc_text = "2023년 5월 10일 처분에 대해 2024년 1월 1일 시행 규정을 적용해야 합니다."
    doc = _make_doc(doc_text)

    # 1건은 재계산 가능한 날짜 모순 지적, 1건은 단순 표현 지적
    r1 = _fact_remark_finding(doc, "[anthropic] 2024. 1. 1. 시행 규정을 2023. 5. 10. 처분에 적용한 모순", "PERIOD")
    r2 = _fact_remark_finding(doc, "[gemini] 문맥상 어투가 다소 어색하고 부자연스러움", "OTHER")

    stats = {}
    out = reconcile_model_fact_remarks([r1, r2], stats, doc_text=doc_text, reference_date="2023-05-10")

    # r1은 재계산되어 정식 Finding으로 승격됨
    promoted = [f for f in out if f.confidence_features.get("recalculated") == "RECALCULATED_VERIFIED"]
    assert len(promoted) == 1
    assert promoted[0].status == VerificationStatus.SUSPICIOUS
    assert promoted[0].advisory_only is False

    # r2는 재계산 불가로 UNCONFIRMED로 남음
    unconfirmed = [f for f in out if f.confidence_features.get("reconciled") == "UNCONFIRMED"]
    assert len(unconfirmed) == 1
    assert unconfirmed[0].advisory_only is True
    assert stats["confirmed"] == 1
    assert stats["unconfirmed"] == 1
