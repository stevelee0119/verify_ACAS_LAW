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


class _ConsultRouter:
    """consult_all만 흉내낸다. 공급자별 답과 받은 요청을 기록한다."""

    def __init__(self, answers):
        self.answers, self.requests = answers, []

    def has_available_provider(self, *, policy=None):
        return True

    async def consult_all(self, role, request, *, policy=None, expected_task=""):
        from types import SimpleNamespace
        self.requests.append(request)
        return [SimpleNamespace(used=parsed is not None, parsed=parsed, text="",
                                executions=[SimpleNamespace(provider=name, model="m")])
                for name, parsed in self.answers.items()]


def _unconfirmed_case():
    text = ("원고 홍길동(010-1234-5678)은 대법원 2011모1839 결정에 따라 이 사건 처분이 위법하다고 주장한다.")
    doc = _make_sample_doc(text)
    citation = Citation(citation_id="cit_1", type=CitationType.CASE, raw_text="대법원 2011모1839 결정",
                        case_number="2011모1839", context=text, document_id=doc.document_id, page=1)
    verdicts = [{"citation_id": "cit_1", "status": "NOT_FOUND", "levels": {"level1": "NOT_FOUND"}}]
    return doc, citation, verdicts


def test_ai_opinions_never_turn_an_unconfirmed_case_into_a_fake_one():
    """키가 살아나자 모델 하나의 답으로 미확인 판례가 '허위 판례(CONTRADICTED·HIGH)'가 됐다.

    판정은 규칙이 정하고, 모델 의견은 모두 모아 일치 여부와 함께 참고로만 붙인다.
    """
    doc, citation, verdicts = _unconfirmed_case()
    row = {"item_id": 1, "claim_text": "처분 위법", "validity_verdict": "부당", "legal_reasoning": "법리상 부당",
           "recommended_check": "판결문 확인"}
    router = _ConsultRouter({"anthropic": {"rows": [row]}, "openai": {"rows": [row]},
                             "gemini": {"rows": [{**row, "validity_verdict": "판단 불가"}]}})
    masked = []
    result = asyncio.run(verify_argument_validity(
        doc, [citation], verdicts, [], router=router,
        mask=lambda text: masked.append(text) or text.replace("010-1234-5678", "[전화번호]")))

    finding = result.findings[0]
    assert finding.status == VerificationStatus.UNVERIFIED and finding.severity == Severity.MEDIUM
    assert "허위" not in finding.title
    table = result.rows[0]
    assert table.basis == "UNCONFIRMED" and table.ai_agreement == "DISAGREE"
    assert "[AI 교차검토 참고 · 3개 모델 의견 불일치" in table.legal_reasoning
    assert {o["provider"] for o in table.ai_opinions} == {"anthropic", "openai", "gemini"}
    assert result.ai_providers == ["anthropic", "gemini", "openai"]
    # 모델에게 '존재하지 않는 가공의 판례'라는 전제를 주지 않고, 개인정보는 가린다.
    sent = router.requests[0].system + router.requests[0].user
    assert "가공의 판례" not in sent and "부존재를 뜻하지 않음" in sent
    assert "010-1234-5678" not in router.requests[0].user and masked


