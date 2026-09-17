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
    #
    # 문서 속성의 AI 표기는 "AI 관련 문자열이 존재한다"는 사실일 뿐이다.
    # 속성은 누구나 편집할 수 있으므로 그것으로 작성 주체를 확정하지 않는다.
    # C2PA 후보를 발견한 것도 검증이 아니다. 서명·자산 결합을 확인하는 검증기가
    # 없는 상태에서 PROVEN을 주면, 작성자 칸에 이름을 적어 넣은 문서가
    # 암호학적으로 증명된 것처럼 보고된다.
    # 범위별 판정은 forensic_engine.ai_provenance가 담당한다.
    if provenance_hits or signals["has_c2pa"]:
        return AuthorshipAssessment(
            verdict=AuthorshipVerdict.ABSTAIN,
            score=0.0,
            signals=signals,
            attribution=AttributionLevel.WEAK_INDICATION,
            attributed_model=None,
            notes=notes
            + [
                "문서 속성 또는 출처 기록 후보에 AI 관련 표기가 있다. 속성은 편집할 수 있고 "
                "출처 기록의 서명·자산 결합은 검증하지 않았으므로, 표기의 존재만 사실로 남기고 "
                "작성 주체는 판단하지 않는다(설계서 제8.1장 미검증 표기).",
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

    # 문체 통계는 판정에 쓰지 않는다(설계서 제8.4장).
    #
    # 종전에는 score >= 0.5면 AI_LIKELY, <= 0.15면 HUMAN_LIKELY를 냈다. 둘 다
    # 문제가 있다. 문장 길이 변동계수와 어휘 다양도는 장르·번역·교정·OCR에 따라
    # 크게 흔들리고, 한국어 법률문서에 대해 검증된 임계값이 아니다.
    # 특히 HUMAN_LIKELY는 "흔적이 없다"를 "사람이 썼다"로 바꾸는 것이어서
    # 잘못된 안심을 준다(제1.1장). AI가 쓴 글을 사람이 붙여 넣으면 파일에는
    # 아무 기록도 남지 않는다.
    #
    # 지표는 근거로 계속 보관하되, 사용자 판정은 판단 보류로 둔다.
    signals["stylometry_score"] = round(score, 3)
    signals["stylometry_is_advisory_only"] = True
    verdict = AuthorshipVerdict.UNCERTAIN

    notes.append(
        "문체·구조 통계는 참고 지표로만 싣는다. 장르·번역·교정·OCR에 따라 크게 달라지므로 "
        "이것만으로 AI 작성 여부를 판정하지 않으며, 흔적이 없다는 것을 사람이 작성했다는 "
        "근거로도 쓰지 않는다. 작성 주체에 관한 판단은 검증된 출처 기록이 있을 때에만 가능하다."
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


MIN_SENTENCES_PER_SEGMENT = 3


def _paragraph_units(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """줄 블록을 문단 단위로 묶는다.

    PDF 파서는 시각적 '줄'을 블록으로 만든다. 한 줄에 문장이 3개 들어갈 일은
    거의 없으므로, 줄을 그대로 문단으로 보면 모든 구간이 분량 부족으로
    ABSTAIN이 된다. 실제 검증보고서에서 95개 블록이 전부 ABSTAIN이었던 원인이다.

    같은 페이지의 연속된 줄을 문장 수가 기준에 찰 때까지 이어 붙인다.
    """
    units: List[Dict[str, Any]] = []
    current: List[Any] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(b.text.strip() for b in current if b.text.strip())
        if text:
            units.append(
                {
                    "block_id": current[0].block_id,
                    "block_ids": [b.block_id for b in current],
                    "page": current[0].page,
                    "text": text,
                }
            )
        current.clear()

    for block in doc.prose_blocks():
        if current and block.page != current[0].page:
            flush()
        current.append(block)
        if len(sentences(" ".join(b.text for b in current))) >= MIN_SENTENCES_PER_SEGMENT:
            flush()
    flush()
    return units


def _segment_verdicts(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """문단 단위 표시(제13장). 짧은 문단은 판단을 유보한다."""
    out: List[Dict[str, Any]] = []
    for unit in _paragraph_units(doc):
        sents = sentences(unit["text"])
        if len(sents) < MIN_SENTENCES_PER_SEGMENT:
            out.append({
                "block_id": unit["block_id"], "block_ids": unit["block_ids"],
                "page": unit["page"], "verdict": str(AuthorshipVerdict.ABSTAIN),
                "reason": f"문장 {len(sents)}개로 분량이 부족하다",
            })
            continue
        lengths = [len(s) for s in sents]
        cv = statistics.pstdev(lengths) / statistics.mean(lengths) if statistics.mean(lengths) else 1.0
        # 문단 단위로 AI를 지목하지 않는다(제8.3장). 강한 범위 식별 없이
        # 특정 문단을 AI 작성으로 표시하면 근거 없는 지목이 된다.
        verdict = AuthorshipVerdict.UNCERTAIN
        out.append(
            {
                "block_id": unit["block_id"],
                "block_ids": unit["block_ids"],
                "page": unit["page"],
                "verdict": str(verdict),
                "sentence_count": len(sents),
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
