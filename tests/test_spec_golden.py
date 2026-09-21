"""명세 v1.0 제13장 골든 테스트 T01~T12.

명세가 예로 든 원자료(주주간계약서, 회의록, 이메일)는 이 저장소에 없다.
없는 자료의 내용을 지어내면 시험이 통과해도 아무것도 보장하지 못하므로,
각 시험은 명세가 기술한 **판정 구조**를 최소 입력으로 재현한다.
사건번호와 판시 내용처럼 실재 여부를 확인해야 하는 값은 쓰지 않는다.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from packages.claim_engine.assertion import analyze_assertions, draft_artifact_findings
from packages.claim_engine.deterministic import (
    Input,
    apply_rounding,
    months_elapsed,
    multiply,
    verify_stated,
    vesting,
    vesting_sensitivity,
)
from packages.claim_engine.fact_ledger import FactLedger
from packages.claim_engine.resolution import (
    AGAINST,
    BOARD_RESOLUTION_COMMERCIAL_ACT,
    FOR,
    Attendee,
    evaluate_resolution,
    resolution_findings,
)
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ReleaseGate,
    Severity,
    SupportType,
    VerificationStatus,
)
from packages.common.schemas import Block, Finding, NormalizedDocument, Page
from packages.legal_engine.internal_citation import (
    build_clause_index,
    check_references,
    internal_citation_findings,
)
from packages.legal_engine.omission import analyze_omissions, omission_findings
from packages.legal_engine.quotation import (
    check_proviso_omission,
    check_quote,
    extract_quotes,
    quote_findings,
)
from packages.verification_engine.gate import claim_confidence, evaluate_gate, risk_index


def _finding(type_, *, severity=Severity.HIGH, status=VerificationStatus.CONTRADICTED) -> Finding:
    return Finding.create(type=type_, status=status, severity=severity,
                          evidence_grade=EvidenceGrade.A, title=str(type_))


def _doc(text: str, document_id: str = "D1") -> NormalizedDocument:
    doc = NormalizedDocument(document_id=document_id, filename=f"{document_id}.pdf",
                             mime_type="application/pdf", sha256="x")
    page = Page(page_number=1)
    page.blocks.append(Block(block_id="b1", text=text, page=1, source_layer="visible_text"))
    doc.pages.append(page)
    return doc


# --- T01 조항번호 교차검증 ----------------------------------------------------
CONTRACT_TEXT = (
    "제11조 (동반매도요구권) 주주는 다른 주주에게 동반매도를 요구할 수 있다. "
    "제24조 (공정가치) Fair Value는 외부 평가기관이 산정한 금액으로 한다."
)


def test_t01_wrong_clause_number_is_flagged_with_a_candidate():
    """제11조라고 적었으나 해당 내용은 제24조에 있다."""
    index = build_clause_index(_doc(CONTRACT_TEXT, "CONTRACT"))
    checks = check_references("주주간계약서 제11조의 Fair Value 산정 방식에 따라 계산한다.", index)
    findings = internal_citation_findings(checks, source_label="주주간계약서")

    assert [str(f.type) for f in findings] == ["INTERNAL_CITATION_ERROR"]
    assert "제24조" in findings[0].detail, "수정 후보 조항을 제시해야 한다"
    assert findings[0].severity == Severity.HIGH


def test_t01_correct_clause_number_passes_silently():
    index = build_clause_index(_doc(CONTRACT_TEXT, "CONTRACT"))
    checks = check_references("주주간계약서 제24조의 Fair Value 산정 방식", index)
    assert internal_citation_findings(checks) == []


def test_t01_instruction_clause_number_is_not_trusted():
    """제2.1장. 사용자 지시문도 검증대상이지 신뢰된 사실이 아니다."""
    index = build_clause_index(_doc(CONTRACT_TEXT, "CONTRACT"))
    checks = check_references("지시문에 따라 제11조의 Fair Value를 검토한다.", index)
    assert any(c.matches_concept is False for c in checks)


# --- T02 옵저버 의결권 --------------------------------------------------------
def _observer_meeting():
    return {
        FOR: [
            Attendee("갑", "사내이사", has_voting_right=True, source_span="MIN:p1"),
            Attendee("을", "사외이사(옵저버)", has_voting_right=False, source_span="MIN:p1",
                     note="회의록에 '옵저버 자격, 의결권 없음'으로 기재"),
        ],
        AGAINST: [Attendee("병", "사내이사", has_voting_right=True, source_span="MIN:p1")],
    }


def test_t02_nominal_and_effective_tallies_are_separate():
    """명목 2:1과 유효 1:1을 각각 제시해야 한다."""
    result = evaluate_resolution(agenda="주식 취득 승인", votes=_observer_meeting(),
                                 total_members=3, rule=BOARD_RESOLUTION_COMMERCIAL_ACT)
    assert result.nominal.for_ == 2 and result.nominal.against == 1
    assert result.effective.for_ == 1 and result.effective.against == 1
    assert any(e["reason"].startswith("의결권 없음") for e in result.excluded)


def test_t02_claimed_passage_contradicts_the_effective_tally():
    result = evaluate_resolution(agenda="주식 취득 승인", votes=_observer_meeting(),
                                 total_members=3, rule=BOARD_RESOLUTION_COMMERCIAL_ACT)
    assert result.passed is False
    types = {str(f.type) for f in resolution_findings(result, asserted_passed=True)}
    assert "FACT_CONTRADICTION" in types


def test_t02_unknown_voting_right_is_not_assumed_to_exist():
    """의결권 유무가 기록에 없으면 있다고 보지 않는다."""
    votes = {FOR: [Attendee("정", "참석자", has_voting_right=None, source_span="MIN:p1")]}
    result = evaluate_resolution(agenda="안건", votes=votes,
                                 rule=BOARD_RESOLUTION_COMMERCIAL_ACT)
    assert result.effective.cast == 0
    assert "확인" in result.undetermined_reason


def test_t02_quorum_rule_records_its_own_basis():
    """정족수 기준은 근거와 함께 표시된다. 근거 없는 정족수 판단은 하지 않는다."""
    result = evaluate_resolution(agenda="안건", votes=_observer_meeting(), total_members=3,
                                 rule=BOARD_RESOLUTION_COMMERCIAL_ACT)
    assert result.to_dict()["rule"]["basis_citation"] == "상법 제391조 제1항"
    bare = evaluate_resolution(agenda="안건", votes=_observer_meeting())
    assert bare.passed is None, "기준이 없으면 가결 여부를 단정하지 않는다"


# --- T03 상충자료 -------------------------------------------------------------
def _conflicted_ledger() -> FactLedger:
    ledger = FactLedger()
    ledger.add(predicate="incorporation_date", subject="대상회사", value=date(2020, 3, 2),
               value_type="date", source_spans=["DOC_CONTRACT:p1:정의조항"])
    ledger.add(predicate="incorporation_date", subject="대상회사", value=date(2020, 3, 15),
               value_type="date", source_spans=["DOC_MINUTES:p1"])
    return ledger


def test_t03_conflicting_sources_are_preserved_not_resolved():
    conflicts = _conflicted_ledger().conflicts()
    assert len(conflicts) == 1
    assert len(conflicts[0].facts) == 2, "상충자료를 지우면 안 된다"
    assert conflicts[0].resolved is False


def test_t03_asserting_one_value_without_explanation_is_flagged():
    findings = _conflicted_ledger().findings(
        asserted_conclusions={("대상회사", "incorporation_date"): "2020-03-15"})
    assert any(f.type == FindingType.SOURCE_CONFLICT_IGNORED for f in findings)


def test_t03_no_finding_when_the_document_does_not_assert():
    """충돌이 있다는 사실만으로는 오류가 아니다. 단정했을 때 오류다."""
    findings = _conflicted_ledger().findings(asserted_conclusions={})
    assert not any(f.type == FindingType.SOURCE_CONFLICT_IGNORED for f in findings)


# --- T04 해석값과 계산 --------------------------------------------------------
def test_t04_derived_date_is_marked_as_inferred():
    ledger = FactLedger()
    fact = ledger.add(
        predicate="employment_end_date", subject="퇴사예정자", value=date(2025, 12, 31),
        value_type="date", source_spans=["DOC_EMAIL:p2:l10-12"],
        support_type=SupportType.INFERRED,
        inference_rule="2025-11-03 이메일의 '다음 달 말까지 인수인계하고 퇴사'",
    )
    payload = fact.to_dict()
    assert payload["support_type"] == "INFERRED"
    assert payload["inference_rule"], "도출 근거 없이 해석값을 만들 수 없다"


def test_t04_inferred_fact_requires_an_inference_rule():
    with pytest.raises(ValueError):
        FactLedger().add(predicate="p", subject="s", value=1,
                         support_type=SupportType.INFERRED)


def test_t04_alternative_reference_dates_are_shown_side_by_side():
    """기준일 전제별 결과를 나란히 제시한다. 하나를 골라 주지 않는다."""
    sensitivity = vesting_sensitivity(
        total_shares=Input("총주식수", 360000, "주", "DOC_TERMSHEET:p1"),
        start=Input("기산일", date(2022, 1, 1), source_span="DOC_CONTRACT:p2"),
        as_of_candidates=[
            Input("평가기준일(2025-11-01)", date(2025, 11, 1), source_span="DOC_MEMO:p1"),
            Input("퇴사예정일(2025-12-31)", date(2025, 12, 31),
                  source_span="DOC_EMAIL:p2", support="INFERRED"),
        ],
        vesting_months=Input("베스팅기간", 48, "", "DOC_CONTRACT:p2"),
    )
    assert sensitivity.diverges, "전제가 다르면 결과가 갈린다는 사실을 보여야 한다"
    months = [c["outputs"]["elapsed_months"] for c in sensitivity.cases]
    assert months == ["46", "47"]
    assert "담당 변호사" in sensitivity.note


def test_t04_unvested_price_is_independently_recomputed():
    check = verify_stated(
        multiply(quantity=Input("미베스팅주식수", 7292, "주", "DOC_ANSWER:p3"),
                 unit_price=Input("주당가액", 500, "원", "DOC_CONTRACT:p4")),
        "amount", 3_646_000)
    assert check["matches"] is True
    wrong = verify_stated(
        multiply(quantity=Input("미베스팅주식수", 7292, "주", "DOC_ANSWER:p3"),
                 unit_price=Input("주당가액", 500, "원", "DOC_CONTRACT:p4")),
        "amount", 3_640_000)
    assert wrong["matches"] is False and wrong["delta"] == "-6000"


# --- T05 판례 실재 여부 -------------------------------------------------------
def test_t05_missing_case_blocks_immediately():
    """존재하지 않는 판례는 점수와 무관하게 BLOCK이다."""
    decision = evaluate_gate([_finding(FindingType.CASE_NOT_FOUND, severity=Severity.CRITICAL)])
    assert decision.gate == ReleaseGate.BLOCK
    assert decision.hard_block_reasons


def test_t05_case_not_found_is_never_downgraded_to_pass_by_low_score():
    """가중합이 낮아도 하드게이트가 이긴다(제9.1장)."""
    decision = evaluate_gate([_finding(FindingType.CASE_NOT_FOUND)])
    assert decision.risk_index < 70 and decision.gate == ReleaseGate.BLOCK


# --- T06 판례 관련성 ----------------------------------------------------------
def test_t06_existence_and_relevance_are_scored_separately():
    """존재는 통과, 관련성은 실패. 하나의 '검증 완료'로 뭉개지 않는다."""
    scored = claim_confidence({
        "source_existence": 1.0, "text_accuracy": 1.0, "temporal_applicability": 1.0,
        "issue_relevance": 0.2, "reasoning_completeness": 0.8,
    })
    assert scored["axes"]["source_existence"] == 1.0
    assert scored["axes"]["issue_relevance"] == 0.2
    assert scored["verdict"] != "SUFFICIENT"


def test_t06_zero_axis_cannot_be_averaged_away():
    scored = claim_confidence({
        "source_existence": 1.0, "text_accuracy": 1.0, "temporal_applicability": 1.0,
        "issue_relevance": 0.0, "reasoning_completeness": 1.0,
    })
    assert scored["confidence"] >= 0.8
    assert scored["verdict"] == "HARD_FAIL", "평균이 높아도 통과시키면 안 된다"


def test_t06_unmeasured_axis_yields_no_confidence_number():
    scored = claim_confidence({
        "source_existence": 1.0, "text_accuracy": None, "temporal_applicability": 1.0,
        "issue_relevance": 1.0, "reasoning_completeness": 1.0,
    })
    assert scored["confidence"] is None and scored["verdict"] == "UNVERIFIABLE"


# --- T07 법령 시점 ------------------------------------------------------------
def test_t07_wrong_statute_version_blocks():
    decision = evaluate_gate([_finding(FindingType.TEMPORAL_LAW_MISMATCH,
                                       severity=Severity.CRITICAL)])
    assert decision.gate == ReleaseGate.BLOCK


def test_t07_statute_version_error_keeps_the_spec_code_name():
    from packages.common.enums import spec_code
    assert spec_code(FindingType.TEMPORAL_LAW_MISMATCH) == "STATUTE_VERSION_ERROR"


# --- T08 자기주식 취득 누락 ---------------------------------------------------
def test_t08_recommendation_without_requirements_is_flagged():
    reports = analyze_omissions("회사가 전량 매수하면 된다.")
    findings = omission_findings(reports)
    assert [str(f.type) for f in findings] == ["LEGAL_REQUIREMENT_OMITTED"]
    assert findings[0].severity == Severity.HIGH
    for keyword in ("재원", "기관 결의"):
        assert keyword in findings[0].detail


def test_t08_checklist_does_not_declare_the_document_unlawful():
    """제7.2장 단서. 체크리스트 매칭만으로 법률 결론을 확정하지 않는다."""
    findings = omission_findings(analyze_omissions("회사가 전량 매수하면 된다."))
    detail = findings[0].detail
    assert "위법" not in detail and "무효이다" not in detail
    assert "담당 변호사가 확정한다" in detail
    assert findings[0].status == VerificationStatus.UNVERIFIED


def test_t08_a_contract_clause_alone_is_not_an_omission():
    """결론이 없는 문서에는 누락이라 할 대상이 없다.

    계약서처럼 조항만 담은 문서에까지 체크리스트를 들이대면 실제 검토
    누락이 그 소음에 묻힌다.
    """
    contract = "제11조 (동반매도요구권) 주주는 다른 주주에게 동반매도를 요구할 수 있다."
    reports = analyze_omissions(contract)
    assert reports and reports[0].missing, "체크리스트 자체는 작동해야 한다"
    assert omission_findings(reports) == []
    assert omission_findings(reports, require_conclusion=False), "명시 요청 시에는 보고한다"


def test_t08_covered_requirements_are_not_reported_as_missing():
    text = ("자기주식 취득은 배당가능이익 범위에서 주주총회 결의로 각 주주에게 통지하여 "
            "균등한 조건으로 하며, 주주평등 원칙을 지켜야 하고, 합병의 경우 예외가 있으며 "
            "위반 시 효력이 문제된다. 검토 결과 위 요건을 모두 충족한다고 판단된다.")
    assert omission_findings(analyze_omissions(text)) == []


# --- T09 직접인용 왜곡 --------------------------------------------------------
SOURCE_SENTENCE = ("채무자가 그 채무를 이행하지 아니한 경우에는 채권자는 손해배상을 청구할 수 있다. "
                   "다만, 채무자의 고의나 과실이 없는 때에는 그러하지 아니하다.")


def test_t09_altered_quotation_is_a_mismatch():
    quoted = "채무자는 어떠한 경우에도 손해배상책임을 진다"
    check = check_quote(quoted, SOURCE_SENTENCE, source_label="원문")
    assert check.status == VerificationStatus.CONTRADICTED
    findings = quote_findings([check])
    assert [str(f.type) for f in findings] == ["QUOTE_MISMATCH"]
    assert findings[0].severity == Severity.CRITICAL


def test_t09_exact_quotation_passes():
    quoted = "채무자가 그 채무를 이행하지 아니한 경우에는 채권자는 손해배상을 청구할 수 있다"
    assert check_quote(quoted, SOURCE_SENTENCE).status == VerificationStatus.VERIFIED


def test_t09_quotation_without_the_source_text_is_unverified_not_verified():
    """제11.1장. 공식 원문이 없으면 일치로도 불일치로도 처리하지 않는다."""
    check = check_quote("무엇이든", None)
    assert check.status == VerificationStatus.UNVERIFIED
    assert quote_findings([check]) == [], "미확보는 Finding이 아니라 미검증 항목이다"


def test_t09_quotation_marks_are_extracted_from_the_body():
    text = '법원은 “채무자는 손해배상책임을 진다”라고 판시하였다.'
    assert extract_quotes(text)[0][0] == "채무자는 손해배상책임을 진다"


def test_t09_dropping_the_proviso_is_detected_separately():
    """인용 자체는 정확해도 단서를 가리면 요건이 달라진다."""
    quoted = "채무자가 그 채무를 이행하지 아니한 경우에는 채권자는 손해배상을 청구할 수 있다"
    proviso = check_proviso_omission(quoted, SOURCE_SENTENCE, f"원문은 “{quoted}”라고 한다.")
    assert proviso is not None and proviso.startswith("다만")


# --- T10 초안 흔적 ------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "이 부분은 인용 검증 필요.",
    "[TODO] 판례번호 확인",
    "[판례 추가 필요]",
    "관련 근거는 추후 보완한다.",
])
def test_t10_draft_markers_are_detected(text):
    assert [str(f.type) for f in draft_artifact_findings(text)] == ["DRAFT_ARTIFACT"]


def test_t10_draft_artifact_yields_at_least_a_warning_gate():
    decision = evaluate_gate([_finding(FindingType.DRAFT_ARTIFACT, severity=Severity.MEDIUM)])
    assert decision.gate != ReleaseGate.PASS
    assert decision.risk_index == 10


def test_t10_clean_text_produces_no_draft_finding():
    assert draft_artifact_findings("원고는 피고에게 손해배상을 청구한다.") == []


# --- T11 다수모델 합의의 한계 --------------------------------------------------
def test_t11_model_agreement_alone_never_verifies():
    """제8.1장. 여러 모델이 같은 답을 했다는 이유로 사실로 확정하지 않는다."""
    from packages.common.confidence import FEATURE_WEIGHTS, score

    agreement_only = score({"model_agreement": 4, "single_model_opinion": False})
    assert agreement_only < 0.8, "모델 합의만으로 높은 신뢰도를 주면 안 된다"
    assert FEATURE_WEIGHTS["model_agreement"][0] < FEATURE_WEIGHTS["official_source_match"][0]


def test_t11_official_source_outranks_model_consensus():
    from packages.common.confidence import score

    consensus = score({"model_agreement": 3})
    official = score({"official_source_match": True})
    assert official > consensus


def test_t11_risk_index_ignores_model_opinion_entirely():
    """검증위험 지수에는 모델 의견이 들어가지 않는다(제8.2장)."""
    from packages.verification_engine.gate import RISK_WEIGHTS

    names = {str(t) for t in RISK_WEIGHTS}
    assert not any("MODEL" in n or "AI_AUTHORSHIP" in n or "STYLE" in n for n in names)


# --- T12 불변식 ---------------------------------------------------------------
def test_t12_vesting_invariant_holds_for_every_rounding_rule():
    for rule in ("FLOOR", "CEILING", "HALF_UP", "HALF_EVEN", "TRUNCATE"):
        calculation = vesting(
            total_shares=Input("총주식수", 357001, "주", "DOC:p1"),
            start=Input("기산일", date(2022, 1, 1), source_span="DOC:p1"),
            as_of=Input("기준일", date(2025, 11, 15), source_span="DOC:p1"),
            vesting_months=Input("베스팅기간", 48, "", "DOC:p1"),
            rounding_rule=rule,
        )
        outputs = calculation.outputs
        assert outputs["vested_shares"] + outputs["unvested_shares"] == Decimal(357001)
        assert calculation.invariants_hold, f"{rule}에서 불변식이 깨졌다"


def test_t12_violated_invariant_is_reported_with_the_rounding_rule():
    """불변식 위반은 계산 단계와 반올림 규칙을 함께 표시해야 한다."""
    calculation = vesting(
        total_shares=Input("총주식수", 357000, "주", "DOC:p1"),
        start=Input("기산일", date(2022, 1, 1), source_span="DOC:p1"),
        as_of=Input("기준일", date(2025, 11, 1), source_span="DOC:p1"),
        vesting_months=Input("베스팅기간", 48, "", "DOC:p1"),
        rounding_rule="HALF_UP",
    )
    payload = calculation.to_dict()
    assert payload["rounding_rule"] == "HALF_UP"
    assert payload["formula"]
    assert payload["invariants"][0]["expression"] == (
        "vested_shares + unvested_shares == total_shares")
    stated = verify_stated(calculation, "vested_shares", 342708)
    assert stated["matches"] is False
    assert stated["rounding_rule"] == "HALF_UP" and stated["formula"]


def test_t12_calculation_error_contributes_to_the_risk_index():
    total, contributions = risk_index([
        _finding(FindingType.CALCULATION_INVARIANT_VIOLATION),
        _finding(FindingType.ARITHMETIC_MISMATCH),
    ])
    assert total == 50
    assert {c.weight for c in contributions} == {25}


def test_t12_inputs_without_a_source_span_are_named():
    calculation = vesting(
        total_shares=Input("총주식수", 100, "주"),
        start=Input("기산일", date(2022, 1, 1), source_span="DOC:p1"),
        as_of=Input("기준일", date(2024, 1, 1), source_span="DOC:p1"),
        vesting_months=Input("베스팅기간", 48, "", "DOC:p1"),
    )
    assert calculation.unsourced_inputs == ["총주식수"]


# --- 제16장 인수기준 가운데 구조로 고정할 수 있는 것 --------------------------
def test_acceptance_source_failure_is_never_marked_verified():
    assert check_quote("아무 문장", None).status == VerificationStatus.UNVERIFIED


def test_acceptance_unreadable_document_does_not_pass():
    assert evaluate_gate([], nothing_analyzed=True).gate == ReleaseGate.HUMAN_REVIEW_REQUIRED


def test_acceptance_clean_run_passes():
    assert evaluate_gate([]).gate == ReleaseGate.PASS


def test_acceptance_every_spec_finding_code_is_reachable():
    """제1.2장 20개 코드가 모두 FindingType 또는 대응표로 존재해야 한다."""
    from packages.common.enums import SPEC_FINDING_CODE, spec_code

    required = {
        "CASE_NONEXISTENT", "CASE_METADATA_MISMATCH", "CASE_HOLDING_MISMATCH",
        "CASE_RELEVANCE_WEAK", "STATUTE_NONEXISTENT", "STATUTE_VERSION_ERROR",
        "STATUTE_TEXT_MISMATCH", "INTERNAL_CITATION_ERROR", "QUOTE_MISMATCH",
        "FACT_UNSUPPORTED", "FACT_CONTRADICTION", "SOURCE_CONFLICT_IGNORED",
        "CALCULATION_ERROR", "LEGAL_REQUIREMENT_OMITTED", "OVERCLAIM", "REASONING_GAP",
        "AUTHORITY_RANK_ERROR", "SECONDARY_SOURCE_ERROR", "DRAFT_ARTIFACT",
        "UNCERTAINTY_NOT_DISCLOSED",
    }
    available = {spec_code(t) for t in FindingType}
    assert required - available == set(), f"미구현 코드: {sorted(required - available)}"


def test_acceptance_risk_index_is_labelled_as_a_verification_risk():
    """제8.2장. 작성주체 확률로 읽히면 안 된다."""
    payload = evaluate_gate([_finding(FindingType.DRAFT_ARTIFACT)]).to_dict()
    assert "작성주체 확률이 아니라" in payload["risk_index_note"]


def test_acceptance_auto_fix_scope_excludes_legal_judgement():
    """제9.3장. 법적 평가는 자동수정 대상이 아니다."""
    from packages.verification_engine.gate import AUTO_FIXABLE_TYPES, LAWYER_APPROVAL_TYPES

    assert AUTO_FIXABLE_TYPES.isdisjoint(LAWYER_APPROVAL_TYPES)
    for type_ in (FindingType.CASE_HOLDING_DISTORTION, FindingType.OVERCLAIM,
                  FindingType.LEGAL_REQUIREMENT_OMITTED, FindingType.SOURCE_CONFLICT_IGNORED):
        assert type_ not in AUTO_FIXABLE_TYPES
        assert type_ in LAWYER_APPROVAL_TYPES
