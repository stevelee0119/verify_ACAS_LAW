"""AI 법률문서 생성 판별 및 법률 주장 타당성 검토 단위 테스트."""
import asyncio
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
