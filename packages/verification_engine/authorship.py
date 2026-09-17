"""제13장 AI 작성 여부 및 모델 Attribution.

확정판정이 아니라 확률적·증거단계별 분석으로 제공하며 ABSTAIN을 허용한다.
AI 탐지점수가 높다는 이유만으로 'AI가 작성했다'고 확정하지 않는다(부록 C 제5항).
문체 유사성만으로 특정 제품이 작성했다고 확정하지 않는다(제13.2장).
"""
from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    AttributionLevel,
    AuthorshipVerdict,
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import AuthorshipAssessment, Evidence, Finding, NormalizedDocument
from packages.common.textutil import sentences

ENGINE_NAME = "verification_engine.authorship"

# Provenance: 생성 metadata에 남는 대표 서명 (제13.1장, C2PA 포함)
GENERATOR_METADATA_RE = re.compile(
    r"(chatgpt|openai|gpt-[45]|claude|anthropic|gemini|bard|copilot|llama|mistral|"
    r"stable\s*diffusion|midjourney|c2pa|content\s*credentials)",
    re.IGNORECASE,
)

# 구조적 특징: 기계 생성 문서에서 자주 보이는 형식 (단독으로는 근거가 되지 않는다)
STRUCTURAL_MARKERS = [
    re.compile(r"^\s*(?:첫째|둘째|셋째|넷째)[,.]", re.MULTILINE),
    re.compile(r"^\s*\d+\.\s+\*\*", re.MULTILINE),
    re.compile(r"(결론적으로|요약하면|종합하면|정리하자면)", re.IGNORECASE),
    re.compile(r"(다음과 같은 (?:점|측면|이유)(?:들)?이 있습니다)"),
]

MIN_SENTENCES_FOR_ANALYSIS = 12


def analyze_authorship(doc: NormalizedDocument) -> AuthorshipAssessment:
    text = doc.visible_text
    sents = sentences(text)
    signals: Dict[str, Any] = {}
    notes: List[str] = []

    # 1) Provenance — 가장 강한 객관적 흔적
    metadata_blob = " ".join(f"{k}={v}" for k, v in doc.metadata.items())
    provenance_hits = sorted(set(m.group(0).lower() for m in GENERATOR_METADATA_RE.finditer(metadata_blob)))
    signals["provenance_metadata"] = provenance_hits
    signals["has_c2pa"] = bool(doc.structure.get("c2pa"))

    # 2) Stylometry
    if len(sents) >= MIN_SENTENCES_FOR_ANALYSIS:
        lengths = [len(s) for s in sents]
        mean_length = statistics.mean(lengths)
        stdev_length = statistics.pstdev(lengths)
        cv = stdev_length / mean_length if mean_length else 0.0
        words = re.findall(r"[가-힣A-Za-z]+", text)
        ttr = len(set(words)) / len(words) if words else 0.0
        signals["sentence_count"] = len(sents)
        signals["mean_sentence_length"] = round(mean_length, 2)
        signals["sentence_length_cv"] = round(cv, 3)
        signals["type_token_ratio"] = round(ttr, 3)
    else:
        notes.append(f"문장이 {len(sents)}개로 통계 분석에 충분하지 않다. 판단을 유보한다.")

    # 3) Structural features
    structural = sum(1 for pattern in STRUCTURAL_MARKERS if pattern.search(text))
    signals["structural_markers"] = structural

    # 4) 문체 변화 (Style Shift)
    shift = _style_shift(sents)
    signals["style_shift"] = shift

    # --- 종합 -------------------------------------------------------------
    if provenance_hits or signals["has_c2pa"]:
        return AuthorshipAssessment(
            verdict=AuthorshipVerdict.AI_LIKELY,
            score=0.9,
            signals=signals,
            attribution=AttributionLevel.PROVEN if signals["has_c2pa"] else AttributionLevel.STRONG_INDICATION,
            attributed_model=provenance_hits[0] if provenance_hits else None,
            notes=notes
            + [
                "생성 metadata 또는 provenance에 기반한 판단이다. "
                "다만 metadata는 편집될 수 있으므로 원본 확인이 필요하다."
            ],
        )

    if len(sents) < MIN_SENTENCES_FOR_ANALYSIS:
        return AuthorshipAssessment(
            verdict=AuthorshipVerdict.ABSTAIN,
            score=0.0,
            signals=signals,
            attribution=AttributionLevel.UNDETERMINED,
            notes=notes + ["분량 부족으로 판단을 유보한다(ABSTAIN)."],
        )

    score = 0.0
    cv = signals.get("sentence_length_cv", 0.5)
    if cv < 0.30:
        score += 0.25  # 문장 길이가 지나치게 균일
    if structural >= 2:
        score += 0.20
    ttr = signals.get("type_token_ratio", 0.5)
    if ttr < 0.35:
        score += 0.10
    if shift.get("detected"):
        score += 0.10

    if score >= 0.5:
        verdict = AuthorshipVerdict.AI_LIKELY
    elif score <= 0.15:
        verdict = AuthorshipVerdict.HUMAN_LIKELY
    else:
        verdict = AuthorshipVerdict.UNCERTAIN

    notes.append(
        "문체·구조 통계에 기반한 확률적 추정이다. 특정 AI 제품이 작성했다고 확정할 수 없으며, "
        "AI 작성 여부에 관한 최종 판단은 사용자에게 있다."
    )
    return AuthorshipAssessment(
        verdict=verdict,
        score=round(score, 3),
        signals=signals,
        attribution=AttributionLevel.UNDETERMINED,
        notes=notes,
        segment_verdicts=_segment_verdicts(doc),
    )


