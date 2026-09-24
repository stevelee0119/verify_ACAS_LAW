"""AI 작성 판별에서 모델마다 낸 결론과 설명을 보고서 표로 만든다.

최종 판정만 싣으면 세 모델 가운데 누가 어떤 근거로 무엇이라 했는지, 누가 왜
빠졌는지를 보고서만 보고는 알 수 없다.
"""
from __future__ import annotations

import re
from typing import Any, List

PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini"}
VERDICT_LABELS = {
    "AI_FULL_GENERATION_LIKELY": "AI 임의 전체 작성 유력",
    "AI_PARTIAL_GENERATION": "일부 AI 작성·인용",
    "HUMAN_AUTHORED_LIKELY": "사람 작성 유력",
    "UNCERTAIN": "판단 보류",
}


def model_display_name(model: str) -> str:
    """모델 ID를 사람이 읽는 이름으로 바꾼다. 모르는 형식은 ID 그대로 둔다.

    claude-opus-5-5 → Claude Opus 5.5, gemini-3.8-flash → Gemini 3.8 Flash,
    gpt-6-luna → GPT-6 Luna, gpt-5.6 → GPT-5.6
    """
    model = str(model or "")
    claude = re.fullmatch(r"claude-(opus|sonnet|haiku)-(\d+)(?:-(\d))?(?:-\d{8})?", model)
    if claude:
        family, major, minor = claude.groups()
        return f"Claude {family.title()} {major}{'.' + minor if minor else ''}"
    gemini = re.fullmatch(r"gemini-([\d.]+)-(flash|pro)(-lite)?(-preview)?", model)
    if gemini:
        version, tier, lite, preview = gemini.groups()
        return f"Gemini {version} {tier.title()}{' Lite' if lite else ''}{' Preview' if preview else ''}"
    gpt = re.fullmatch(r"gpt-([\d.]+)(?:-([a-z]+))?", model)
    if gpt:
        version, variant = gpt.groups()
        return f"GPT-{version}{' ' + variant.title() if variant else ''}"
    return model


def model_label(provider: str, model: str) -> str:
    """'Anthropic · Claude Opus 5.5 (claude-opus-5-5)'. 이름과 ID가 같으면 ID는 생략한다."""
    name = model_display_name(model)
    head = PROVIDER_NAMES.get(provider, provider)
    if not model:
        return head
    return f"{head} · {name}" + (f" ({model})" if name != model else "")


def model_opinion_rows(documents: List[Any]) -> List[List[str]]:
    """[문서, 모델, 판정, 점수, 근거] 행. 응답하지 못한 모델은 사유를 근거 칸에 적는다."""
    rows: List[List[str]] = []
    for document in documents:
        signals = (getattr(document, "ai_detector_result", {}) or {}).get("signals") or {}
        name = getattr(document, "filename", "")
        for opinion in signals.get("llm_opinions") or []:
            rows.append([name, model_label(opinion.get("provider", ""), opinion.get("model", "")),
                         VERDICT_LABELS.get(opinion.get("verdict"), str(opinion.get("verdict", ""))),
                         f"{float(opinion.get('score') or 0):.2f}",
                         "\n".join(f"- {reason}" for reason in opinion.get("reasons") or []) or "설명 없음"])
        failure_models = signals.get("llm_failure_models") or {}
        for provider, why in (signals.get("llm_failures") or {}).items():
            rows.append([name, model_label(provider, failure_models.get(provider, "")), "응답 없음", "-", str(why)])
    return rows
