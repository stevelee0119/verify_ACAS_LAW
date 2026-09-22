"""AI 법률문서 생성 판별 및 법률 주장 타당성 검토 단위 테스트."""
import asyncio
from datetime import date
import pytest

from packages.common.enums import ClaimType, EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Block, Citation, CitationType, Claim, Finding, NormalizedDocument, Page
from packages.verification_engine.ai_document_detector import (
    create_ai_detector_findings,
    detect_ai_document,
)
from packages.legal_engine.argument_validity_verifier import (
    verify_argument_validity,
)


def _make_sample_doc(text: str, filename: str = "답변서.pdf") -> NormalizedDocument:
    doc = NormalizedDocument(
        document_id="doc_test_1",
        filename=filename,
        mime_type="application/pdf",
        sha256="testsha256",
    )
    page = Page(page_number=1)
    page.blocks.append(Block(block_id="b1", text=text, page=1, source_layer="visible_text"))
    doc.pages.append(page)
    doc.raw_layers["visible_text"] = text
    return doc


def test_ai_document_detector_with_chatbot_cliches_and_fake_case():
    # 챗봇 상투구 및 가짜 판례 정황이 포함된 서면
    text = (
        "답변서\n\n"
        "사건: 2024가합12345 손해배상(기)\n"
        "원고: 홍길동\n"
        "피고: 주식회사 테스트\n\n"
        "1. 원고의 주장에 대하여\n"
        "원고는 피고가 채무를 불이행하였다고 주장하나, 다음과 같은 점들이 있습니다.\n"
        "첫째, 피고는 계약상 의무를 모두 이행하였습니다.\n"
        "둘째, 대법원 2099다99999 판결에 따르면 이와 같은 경우 손해배상 책임이 성립하지 않습니다.\n"
        "종합하자면 피고에게는 귀책사유가 없습니다.\n"
        "도움이 되었기를 바랍니다. 추가적인 질문이 있으시면 언제든 문의해 주십시오."
    )
    doc = _make_sample_doc(text)

    # 가짜 판례 finding 모의
    citation_findings = [
        Finding.create(
            type=FindingType.CASE_NOT_FOUND,
            status=VerificationStatus.NOT_FOUND,
            severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.B,
            title="공식 Source에서 확인되지 않는 판례 인용: 대법원 2099다99999 판결",
            detail="일치하는 기록을 공식 Source에서 확인하지 못했다",
            document_id=doc.document_id,
            engine="legal_engine",
            tags=["LEGAL", "CASE"],
        )
    ]

    res = asyncio.run(
        detect_ai_document(
            doc,
            citation_findings,
            router=None,  # 규칙 기반 검출 검증
            metadata_indications=True,
        )
    )

    # 검증: AI 생성 유력 판정 및 근거가 올바르게 추출되었는지 확인
    assert res.verdict in ("AI_FULL_GENERATION_LIKELY", "AI_PARTIAL_GENERATION")
    assert res.score >= 0.5
    assert any("챗봇" in r or "관용구" in r for r in res.reasons)
    assert any("판례" in r for r in res.reasons)

    # Finding 생성 검증
    findings = create_ai_detector_findings(doc, res)
    assert len(findings) > 0
    assert any(f.type in (FindingType.AI_FULL_GENERATION_SUSPECTED, FindingType.AI_AUTHORSHIP_LIKELY) for f in findings)


def test_argument_validity_verifier_generates_hallucination_table():
    text = (
        "원고는 피고의 행위가 불법행위라고 주장하나, "
        "대법원 2088다77777 판결에 의하면 본 사안과 같은 행위는 위법성이 조각되므로 원고의 청구는 기각되어야 합니다."
    )
    doc = _make_sample_doc(text)

    citation = Citation(
        citation_id="cit_1",
        type=CitationType.CASE,
        raw_text="대법원 2088다77777 판결",
        case_number="2088다77777",
        context=text,
        document_id=doc.document_id,
        page=1,
    )

    legal_verdicts = [
        {
            "citation_id": "cit_1",
            "status": "NOT_FOUND",
            "levels": {"level1": "NOT_FOUND"},
        }
    ]

    claims = [
        Claim(
            claim_id="cl_1",
            type=ClaimType.LEGAL_RULE,
            text="피고의 행위는 위법성이 조각된다",
            document_id=doc.document_id,
        )
    ]

    result = asyncio.run(
        verify_argument_validity(
            doc,
            [citation],
            legal_verdicts,
            claims,
            router=None,  # 로컬 규칙 기반
        )
    )

    # 검증: 가짜 판례에 대한 대조표 행(HallucinationTableRow)이 생성되었는지 확인
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.cited_authority == "대법원 2088다77777 판결"
    assert row.authority_exists is False
    assert "공식" in row.ai_generation_basis
    assert "타당성" in row.legal_reasoning or "가공" in row.legal_reasoning
    assert "석명" in row.recommended_counteraction or "배척" in row.recommended_counteraction

    # Finding 생성 검증
    assert len(result.findings) == 1
    assert result.findings[0].type == FindingType.LEGAL_ARGUMENT_INVALID
    assert result.findings[0].severity == Severity.HIGH


