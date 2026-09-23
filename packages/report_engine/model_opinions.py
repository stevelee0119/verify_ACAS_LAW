"""AI 작성 판별에서 모델마다 낸 결론과 설명을 보고서 표로 만든다.

최종 판정만 싣으면 세 모델 가운데 누가 어떤 근거로 무엇이라 했는지, 누가 왜
빠졌는지를 보고서만 보고는 알 수 없다.
"""
from __future__ import annotations

from typing import Any, List

PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini"}
VERDICT_LABELS = {
    "AI_FULL_GENERATION_LIKELY": "AI 임의 전체 작성 유력",
    "AI_PARTIAL_GENERATION": "일부 AI 작성·인용",
    "HUMAN_AUTHORED_LIKELY": "사람 작성 유력",
    "UNCERTAIN": "판단 보류",
}


def model_opinion_rows(documents: List[Any]) -> List[List[str]]:
    """[문서, 모델, 판정, 점수, 근거] 행. 응답하지 못한 모델은 사유를 근거 칸에 적는다."""
    rows: List[List[str]] = []
    for document in documents:
        signals = (getattr(document, "ai_detector_result", {}) or {}).get("signals") or {}
        name = getattr(document, "filename", "")
        for opinion in signals.get("llm_opinions") or []:
            provider = PROVIDER_NAMES.get(opinion.get("provider"), opinion.get("provider", ""))
            rows.append([name, f"{provider} ({opinion.get('model', '')})".replace(" ()", ""),
                         VERDICT_LABELS.get(opinion.get("verdict"), str(opinion.get("verdict", ""))),
                         f"{float(opinion.get('score') or 0):.2f}",
                         "\n".join(f"- {reason}" for reason in opinion.get("reasons") or []) or "설명 없음"])
        for provider, why in (signals.get("llm_failures") or {}).items():
            rows.append([name, PROVIDER_NAMES.get(provider, provider), "응답 없음", "-", str(why)])
    return rows