def _style_shift(sents: List[str]) -> Dict[str, Any]:
    """문서 내 문체 급변 구간을 찾는다(제13.1장 Structural Feature)."""
    if len(sents) < 10:
        return {"detected": False}
    half = len(sents) // 2
    first = [len(s) for s in sents[:half]]
    second = [len(s) for s in sents[half:]]
    mean_first, mean_second = statistics.mean(first), statistics.mean(second)
    if not mean_first:
        return {"detected": False}
    ratio = abs(mean_second - mean_first) / mean_first
    return {
        "detected": ratio > 0.6,
        "first_half_mean": round(mean_first, 1),
        "second_half_mean": round(mean_second, 1),
        "ratio": round(ratio, 3),
    }


def _segment_verdicts(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """문단 단위 표시(제13장). 짧은 문단은 판단을 유보한다."""
    out: List[Dict[str, Any]] = []
    for block in doc.body_blocks():
        sents = sentences(block.text)
        if len(sents) < 3:
            out.append({"block_id": block.block_id, "page": block.page, "verdict": str(AuthorshipVerdict.ABSTAIN)})
            continue
        lengths = [len(s) for s in sents]
        cv = statistics.pstdev(lengths) / statistics.mean(lengths) if statistics.mean(lengths) else 1.0
        verdict = AuthorshipVerdict.AI_LIKELY if cv < 0.25 else AuthorshipVerdict.UNCERTAIN
        out.append(
            {
                "block_id": block.block_id,
                "page": block.page,
                "verdict": str(verdict),
                "sentence_length_cv": round(cv, 3),
            }
        )
    return out


def authorship_findings(doc: NormalizedDocument, assessment: AuthorshipAssessment) -> List[Finding]:
    findings: List[Finding] = []
    if assessment.verdict == AuthorshipVerdict.AI_LIKELY:
        provenance = bool(assessment.signals.get("provenance_metadata") or assessment.signals.get("has_c2pa"))
        features = {
            "heuristic_only": not provenance,
            "forensic_signal": 1 if provenance else 0,
            "deterministic_rule": provenance,
            **{k: v for k, v in assessment.signals.items() if isinstance(v, (int, float, bool, str))},
        }
        findings.append(
            Finding.create(
                type=FindingType.AI_AUTHORSHIP_LIKELY,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.INFO if not provenance else Severity.LOW,
                evidence_grade=EvidenceGrade.A if provenance else EvidenceGrade.D,
                title=f"AI 작성 가능성 신호 (score={assessment.score})",
                detail=" ".join(assessment.notes),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                tags=["AUTHORSHIP"],
                evidence=[
                    Evidence.create(
                        description="분석 신호",
                        grade=EvidenceGrade.A if provenance else EvidenceGrade.D,
                        document_id=doc.document_id,
                        excerpt=str(assessment.signals)[:400],
                    )
                ],
            )
        )
    shift = assessment.signals.get("style_shift") or {}
    if shift.get("detected"):
        features = {"heuristic_only": True, "style_shift_ratio": shift.get("ratio")}
        findings.append(
            Finding.create(
                type=FindingType.STYLE_SHIFT,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.INFO,
                evidence_grade=EvidenceGrade.D,
                title="문서 전·후반의 문체 특성이 크게 다르다",
                detail=(
                    f"전반부 평균 문장길이 {shift.get('first_half_mean')}자, 후반부 {shift.get('second_half_mean')}자. "
                    "여러 작성자 또는 재사용 문단의 가능성을 시사하는 참고정보이며 단정 근거가 아니다."
                ),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                tags=["AUTHORSHIP"],
            )
        )
    return findings
