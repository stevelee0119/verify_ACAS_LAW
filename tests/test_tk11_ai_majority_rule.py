"""TK-11 AI 작성 판정 다수결 규칙 단위 테스트.

규칙:
1. 응답 모델 n개 중 AI 표(FULL + PARTIAL)가 과반(n/2 초과)이면 AI 판정, 아니면 UNCERTAIN.
2. AI 판정일 때 FULL 표가 과반이면 AI_FULL_GENERATION_LIKELY, 아니면 AI_PARTIAL_GENERATION.
3. n=1은 규칙 판정 상한 유지 (모델 단독 확정 방지).
4. n=2는 둘 다 AI여야 AI 확정.
5. 객관적 흔적(objective_traces) 부재는 다수결 판정을 차단하지 않는다.
"""
from types import SimpleNamespace
import pytest

from packages.verification_engine.ai_document_detector import AIDetectorResult, _combine_model_verdicts

FULL = "AI_FULL_GENERATION_LIKELY"
PARTIAL = "AI_PARTIAL_GENERATION"
UNC = "UNCERTAIN"
HUMAN = "HUMAN_AUTHORED_LIKELY"


def _answers(*verdicts):
    return [
        SimpleNamespace(
            used=True,
            text="",
            parsed={
                "verdict": v,
                "ai_score": 0.85,
                "reasons": [{"kind": "style", "text": "정형화된 문체"}],
                "suspicious_excerpts": [],
            },
            executions=[SimpleNamespace(provider=f"model_{i}", model=f"m{i}")],
        )
        for i, v in enumerate(verdicts)
    ]


def _combine(*verdicts, traces=0):
    rule = AIDetectorResult(
        verdict="UNCERTAIN",
        score=0.1,
        reasons=[],
        signals={"objective_traces": traces},
    )
    return _combine_model_verdicts(rule, _answers(*verdicts), "샘플 본문 텍스트입니다.")


# ── 1. 양성 테스트 (다수결로 AI 판정 확정) ────────────────────────────────

class TestMajorityPositive:
    """AI 표가 과반을 넘어 AI 판정으로 확정되는 경우."""

    def test_full_majority_three_models(self):
        """3개 모델 중 FULL 2표, PARTIAL 1표 → FULL 확정 (서면7 유형)."""
        res = _combine(FULL, FULL, PARTIAL, traces=0)
        assert res.verdict == FULL
        assert str(res.signals["decision_rule"]).startswith("MAJORITY")
        assert res.signals["verdict_distribution"][FULL] == 2
        assert res.signals["verdict_distribution"][PARTIAL] == 1

    def test_partial_majority_three_models(self):
        """3개 모델 중 PARTIAL 2표, FULL 1표 → PARTIAL 확정."""
        res = _combine(PARTIAL, PARTIAL, FULL, traces=0)
        assert res.verdict == PARTIAL
        assert str(res.signals["decision_rule"]).startswith("MAJORITY")

    def test_full_and_partial_against_unc(self):
        """3개 모델 중 FULL 1표, PARTIAL 1표, UNC 1표 → AI 표 2/3 과반, FULL 1/3 과반 미달 → PARTIAL 확정."""
        res = _combine(FULL, PARTIAL, UNC, traces=0)
        assert res.verdict == PARTIAL
        assert str(res.signals["decision_rule"]).startswith("MAJORITY")

    def test_full_unanimous_without_traces(self):
        """3개 모델 모두 FULL 만장일치 + 흔적 0 → 다수결에 따라 FULL 확정."""
        res = _combine(FULL, FULL, FULL, traces=0)
        assert res.verdict == FULL
        assert str(res.signals["decision_rule"]).startswith("MAJORITY")

    def test_two_models_both_full(self):
        """2개 모델 모두 FULL → 둘 다 AI이므로 FULL 확정."""
        res = _combine(FULL, FULL, traces=0)
        assert res.verdict == FULL
        assert str(res.signals["decision_rule"]).startswith("MAJORITY")


# ── 2. 대조군 테스트 (과반 미달 또는 단일 모델로 UNCERTAIN 유지) ─────────

class TestMajorityNegativeControls:
    """과반 미달, 동수, 단일 모델 상한 등으로 UNCERTAIN이 유지되는 경우."""

    def test_single_model_capped_by_rule(self):
        """1개 모델만 FULL 지목 → 단일 모델 상한(규칙 결과 UNCERTAIN) 유지."""
        res = _combine(FULL, traces=0)
        assert res.verdict == UNC
        assert res.signals["decision_rule"] == "SINGLE_MODEL_CAPPED_BY_RULES"

    def test_two_models_split(self):
        """2개 모델 중 1개 FULL, 1개 UNC → 과반(2/2) 미달이므로 UNCERTAIN."""
        res = _combine(FULL, UNC, traces=0)
        assert res.verdict == UNC
        assert res.signals["decision_rule"] == "HELD_DISAGREEMENT"

    def test_four_models_half_split(self):
        """4개 모델 중 2개 FULL, 2개 UNC → 2/4는 과반(2 초과)이 아니므로 UNCERTAIN."""
        res = _combine(FULL, FULL, UNC, UNC, traces=0)
        assert res.verdict == UNC
        assert res.signals["decision_rule"] == "HELD_DISAGREEMENT"

    def test_minority_ai_in_three_models(self):
        """3개 모델 중 1개 FULL, 2개 UNC → AI 표 1/3 과반 미달이므로 UNCERTAIN."""
        res = _combine(FULL, UNC, UNC, traces=0)
        assert res.verdict == UNC
        assert res.signals["decision_rule"] == "HELD_DISAGREEMENT"

    def test_human_opinion_counted_as_uncertain(self):
        """HUMAN 2표, FULL 1표 → HUMAN은 UNCERTAIN으로 변환되므로 AI 1/3 과반 미달 → UNCERTAIN."""
        res = _combine(HUMAN, HUMAN, FULL, traces=0)
        assert res.verdict == UNC
        assert res.signals["decision_rule"] == "HELD_DISAGREEMENT"


# ── 3. 안전장치 및 신호 무결성 검증 ────────────────────────────────────

class TestSafeguardsAndSignals:
    """다수결 판정과 별도 축으로 안전장치 신호가 보존되는지 검증."""

    def test_objective_traces_preserved_as_independent_axis(self):
        """객관적 흔적 수는 다수결 결과와 무관하게 신호에 정확히 기록된다."""
        res_zero = _combine(FULL, FULL, PARTIAL, traces=0)
        assert res_zero.signals["objective_traces"] == 0
        assert res_zero.verdict == FULL

        res_three = _combine(FULL, FULL, PARTIAL, traces=3)
        assert res_three.signals["objective_traces"] == 3
        assert res_three.verdict == FULL

    def test_verdict_distribution_accurately_recorded(self):
        """각 모델 의견의 분포가 정확히 기록된다."""
        res = _combine(FULL, FULL, PARTIAL, UNC, traces=0)
        dist = res.signals["verdict_distribution"]
        assert dist[FULL] == 2
        assert dist[PARTIAL] == 1
        assert dist[UNC] == 1
