"""AI 작성 문서 판정의 다수결 규칙 시험(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-11.

사용자 결정(2026-09-30): 문서 판정은 모델 의견의 만장일치가 아니라 다수결로 정한다.
규칙: 응답한 모델 n개 중 AI 표(FULL + PARTIAL)가 과반이면 AI 쪽, FULL 표가 과반이면 FULL 아니면 PARTIAL.
n=1은 규칙 판정으로 상한(현행 유지). 사람 작성 의견은 UNCERTAIN으로 센다(현행 유지).
객관적 작성 흔적이 없는 경우(`objective_traces: 0`)를 기본 조건으로 잰다. 흔적 부재가 판정을 막지 않는 것이 이번 해석이다(TK-11 '해석').

TK-11은 2026-10-01 cf7c739에서 해결되었다(xfail 표시 제거). 이제 일반 회귀 시험이다.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

FULL, PARTIAL, UNC, HUMAN = ("AI_FULL_GENERATION_LIKELY", "AI_PARTIAL_GENERATION", "UNCERTAIN", "HUMAN_AUTHORED_LIKELY")
TICKET = "TK-11"


def _answers(*verdicts):
    return [SimpleNamespace(used=True, text="",
                            parsed={"verdict": v, "ai_score": 0.85, "reasons": [{"kind": "style", "text": "정형 요약"}],
                                    "suspicious_excerpts": []},
                            executions=[SimpleNamespace(provider=f"m{i}", model=f"m{i}")])
            for i, v in enumerate(verdicts)]


def _combine(*verdicts, traces=0):
    from packages.verification_engine.ai_document_detector import AIDetectorResult, _combine_model_verdicts

    rule = AIDetectorResult(verdict="UNCERTAIN", score=0.1, reasons=[], signals={"objective_traces": traces})
    return _combine_model_verdicts(rule, _answers(*verdicts), "본문")


OPEN = pytest.mark.skipif(False, reason="TK-11은 2026-10-01 cf7c739에서 해결되어 xfail 표시를 지웠다")  # 표시 자리만 남김(제거해도 같다)

CASES = [
    # (id, 모델 의견, 기대 판정, 미해결 여부)
    ("full-full-partial", (FULL, FULL, PARTIAL), FULL, True),          # 서면7 모양: 모두 AI 쪽, FULL이 과반
    ("partial-partial-full", (PARTIAL, PARTIAL, FULL), PARTIAL, True),  # 모두 AI 쪽, FULL은 과반 아님
    ("full-partial-unc", (FULL, PARTIAL, UNC), PARTIAL, True),          # AI 2/3 과반, FULL 1/3
    ("full-full-unc", (FULL, FULL, UNC), FULL, True),                   # AI 2/3, FULL 2/3
    ("full-full-full", (FULL, FULL, FULL), FULL, True),                 # 만장일치여도 흔적 없으면 지금은 유보
    ("full-full-two-models", (FULL, FULL), FULL, True),                 # n=2는 둘 다 AI
    ("full-unc-unc", (FULL, UNC, UNC), UNC, False),                     # AI 1/3: 과반 아님
    ("unc-unc-unc", (UNC, UNC, UNC), UNC, False),
    ("full-unc-two-models", (FULL, UNC), UNC, False),                   # n=2 갈림: 과반 아님
    ("four-models-half", (FULL, FULL, UNC, UNC), UNC, False),           # 2/4는 과반(2 초과) 아님
    ("human-human-full", (HUMAN, HUMAN, FULL), UNC, False),             # 사람 작성 의견은 UNCERTAIN으로 센다
    ("four-models-majority", (FULL, FULL, FULL, UNC), FULL, True),      # 3/4
]


@pytest.mark.parametrize("opinions, expected", [
    pytest.param(o, e, id=i, marks=[OPEN] if open_ else [])
    for i, o, e, open_ in CASES])
def test_majority_verdict(opinions, expected):
    assert _combine(*opinions).verdict == expected


def test_single_model_is_capped_by_the_rule_verdict():
    """n=1은 현행 유지: 모델 하나의 AI 의견만으로 판정하지 않는다."""
    assert _combine(FULL).verdict == "UNCERTAIN"


@OPEN
def test_majority_outcome_is_labelled_and_safeguards_stay_visible():
    combined = _combine(FULL, FULL, PARTIAL)
    signals = combined.signals
    assert str(signals["decision_rule"]).startswith("MAJORITY")
    # 안전장치는 판정과 별도 축으로 남는다: 표 분포와 객관적 흔적 수
    assert signals["verdict_distribution"][FULL] == 2 and signals["verdict_distribution"][PARTIAL] == 1
    assert signals["objective_traces"] == 0


def test_held_outcomes_keep_a_held_rule_name():
    assert str(_combine(FULL, UNC, UNC).signals["decision_rule"]).startswith(("HELD_", "AGREED_"))


def test_objective_traces_do_not_change_a_majority_result():
    """흔적이 있는 조건에서도 같은 다수결 결과여야 한다(흔적은 별도 축). 흔적 없는 조건은 위 매개변수화 시험이 잰다."""
    assert _combine(FULL, FULL, PARTIAL, traces=3).verdict == FULL
    assert _combine(FULL, UNC, UNC, traces=3).verdict == UNC


# ---- TK-18: 보고서 머리 축(unified_authorship)이 다수결 판정을 따라야 한다 -------------------------------------
# 사용자 온라인 보고서(서면8, main cf7c739)에서 detector.verdict는 AI_PARTIAL_GENERATION(다수결)이고 MEDIUM finding도 올랐는데,
# scores.axes.ai_authorship.documents[0].verdict는 UNCERTAIN으로 나왔다. scoring.py의 unified_authorship에 옛 규칙
# ("객관적 흔적 0건이면 UNCERTAIN")이 남아 있기 때문이다. 같은 정책이 두 곳에 있었고 한 곳만 고쳤다.
def _axis(verdict, traces):
    from packages.verification_engine.scoring import unified_authorship

    doc = SimpleNamespace(document_id="d", authorship=None,
                          ai_detector_result={"verdict": verdict, "score": 0.72, "signals": {"objective_traces": traces}})
    return unified_authorship(doc)


@pytest.mark.parametrize("verdict", [FULL, PARTIAL])
def test_axis_follows_majority_verdict_without_traces(verdict):
    assert _axis(verdict, 0)["verdict"] == verdict


@pytest.mark.parametrize("verdict, traces", [(FULL, 3), (PARTIAL, 1), (UNC, 0)])
def test_axis_unchanged_where_it_already_agreed(verdict, traces):
    assert _axis(verdict, traces)["verdict"] == verdict


def test_axis_keeps_involvement_separate_from_verdict():
    axis = _axis(PARTIAL, 0)
    assert axis["involvement"] == "NO_OBJECTIVE_TRACES" and axis["objective_traces"] == 0
