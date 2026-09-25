"""'법리적 타당성 검토 및 반박 근거' 칸의 표시 형식.

검토 결과·AI 교차검증 요약·모델별 의견을 한 문단으로 잇지 않고 항목마다 줄을 나눈다. 웹 화면·DOCX·PDF가 같은
구조(reasoning_sections)와 같은 문자열(format_reasoning)을 쓴다.

    타당성 검토 결과 : …
    AI 교차검증 결과 참고 : 3개 모델 의견 불일치 — 직접 검토 필요
      (Anthropic : 부당)
          근거: …
      (OpenAI : 타당)
          근거: …
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

PROVIDER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "gemini": "Gemini"}
REVIEW_LABEL = "타당성 검토 결과"
AI_LABEL = "AI 교차검증 결과 참고"


def provider_name(provider: Any) -> str:
    key = str(provider or "").strip()
    return PROVIDER_NAMES.get(key.lower(), key or "모델")


def reasoning_sections(review: str, ai_label: Optional[str], opinions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """화면이 칸 안을 항목별로 그리는 데 쓰는 구조."""
    return {
        "review": str(review or "").strip(),
        "ai_label": ai_label or "",
        "opinions": [{"provider": o.get("provider"), "name": provider_name(o.get("provider")),
                      "verdict": str(o.get("verdict") or "판단 불가"), "reasoning": str(o.get("reasoning") or "").strip()}
                     for o in opinions or []],
    }


def format_reasoning(review: str, ai_label: Optional[str] = None,
                     opinions: Iterable[Dict[str, Any]] = ()) -> str:
    """항목마다 줄을 나눈 문자열(DOCX·PDF·JSON용)."""
    sections = reasoning_sections(review, ai_label, opinions)
    lines: List[str] = [f"{REVIEW_LABEL} : {sections['review']}"]
    if sections["ai_label"]:
        lines.append(f"{AI_LABEL} : {sections['ai_label']}")
        for opinion in sections["opinions"]:
            lines.append(f"  ({opinion['name']} : {opinion['verdict']})")
            if opinion["reasoning"]:
                lines.append(f"      근거: {opinion['reasoning']}")
    return "\n".join(lines)


def format_counteraction(base: str, checks: Iterable[Dict[str, Any]] = ()) -> str:
    """대응 방안: 기본 대응 뒤에 모델별 확인 사항을 한 줄씩."""
    lines = [str(base or "").strip()]
    items = [c for c in checks or [] if str(c.get("check") or "").strip()]
    if items:
        lines.append("[AI 참고]")
        lines += [f"  ({provider_name(c.get('provider'))}) {str(c['check']).strip()}" for c in items]
    return "\n".join(line for line in lines if line)


def row_reasoning_text(row: Dict[str, Any]) -> str:
    """보고서(DOCX·PDF)에 적을 법리 검토 칸 글. 구조가 있으면 항목별 줄바꿈 형식, 이전 결과는 저장된 글 그대로."""
    sections = row.get("reasoning_sections") or {}
    if sections.get("review"):
        return format_reasoning(sections["review"], sections.get("ai_label"), sections.get("opinions") or [])
    return str(row.get("legal_reasoning") or "")


def row_cell_text(row: Dict[str, Any], limit: Optional[int] = None) -> str:
    """법리 검토 칸 전체: 검토 글 + 빈 줄 + 대응 방안. limit가 있으면 각 부분을 그 길이에서 자른다(PDF 분량 제한)."""
    reasoning, counter = row_reasoning_text(row), str(row.get("recommended_counteraction") or "")
    if limit:
        reasoning = reasoning if len(reasoning) <= limit else reasoning[:limit].rstrip() + " …"
        counter = counter if len(counter) <= limit // 2 else counter[:limit // 2].rstrip() + " …"
    return f"{reasoning}\n\n대응 방안 : {counter}" if counter else reasoning