def test_unavailable_source_does_not_count_as_fake_case_or_ai_generation():
    doc = _make_sample_doc("원고의 청구는 이유 없습니다. 계약은 유효합니다. 채무를 이행했습니다.")
    unavailable = Finding.create(
        type=FindingType.CASE_NOT_FOUND, status=VerificationStatus.UNVERIFIED,
        severity=Severity.INFO, evidence_grade=EvidenceGrade.U,
        title="외부 출처 시간 초과", detail="조회 미완료", engine="legal_engine")
    baseline = asyncio.run(detect_ai_document(doc, [], router=None))
    result = asyncio.run(detect_ai_document(doc, [unavailable] * 46, router=None))
    assert result.score == baseline.score
    assert result.reasons == baseline.reasons


# --- 실재 판례를 허위로 단정하지 않는다 ---------------------------------------
def test_real_case_numbers_are_never_called_fabricated():
    """공식 DB에서 확인하지 못한 것과 성립할 수 없는 것은 전혀 다르다.

    국가법령정보 판례 DB는 모든 재판을 수록하지 않는다. 미공개 결정·하급심·
    수록범위 밖 사건은 조회되지 않는다. 그것을 "가공의 판례"로 적으면 실재하는
    판례를 제대로 인용한 서면이 근거 없이 공격당한다. 실제 배포에서 대법원
    2011모1839(형사 재항고)가 허위 의심으로 판정됐다.
    """
    from packages.legal_engine.normalize import case_number_possible

    # 실재할 수 있는 형태 — 결정(모·마·그)과 하급심·헌재를 포함한다.
    for number in ("2011모1839", "2015모2524", "2011마1839", "2019헌바127",
                   "2021구합70769", "2023도12345", "2020다12345", "1998후1234"):
        assert case_number_possible(number) is True, number

    # 성립할 수 없는 형태 — 아직 오지 않은 해, 재판예규에 없는 사건부호.
    for number in (f"{date.today().year + 1}다77777", "2088다77777", "2011좋1839"):
        assert case_number_possible(number) is False, number


def test_unconfirmed_citation_is_reported_as_unconfirmed_not_fabricated():
    """조회 미확인 행은 부존재를 단정하지 않고 확인을 권고해야 한다."""
    from packages.legal_engine.argument_validity_verifier import _basis_for

    class _C:
        def __init__(self, number):
            self.case_number = number
            self.canonical_case_number = number

    assert _basis_for(_C("2011모1839"), "NOT_FOUND") == "UNCONFIRMED"
    assert _basis_for(_C("2011모1839"), "CONTRADICTED") == "CONTENT_MISMATCH"
    assert _basis_for(_C("2088다77777"), "NOT_FOUND") == "FABRICATION_SUSPECTED"


def test_unconfirmed_citations_alone_do_not_drive_the_ai_authorship_verdict():
    """미확인 인용만으로 AI 임의 작성을 추정하지 않는다."""
    from packages.verification_engine.ai_document_detector import _rule_based_ai_detection

    def not_found(number):
        return Finding.create(
            type=FindingType.CASE_NOT_FOUND, status=VerificationStatus.NOT_FOUND,
            severity=Severity.HIGH, evidence_grade=EvidenceGrade.B,
            title=f"미확인: {number}", detail="",
            confidence=0.5, confidence_features={"case_number": number},
            tags=["LEGAL", "CASE"], engine="test")

    body = ("원고는 피고에게 손해배상을 구한다. 대법원 2011모1839 결정과 "
            "대법원 2015모2524 결정의 취지에 따른다. 이에 따라 청구를 인용함이 타당하다. ") * 4
    document = NormalizedDocument(
        document_id="d1", filename="brief.docx", mime_type="text/plain", sha256="x" * 64,
        parser_name="test",
        pages=[Page(page_number=1, width=595.0, height=842.0, blocks=[
            Block(block_id="b1", text=body, page=1, source_layer="visible_text",
                  block_type="paragraph", visible=True)])])

    real = _rule_based_ai_detection(document, [not_found("2011모1839"),
                                               not_found("2015모2524")], False)
    fake = _rule_based_ai_detection(document, [not_found("2088다77777"),
                                               not_found("2099다11111")], False)
    assert real.score < fake.score, "실재 가능한 사건번호가 성립 불가와 같은 점수를 받으면 안 된다"
    assert not any("가공" in reason for reason in real.reasons), real.reasons