def test_authorship_verdict_needs_a_majority_of_models():
    """한 모델만 'AI 전체 작성'이라 해도 그대로 채택하던 것을 막는다."""
    text = "원고는 피고에게 금 1,000만 원을 지급할 것을 청구합니다. 요약하자면 피고의 책임이 인정됩니다."
    doc = _make_sample_doc(text)

    def run(answers):
        return asyncio.run(detect_ai_document(doc, [], router=_ConsultRouter(answers)))

    full = {"verdict": "AI_FULL_GENERATION_LIKELY", "ai_score": 0.9,
            "suspicious_excerpts": [{"snippet": "요약하자면 피고의 책임이 인정됩니다.", "reason": "상투구"},
                                    {"snippet": "본문에 없는 지어낸 문장입니다", "reason": "환각"}]}
    human = {"verdict": "HUMAN_AUTHORED_LIKELY", "ai_score": 0.1}
    uncertain = {"verdict": "UNCERTAIN", "ai_score": 0.4}

    split = run({"anthropic": full, "openai": human, "gemini": uncertain})
    assert split.verdict == "UNCERTAIN" and split.signals["llm_agreement"] == "DISAGREE"
    assert create_ai_detector_findings(doc, split) == [] or all(
        f.type != FindingType.AI_FULL_GENERATION_SUSPECTED for f in create_ai_detector_findings(doc, split))
    assert run({"anthropic": full, "openai": human}).verdict == "HUMAN_AUTHORED_LIKELY"

    agreed = run({"anthropic": full, "openai": full, "gemini": None})
    assert agreed.verdict == "AI_FULL_GENERATION_LIKELY" and agreed.signals["llm_agreement"] == "AGREE"
    snippets = [e["snippet"] for e in agreed.suspicious_excerpts]
    assert "요약하자면 피고의 책임이 인정됩니다." in snippets
    assert all("지어낸" not in s for s in snippets), "본문에 없는 의심 문단은 버린다"
    grades = {f.evidence_grade for f in create_ai_detector_findings(doc, agreed)
              if f.type == FindingType.AI_FULL_GENERATION_SUSPECTED}
    assert grades == {EvidenceGrade.B}


class _FailingConsultRouter(_ConsultRouter):
    """일부 공급자가 실패한 consult_all. 실패 사유를 실행 기록에 담는다."""

    def __init__(self, answers, errors):
        super().__init__(answers)
        self.errors = errors

    async def consult_all(self, role, request, *, policy=None, expected_task=""):
        from types import SimpleNamespace
        results = await super().consult_all(role, request, policy=policy, expected_task=expected_task)
        return results + [SimpleNamespace(used=False, parsed=None, text="",
                                          executions=[SimpleNamespace(provider=name, model="m", error=error)])
                          for name, error in self.errors.items()]


def test_reports_say_which_models_did_not_answer_and_why():
    """'1개 모델(openai) 의견만'만 남으면 나머지가 왜 빠졌는지 알 수 없었다."""
    doc, citation, verdicts = _unconfirmed_case()
    errors = {"gemini": 'HTTP 503: {"message": "high demand"} (재시도 2회 후에도 실패)',
              "anthropic": "OUTPUT_TRUNCATED: 응답이 출력 한도(4096 토큰)에서 잘림"}
    detector = asyncio.run(detect_ai_document(doc, [], router=_FailingConsultRouter(
        {"openai": {"verdict": "UNCERTAIN", "ai_score": 0.3}}, errors)))
    text = " ".join(detector.reasons)
    assert "1개 모델(openai)의 의견만" in text
    assert "gemini(공급자 일시 과부하(HTTP 503) — 재시도 후에도 실패)" in text
    assert "anthropic(응답이 출력 한도에서 잘림)" in text
    assert detector.signals["llm_failures"]["gemini"].startswith("공급자 일시 과부하")

    row = {"item_id": 1, "validity_verdict": "부당", "legal_reasoning": "r"}
    validity = asyncio.run(verify_argument_validity(doc, [citation], verdicts, [], router=_FailingConsultRouter(
        {"openai": {"rows": [row]}}, errors)))
    assert "응답하지 못한 모델: anthropic(응답이 출력 한도에서 잘림), gemini(" in validity.ai_summary
    assert "응답하지 못한 모델" in validity.rows[0].legal_reasoning


