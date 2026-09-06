"""제7.4장 Semantic 분류.

법률문서에는 정상적인 명령형·인용문이 많다. 문장 위치, 인용 여부, 화자,
숨김 방식, AI 관련 용어, 앞뒤 문맥을 종합해 4단계로 분류한다.
단일 신호만으로 SUSPICIOUS 이상을 부여하지 않는다(제7-A.8장).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packages.common.enums import AdversarialClass, FindingType, InjectionIntent, Severity

from .patterns import (
    AI_ADDRESSING_RE,
    BENIGN_CONTEXT_RE,
    INSTRUCTION_PATTERNS,
    INTENT_TO_FINDING,
    QUOTE_WRAPPERS,
)


@dataclass
class PatternHit:
    intent: InjectionIntent
    matched_text: str
    description: str
    weight: float
    start: int
    end: int


@dataclass
class Classification:
    label: AdversarialClass
    intents: List[InjectionIntent]
    score: float
    features: Dict[str, Any] = field(default_factory=dict)
    hits: List[PatternHit] = field(default_factory=list)

    @property
    def primary_finding_type(self) -> FindingType:
        if not self.intents:
            return FindingType.META_INSTRUCTION
        return INTENT_TO_FINDING.get(self.intents[0], FindingType.PROMPT_INJECTION_SUSPECTED)


def find_pattern_hits(text: str) -> List[PatternHit]:
    hits: List[PatternHit] = []
    for regex, intent, weight, description in INSTRUCTION_PATTERNS:
        for m in regex.finditer(text):
            hits.append(PatternHit(intent, m.group(0), description, weight, m.start(), m.end()))
    return hits


def _is_quoted(text: str, start: int, end: int) -> bool:
    """인용부호 안의 문장인지 판정한다(정상 인용 오탐 억제)."""
    before = text[max(0, start - 200) : start]
    after = text[end : end + 200]
    for open_q, close_q in QUOTE_WRAPPERS:
        if open_q in before:
            tail = before[before.rfind(open_q) + 1 :]
            if close_q not in tail and close_q in after:
                return True
    return False


CITATION_CONTEXT_RE = re.compile(
    r"(대법원|헌법재판소|고등법원|지방법원|판결|결정|선고|제\s*\d+\s*조|판시|요지|규정한다|규정하고)"
)


def classify(
    text: str,
    *,
    source_layer: str = "visible_text",
    visible: bool = True,
    hidden_reason: Optional[str] = None,
    block_type: str = "paragraph",
    extra_signals: Optional[Dict[str, Any]] = None,
) -> Classification:
    """단일 텍스트 조각을 분류한다."""
    extra_signals = extra_signals or {}
    hits = find_pattern_hits(text)
    if not hits:
        return Classification(
            AdversarialClass.BENIGN_CONTENT,
            [],
            0.0,
            {"pattern_hits": 0, "corroborating_signals": 0, "source_layer": source_layer},
        )

    # feature 수집
    is_hidden = (not visible) or source_layer in ("hidden_text", "metadata", "xml", "annotation") or bool(hidden_reason)
    addresses_ai = bool(AI_ADDRESSING_RE.search(text))
    benign_context = bool(BENIGN_CONTEXT_RE.search(text))
    citation_context = bool(CITATION_CONTEXT_RE.search(text))
    quoted = all(_is_quoted(text, h.start, h.end) for h in hits)
    distinct_intents = list(dict.fromkeys(h.intent for h in hits))
    encoded = bool(extra_signals.get("encoded"))
    unicode_obfuscated = bool(extra_signals.get("unicode_obfuscated"))
    cross_layer_only = bool(extra_signals.get("cross_layer_only"))

    score = sum(h.weight for h in hits)
    if addresses_ai:
        score += 1.2
    if is_hidden:
        score += 1.5
    if encoded:
        score += 1.2
    if unicode_obfuscated:
        score += 1.2
    if cross_layer_only:
        score += 1.0
    if len(distinct_intents) > 1:
        score += 0.6
    if source_layer == "metadata":
        score += 0.6
    if quoted:
        score -= 1.2
    if benign_context and not is_hidden and not addresses_ai:
        score -= 0.8
    if citation_context and not is_hidden and not addresses_ai:
        score -= 0.5

    features = {
        "pattern_hits": len(hits),
        "distinct_intents": [str(i) for i in distinct_intents],
        "is_hidden": is_hidden,
        "hidden_reason": hidden_reason,
        "addresses_ai": addresses_ai,
        "quoted": quoted,
        "benign_legal_context": benign_context,
        "citation_context": citation_context,
        "encoded": encoded,
        "unicode_obfuscated": unicode_obfuscated,
        "cross_layer_only": cross_layer_only,
        "source_layer": source_layer,
        "block_type": block_type,
        "raw_score": round(score, 3),
    }

    # 단일 신호만으로 SUSPICIOUS 이상 금지: 보조 신호 수를 센다
    corroboration = sum(
        [is_hidden, addresses_ai, encoded, unicode_obfuscated, cross_layer_only, len(distinct_intents) > 1,
         source_layer == "metadata"]
    )
    features["corroborating_signals"] = corroboration

    if score >= 3.0 and corroboration >= 2:
        label = AdversarialClass.PROMPT_INJECTION_LIKELY
    elif score >= 2.0 and corroboration >= 1:
        label = AdversarialClass.SUSPICIOUS_META_INSTRUCTION
    elif score >= 0.8:
        label = AdversarialClass.INSTRUCTION_LIKE
    else:
        label = AdversarialClass.BENIGN_CONTENT

    return Classification(label, distinct_intents, round(score, 3), features, hits)


SEVERITY_BY_CLASS = {
    AdversarialClass.PROMPT_INJECTION_LIKELY: Severity.HIGH,
    AdversarialClass.SUSPICIOUS_META_INSTRUCTION: Severity.MEDIUM,
    AdversarialClass.INSTRUCTION_LIKE: Severity.LOW,
    AdversarialClass.BENIGN_CONTENT: Severity.INFO,
}

# 검증흐름을 직접 겨냥한 의도는 CRITICAL로 승격 가능(제16.3장)
CRITICAL_INTENTS = {
    InjectionIntent.VERIFICATION_SUPPRESSION,
    InjectionIntent.DATA_EXFILTRATION,
    InjectionIntent.TOOL_MANIPULATION,
}


def severity_for(classification: Classification, *, in_ocr_layer: bool = False) -> Severity:
    base = SEVERITY_BY_CLASS[classification.label]
    if classification.label == AdversarialClass.PROMPT_INJECTION_LIKELY:
        if in_ocr_layer or any(i in CRITICAL_INTENTS for i in classification.intents):
            return Severity.CRITICAL
    return base
