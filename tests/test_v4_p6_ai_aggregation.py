"""v4 P6: AI 판별 집계 — 관여 여부·범위 축 분리, 약한 신호는 참고 부록, 모델 근거의 종류 구조화."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.common.enums import FindingType
from packages.verification_engine.ai_document_detector import (
    AIDetectorResult, _combine_model_verdicts, _rule_based_ai_detection, _structured_reasons,
    create_ai_detector_findings)
from packages.verification_engine.scoring import unified_authorship
from tests.test_verification_regressions import document

PLAIN = {
    "민사": ["원고는 피고에게 금 30,000,000원의 지급을 구한다.", "피고는 2023. 3. 15. 원고에게 물품을 인도하였다."] * 4,
    "형사": ["피고인은 2021. 6. 1. 공소사실 기재와 같이 기소되었다.", "피고인은 범행을 부인한다."] * 4,
    "가사": ["원고와 피고는 2010. 5. 1. 혼인신고를 하였다.", "원고는 재산분할을 구한다."] * 4,
}


@pytest.mark.parametrize("field", list(PLAIN))
def test_plain_document_without_ai_tool_metadata_gets_no_ai_finding(field):
    # 일반 메타데이터 이상(생성·저장 도구 다름 등)은 AI 관여 근거가 아니다(metadata_indications=False).
    result = _rule_based_ai_detection(document(*PLAIN[field]), [], metadata_indications=False)
    assert result.verdict == "UNCERTAIN" and result.score < 0.35
    assert not [f for f in create_ai_detector_findings(document(*PLAIN[field]), result)
                if f.type in (FindingType.AI_AUTHORSHIP_LIKELY, FindingType.AI_FULL_GENERATION_SUSPECTED)
                and not f.advisory_only]


def test_objective_residue_is_not_duplicated_as_an_advisory_ai_finding():
    doc = document("피고는 원고에게 금원을 지급하라.", "도움이 되셨길 바랍니다. [출처: 2]")
    result = _rule_based_ai_detection(doc, [], metadata_indications=False)
    residue_advisories = [f for f in create_ai_detector_findings(doc, result)
                          if (f.confidence_features or {}).get("rule_id") == "AIGEN.SOURCE_TOKEN"]
    assert residue_advisories == []   # 객관적 잔재는 DRAFT_ARTIFACT(AI_RESPONSE_RESIDUE)로 한 번만 싣는다


def test_structured_reasons_accept_objects_and_legacy_strings():
    reasons = _structured_reasons([
        {"kind": "style", "text": "번역투 문장이 반복된다"},
        {"kind": "confirmation", "text": "합계 12,100,000원은 세부 금액과 일치한다"},
        "입원 기간 21일은 날짜 사이 일수와 맞지 않는다",       # 예전 형식: 표현으로 kind 추정
        {"kind": "bogus", "text": "문단 구조가 기계적이다"},
    ])
    assert [r["kind"] for r in reasons] == ["style", "confirmation", "contradiction", "style"]


def _answer(provider, verdict, reasons):
    return SimpleNamespace(used=True, parsed={"verdict": verdict, "ai_score": 0.3, "reasons": reasons},
                           text="", executions=[SimpleNamespace(provider=provider, model="m")])


def test_confirmation_is_neither_ai_evidence_nor_a_fact_remark():
    rule = AIDetectorResult(verdict="UNCERTAIN", score=0.1, reasons=[], signals={"objective_traces": 0})
    combined = _combine_model_verdicts(rule, [
        _answer("a", "UNCERTAIN", [{"kind": "confirmation", "text": "합계 금액은 세부 금액의 합과 일치한다"},
                                   {"kind": "contradiction", "text": "합계 12,700,000원이 세부 금액 합산과 다르다"}]),
        _answer("b", "UNCERTAIN", [{"kind": "style", "text": "문체가 균일하다"}]),
    ], "본문")
    assert all("일치한다" not in r for r in combined.reasons)
    assert combined.signals["model_confirmations"] == ["[a] 합계 금액은 세부 금액의 합과 일치한다"]
    remarks = [f for f in create_ai_detector_findings(document("본문"), combined) if f.type == FindingType.MODEL_FACT_REMARK]
    assert len(remarks) == 1 and "12,700,000" in remarks[0].title


@pytest.mark.parametrize("verdict, traces, involvement, scope", [
    ("AI_FULL_GENERATION_LIKELY", 3, "TRACES_FOUND", "WHOLE_DOCUMENT"),
    ("AI_PARTIAL_GENERATION", 1, "TRACES_FOUND", "PART_OF_DOCUMENT"),
    ("UNCERTAIN", 0, "NO_OBJECTIVE_TRACES", "NOT_APPLICABLE"),
])
def test_involvement_and_scope_are_separate_axes(verdict, traces, involvement, scope):
    doc = SimpleNamespace(document_id="d", authorship=None,
                          ai_detector_result={"verdict": verdict, "score": 0.5, "signals": {"objective_traces": traces}})
    axis = unified_authorship(doc)
    assert (axis["involvement"], axis["scope"]) == (involvement, scope)
