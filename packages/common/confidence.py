"""제16.4장 Confidence.

Confidence는 법적 확률이 아니다. feature를 그대로 저장하고,
Benchmark가 충분해지기 전에는 rule-based score만 제공한다.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

# feature 이름 -> (가중치, 설명)
FEATURE_WEIGHTS: Dict[str, Tuple[float, str]] = {
    "official_source_match": (0.35, "공식 Source에서 동일 항목 확인"),
    "official_source_absent": (-0.20, "공식 Source에서 확인 실패"),
    "cryptographic_evidence": (0.30, "해시·전자서명 등 암호학적 확인"),
    "metadata_match": (0.15, "사건번호·법원·선고일 등 메타데이터 일치"),
    "metadata_mismatch": (0.20, "메타데이터 불일치가 결정론적으로 확인"),
    "quote_match": (0.15, "직접 인용문 문자열 일치"),
    "quote_mismatch": (0.18, "직접 인용문 불일치가 결정론적으로 확인"),
    "deterministic_rule": (0.30, "결정론적 규칙으로 관찰"),
    "arithmetic_proof": (0.35, "Python 계산엔진 검산"),
    "source_count": (0.08, "교차 확인 Source 수(개당)"),
    "model_agreement": (0.08, "모델 간 의견 일치"),
    "critic_objection": (-0.15, "독립 Critic의 반증"),
    "forensic_signal": (0.10, "포렌식 신호(개당)"),
    "cross_layer_mismatch": (0.22, "레이어 간 불일치 확인"),
    "heuristic_only": (-0.12, "휴리스틱 추정에만 의존"),
    "single_model_opinion": (-0.10, "단일 모델 의견"),
    "llm_semantic_signal": (0.06, "LLM 의미분석 신호"),
}

BASE_SCORE = 0.30
MIN_SCORE = 0.05
MAX_SCORE = 0.99


def score(features: Dict[str, Any]) -> float:
    """feature dict를 rule-based confidence로 환산한다.

    bool feature는 1/0으로, 숫자 feature는 개수로 취급한다.
    """
    total = BASE_SCORE
    for key, value in features.items():
        if key not in FEATURE_WEIGHTS:
            continue
        weight, _ = FEATURE_WEIGHTS[key]
        if isinstance(value, bool):
            total += weight if value else 0.0
        elif isinstance(value, (int, float)):
            capped = min(float(value), 4.0)
            total += weight * capped
    return round(max(MIN_SCORE, min(MAX_SCORE, total)), 4)


def explain(features: Dict[str, Any]) -> Dict[str, Any]:
    """보고서에 표기할 feature 설명."""
    used = {}
    for key, value in features.items():
        if key in FEATURE_WEIGHTS:
            used[key] = {"value": value, "weight": FEATURE_WEIGHTS[key][0], "note": FEATURE_WEIGHTS[key][1]}
        else:
            used[key] = {"value": value, "weight": 0.0, "note": "score 미반영 참고 feature"}
    return {"features": used, "score": score(features), "method": "rule_based_v1"}
