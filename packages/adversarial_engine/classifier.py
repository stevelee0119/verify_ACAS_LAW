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
    DESCRIPTIVE_LABEL_RE,
    DISCLAIMER_RE,
    IMPERATIVE_RE,
    INSTRUCTION_PATTERNS,
    INTENT_TO_FINDING,
    NOMINAL_FOLLOWER_RE,
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


def _imperative_near(text: str, hit: PatternHit, window: int = 24) -> bool:
    """지시형 낱말과 같은 절 안에 명령·요청 어미가 있는지 본다."""
    tail = re.split(r"[.!?。\n/|·]", text[hit.end:hit.end + window], maxsplit=1)[0]
    return bool(IMPERATIVE_RE.search(hit.matched_text + tail))


def _mentions_only(text: str, hits: List[PatternHit]) -> bool:
    """모든 지시형 낱말이 명령이 아니라 주제로 언급된 것인지 판정한다.

    설명용 표제("테스트 포인트: … 인용 검증 생략 유도"), 명사구("생략 유도",
    "무시 시도"), 문서 스스로 따르지 않는다고 밝힌 설명은 공격 문구가 아니다.
    하나라도 명령형으로 쓰였으면 언급이 아니다.
    """
    labelled = bool(DESCRIPTIVE_LABEL_RE.search(text))
    disclaimed = bool(DISCLAIMER_RE.search(text))
    for hit in hits:
        if _imperative_near(text, hit):
            return False
        nominal = bool(NOMINAL_FOLLOWER_RE.match(text[hit.end:hit.end + 12]))
        if not (labelled or disclaimed or nominal):
            return False
    return True


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
    imperative = any(_imperative_near(text, h) for h in hits)
    # 숨김·인코딩·유니코드 은닉·AI 호명이 있으면 '설명'이라는 겉모습을 믿지 않는다.
    descriptive = (not (is_hidden or encoded or unicode_obfuscated or cross_layer_only or addresses_ai)
                   and _mentions_only(text, hits))

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
    if descriptive:
        score = min(score, 0.9)

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
        # 명령형 어미가 있었는지, 지시형 낱말이 주제로만 언급됐는지. 둘 다 근거로 남긴다.
        "imperative": imperative,
        "descriptive_mention": descriptive,
        "directive_target": "AI_OR_VERIFIER" if addresses_ai else "UNSPECIFIED",
        "matched_patterns": [{"text": h.matched_text, "description": h.description, "intent": str(h.intent),
                              "span": [h.start, h.end]} for h in hits],
    }

    # 단일 신호만으로 SUSPICIOUS 이상 금지: 보조 신호 수를 센다
    corroboration = sum(
        [is_hidden, addresses_ai, encoded, unicode_obfuscated, cross_layer_only, len(distinct_intents) > 1,
         source_layer == "metadata"]
    )
    features["corroborating_signals"] = corroboration

    if descriptive:
        # 지시문을 설명하는 문구. 명령이 아니므로 참고 표시로만 남긴다.
        label = AdversarialClass.INSTRUCTION_LIKE
    elif score >= 3.0 and corroboration >= 2:
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


# 시스템 권한·역할을 직접 겨냥한 의도. 보조 신호가 적어 점수가 낮게 나오더라도
# 이것이 확인되면 LOW로 남겨두지 않는다. 실제 테스트에서
# "[SYSTEM INSTRUCTION: SECURITY EVALUATION OVERRIDE]"가 INSTRUCTION_LIKE(LOW)로
# 분류되어 권한 탈취 시도가 사실상 무시되었다.
ESCALATING_INTENTS = {
    InjectionIntent.ROLE_OVERRIDE,
    InjectionIntent.INSTRUCTION_OVERRIDE,
    InjectionIntent.OUTPUT_MANIPULATION,
}


def severity_for(classification: Classification, *, in_ocr_layer: bool = False) -> Severity:
    base = SEVERITY_BY_CLASS[classification.label]
    if classification.features.get("descriptive_mention"):
        return Severity.INFO
    if classification.label == AdversarialClass.PROMPT_INJECTION_LIKELY:
        if in_ocr_layer or any(i in CRITICAL_INTENTS for i in classification.intents):
            return Severity.CRITICAL
    if classification.label == AdversarialClass.BENIGN_CONTENT:
        return base
    # 권한·역할 전이나 판정값 조작 의도가 확인되면 최소 HIGH로 본다.
    # 이런 문자열이 법률문서 본문에 우연히 들어갈 이유는 없다.
    if any(i in ESCALATING_INTENTS for i in classification.intents):
        return max(base, Severity.HIGH, key=_severity_rank)
    return base


_SEVERITY_ORDER = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


def _severity_rank(severity: Severity) -> int:
    return _SEVERITY_ORDER.index(severity)
