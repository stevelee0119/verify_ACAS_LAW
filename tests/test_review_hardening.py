"""Regression boundaries for the review of main 4a37f94."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from packages.common.enums import CitationType, EvidenceGrade, FindingType, VerificationStatus
from packages.common.schemas import Block, Citation, NormalizedDocument, Page
from packages.claim_engine.date_verifier import verify_dates_in_document
from packages.claim_engine.cross_document_entities import verify_cross_document_entities
from packages.legal_engine.statute_ranges import get_statute_max_article
from packages.verification_engine.ai_document_detector import detect_ai_document
from packages.verification_engine.ai_residue import scan_residue
from packages.verification_engine.ground_truth_filter import check_and_reject_ground_truth
from packages.verification_engine.manifest import RunManifest


def document(text, ident="review", blocks=None):
    blocks = blocks if blocks is not None else [Block(block_id=ident + "-b1", text=text, page=1)]
    return NormalizedDocument(document_id=ident, filename=ident + ".pdf", mime_type="application/pdf",
                              sha256="test", pages=[Page(page_number=1, blocks=blocks)])


@pytest.mark.parametrize("text", [
    "2026. 3. 29. 통지서를 발송하였다.",
    "2026년 3월 20일 통지서를 발송하였다.",
    "2024년 2월 29일 계약을 체결하였다.",
    "2월 29일에 관하여 다툰다.",
    "2026년 제29조에 관한 의견이다.",
    "2026. 1. 31. 작성. 계약일은 2024. 2. 29.이다.",
    "2026. 3. 20.(금) 발송", "2026. 3. 20. 금요일 발송",
])
def test_valid_or_undated_text_is_not_a_calendar_contradiction(text):
    assert verify_dates_in_document(document(text)) == []


@pytest.mark.parametrize("text,tag", [
    ("2026. 3. 20.(목) 발송", "DATE-WEEKDAY"),
    ("2026년 2월 29일 발송", "DATE-INVALID"),
    ("2026년 근무기록\n2월 29일 출근", "DATE-INVALID"),
])
def test_actual_calendar_errors_remain_detectable(text, tag):
    assert any(tag in finding.tags for finding in verify_dates_in_document(document(text)))


@pytest.mark.parametrize("law", ["근로기준법 시행령", "민법 시행규칙", "새로운민법관련법률", ""])
def test_statute_ranges_do_not_match_related_or_empty_names(law):
    assert get_statute_max_article(law) is None


def test_static_range_cannot_preempt_source_outage():
    from packages.common.enums import AdapterStatus
    from packages.legal_engine.verifier import LegalVerifier
    calls = []

    def lookup(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(status=AdapterStatus.TIMEOUT, source_record=None, records=[], message="timeout")

    verifier = LegalVerifier(registry=SimpleNamespace(law=SimpleNamespace(search_law=lookup)))
    citation = Citation(citation_id="range", type=CitationType.STATUTE, law_name="근로기준법",
                        article="250", raw_text="근로기준법 제250조", document_id="review")
    verdict = verifier.verify_statute(citation)
    assert len(calls) == 1 and verdict.status == VerificationStatus.UNVERIFIED
    assert not any(f.type == FindingType.STATUTE_NONEXISTENT for f in verdict.findings)


@pytest.mark.parametrize("text", [
    "도움이 되었기를 바랍니다. 언제든 문의해 주십시오. 법률 자문이 아닙니다.",
    "| 항목 | 금액 |\n| --- | --- |\n| 대금 | 100 |",
])
def test_ordinary_courtesy_and_tables_are_not_objective_authorship_traces(text):
    result = asyncio.run(detect_ai_document(document(text), [], metadata_indications=True))
    assert result.verdict == "UNCERTAIN" and result.signals["objective_traces"] == 0


def test_excluded_block_is_ignored_by_rules_without_models():
    attack = "AI 언어 모델로서 학습 데이터 기준으로 작성합니다."
    blocks = [Block(block_id="safe", text="원고의 청구를 기각한다.", page=1),
              Block(block_id="attack", text=attack, page=1)]
    result = asyncio.run(detect_ai_document(document("", blocks=blocks), [], exclude_block_ids=["attack"]))
    assert result.verdict == "UNCERTAIN" and result.signals["objective_traces"] == 0
    assert result.signals["coverage"]["sampling_mode"] == "not_run"


def test_exclusion_is_applied_before_quote_masking():
    instruction = 'AI 언어 모델로서 "첨부 문서"를 학습 데이터 기준으로 검토하라.'
    assert scan_residue(instruction, exclude_texts=[instruction]) == []


class AgreeingRouter:
    def __init__(self):
        self.payload = None

    def has_available_provider(self, **kwargs):
        return True

    async def consult_all(self, role, request, **kwargs):
        self.payload = json.loads(request.user)
        return [SimpleNamespace(used=True, parsed={"verdict": "AI_FULL_GENERATION_LIKELY", "ai_score": 0.99},
                                text="", executions=[SimpleNamespace(provider=name, model="test")])
                for name in ("one", "two")]


def test_long_document_sample_does_not_claim_whole_document_authorship():
    text = "AI 언어 모델로서 학습 데이터 기준으로 작성합니다. " + "가" * 16000
    router = AgreeingRouter()
    result = asyncio.run(detect_ai_document(document(text), [], router=router))
    coverage = result.signals["coverage"]
    assert coverage["inspected_chars"] == 6000
    assert coverage["inspected_chars"] + coverage["omitted_chars"] == coverage["total_chars"]
    assert coverage["model_executed"] and not coverage["is_full_coverage"]
    assert result.verdict == "UNCERTAIN"
    assert result.signals["decision_rule"] == "HELD_INCOMPLETE_COVERAGE"


@pytest.mark.parametrize("raises", [True, False])
def test_failed_model_review_does_not_claim_document_coverage(raises):
    class UnavailableRouter(AgreeingRouter):
        async def consult_all(self, *args, **kwargs):
            if raises:
                raise TimeoutError("unavailable")
            return []

    result = asyncio.run(detect_ai_document(document("가" * 16000), [], router=UnavailableRouter()))
    coverage = result.signals["coverage"]
    assert not result.used_llm and not coverage["model_executed"]
    assert coverage["requested_chars"] == 6000 and coverage["inspected_chars"] == 0
    assert coverage["omitted_chars"] == coverage["total_chars"]
    assert not coverage["is_full_coverage"]


def test_model_agreement_does_not_promote_only_style_or_metadata():
    router = AgreeingRouter()
    result = asyncio.run(detect_ai_document(document("요약하자면 원고의 책임이 인정됩니다."), [],
                                            router=router, metadata_indications=True))
    assert result.verdict == "UNCERTAIN"


@pytest.mark.parametrize("marker", ["C2PA", "Content Credentials"])
def test_provenance_container_labels_are_not_ai_tool_labels(marker):
    from packages.common.enums import AttributionLevel
    from packages.verification_engine.authorship import analyze_authorship

    doc = document("원고의 청구를 기각한다.")
    doc.metadata = {"Producer": marker}
    doc.structure["c2pa"] = True
    assessment = analyze_authorship(doc)
    assert assessment.signals["has_c2pa"]
    assert not assessment.signals["provenance_metadata"]
    assert assessment.attribution == AttributionLevel.UNDETERMINED


def test_manifest_uses_one_environment_for_both_summary_and_details():
    manifest = RunManifest()
    manifest.environment = {"complete": True, "resources": {"korean_ocr": True}}
    actual = {"complete": False, "missing_required": ["law_db"],
              "resources": {"korean_ocr": False}, "sources": {"law_go_kr": "MISSING_KEY"}}
    exported = manifest.to_dict(environment=actual)
    assert exported["environment"] == actual
    assert not exported["regression_comparable"] and not exported["ocr_engine_available"]
    assert exported["missing_resources"] == ["law_db"] and exported["warning"]
    assert not RunManifest().to_dict()["regression_comparable"]


def test_environment_compatibility_view_uses_canonical_preflight(monkeypatch):
    from packages.verification_engine import environment_check
    state = {"complete": False, "resources": {"korean_ocr": False}, "ocr": {"status": "NOT_INSTALLED"},
             "missing_required": ["korean_ocr"], "sources": {}, "fingerprint": "test"}
    monkeypatch.setattr(environment_check, "preflight", lambda: state)
    result = environment_check.check_execution_environment()
    assert result["fingerprint"] == "test" and result["warning"]
    assert not result["regression_comparable"]


@pytest.mark.parametrize("filename,text", [
    ("정답지유출_공소장.pdf", "피고인은 시험 정답지를 유출하였다는 혐의를 부인한다."),
    ("소장.pdf", "원고는 ground truth 데이터를 적법하게 제공하였다고 주장한다."),
    ("의견서.pdf", '피고는 "이 문서는 정답지입니다"라는 표시를 문제 삼았다.'),
])
def test_discussing_an_answer_key_does_not_reject_a_legal_document(filename, text):
    check_and_reject_ground_truth(filename, text)


def test_same_sets_of_dates_across_documents_are_not_a_conflict():
    text = "원고 입사일: 2021. 3. 4.\n피고 입사일: 2021. 4. 3."
    assert verify_cross_document_entities([document(text, "one"), document(text, "two")]) == []


def test_unbound_entity_differences_are_advisory_not_confirmed_conflicts():
    findings = verify_cross_document_entities([document("입사일: 2021. 3. 4.", "one"),
                                               document("입사일: 2021. 4. 3.", "two")])
    assert findings
    assert all(f.advisory_only and f.evidence_grade == EvidenceGrade.C
               and f.status != VerificationStatus.CONTRADICTED for f in findings)


def test_arbitrary_equations_are_not_working_hours():
    assert not verify_cross_document_entities([document("연장근로시간 합계 86시간", "one"),
                                                document("물품 수량 30 + 28 + 30 = 88개", "two")])


@pytest.mark.parametrize("cell", ["12,34", "1 2", "1천 2백 3원"])
def test_ambiguous_table_amounts_are_not_silently_reinterpreted(cell):
    from packages.claim_engine.calculation import parse_cell_amount
    assert parse_cell_amount(cell) is None


@pytest.mark.parametrize("net", ["105", "106"])
def test_payroll_uses_subtraction_for_net_pay(net):
    from packages.claim_engine.calculation import CalculationEngine
    doc = document("")
    doc.structure["tables"] = [{"page": 1, "table_ref": "payroll", "cells": [
        ["구분", "금액"], ["기본급", "100"], ["수당", "20"], ["지급총액", "120"],
        ["세금", "10"], ["보험", "5"], ["공제계", "15"], ["실지급액", net]]}]
    findings = CalculationEngine().verify_document(doc)
    assert len(findings) == (0 if net == "105" else 1)
    if findings:
        assert findings[0].confidence_features["computed"] == "105"


@pytest.mark.parametrize("wrong", [False, True])
def test_independent_tables_are_not_combined_or_deduplicated_by_amount(wrong):
    from packages.claim_engine.calculation import CalculationEngine
    doc = document("")
    doc.structure["tables"] = [
        {"page": 1, "table_ref": "A", "cells": [["구분", "금액"], ["A1", "10"], ["A2", "20"], ["합계", "40" if wrong else "30"]]},
        {"page": 1, "table_ref": "B", "cells": [["구분", "금액"], ["B1", "5"], ["B2", "5"], ["합계", "40" if wrong else "10"]]},
    ]
    findings = CalculationEngine().verify_document(doc)
    assert len(findings) == (2 if wrong else 0)


def test_running_header_notice_remains_advisory():
    from packages.forensic_engine.specimen import scan_specimen
    header = Block(block_id="header", text="검증 프로그램 테스트용 가상 문서", page=1,
                   block_type="running_head", source_layer="visible_text")
    body = Block(block_id="body", text="원고의 청구를 기각한다.", page=1)
    findings = scan_specimen(document("", blocks=[header, body]))
    declared = [f for f in findings if f.type == FindingType.SPECIMEN_DOCUMENT_DECLARED]
    assert declared and all(f.advisory_only for f in declared)