def test_many_citations_are_asked_in_small_batches():
    """인용을 한 번에 모두 물으면 응답이 출력 한도에서 잘렸다."""
    doc, _, _ = _unconfirmed_case()
    citations, verdicts = [], []
    for i in range(9):
        citations.append(Citation(citation_id=f"c{i}", type=CitationType.CASE, raw_text=f"대법원 2011모{1800 + i} 결정",
                                  case_number=f"2011모{1800 + i}", context="문맥", document_id=doc.document_id, page=1))
        verdicts.append({"citation_id": f"c{i}", "status": "NOT_FOUND", "levels": {"level1": "NOT_FOUND"}})
    router = _ConsultRouter({"openai": {"rows": []}})
    asyncio.run(verify_argument_validity(doc, citations, verdicts, [], router=router))
    import json
    sizes = [len(json.loads(r.user)["items"]) for r in router.requests]
    assert sizes == [4, 4, 1] and all(r.max_tokens == 4096 for r in router.requests)


def test_a_single_model_cannot_raise_the_authorship_verdict_alone():
    """두 모델이 빠진 채 한 모델만 'AI 전체 작성'이라 해도 95%로 표시되던 것을 막는다."""
    text = "원고는 피고에게 금 1,000만 원을 지급할 것을 청구합니다."
    doc = _make_sample_doc(text)
    errors = {"anthropic": "HTTP 503: overloaded", "openai": "HTTP 503: overloaded"}
    result = asyncio.run(detect_ai_document(doc, [], router=_FailingConsultRouter(
        {"gemini": {"verdict": "AI_FULL_GENERATION_LIKELY", "ai_score": 0.95}}, errors)))
    assert result.verdict != "AI_FULL_GENERATION_LIKELY"
    assert result.score < 0.95
    assert any("참고로만 두고" in r for r in result.reasons)
    assert all(f.type != FindingType.AI_FULL_GENERATION_SUSPECTED for f in create_ai_detector_findings(doc, result))


def test_ocr_spaced_resident_numbers_are_masked_before_leaving():
    from packages.pii_engine.detector import detect

    for sample in ("주민등록번호 : 800101 - 1234567", "800101  1234567", "800101-1234567"):
        assert any(m.kind == "RRN" for m in detect(sample)), sample
    assert not any(m.kind == "RRN" for m in detect("800101\n1234567")), "줄을 넘는 숫자는 묶지 않는다"


def test_every_model_verdict_and_explanation_is_kept():
    """화면에는 근거 3개만, 저장은 모델마다 2개만 남아 OpenAI·Gemini 설명이 빠졌다."""
    doc = _make_sample_doc("원고는 피고에게 금 1,000만 원을 지급할 것을 청구합니다. 요약하자면 피고의 책임이 인정됩니다.")
    answers = {
        "anthropic": {"verdict": "UNCERTAIN", "ai_score": 0.4, "reasons": ["a1", "a2", "a3"]},
        "openai": {"verdict": "AI_PARTIAL_GENERATION", "ai_score": 0.6, "reasons": ["o1", "o2"]},
        "gemini": {"verdict": "AI_FULL_GENERATION_LIKELY", "ai_score": 0.9, "reasons": ["g1", "g2", "g3"]},
    }
    result = asyncio.run(detect_ai_document(doc, [], router=_ConsultRouter(answers)))
    opinions = {o["provider"]: o for o in result.signals["llm_opinions"]}
    assert {p: o["verdict"] for p, o in opinions.items()} == {p: a["verdict"] for p, a in answers.items()}
    assert {p: o["reasons"] for p, o in opinions.items()} == {p: a["reasons"] for p, a in answers.items()}
    for provider, answer in answers.items():
        for reason in answer["reasons"]:
            assert f"[{provider}] {reason}" in result.reasons

    from types import SimpleNamespace

    from packages.report_engine.model_opinions import model_opinion_rows
    rows = model_opinion_rows([SimpleNamespace(filename="a.pdf", ai_detector_result=result.to_dict())])
    assert [r[1].split(" ")[0] for r in rows] == ["Anthropic", "OpenAI", "Gemini"]
    assert "- g3" in rows[2][4] and rows[2][2] == "AI 임의 전체 작성 유력"
