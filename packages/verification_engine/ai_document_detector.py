"""AI 법률문서 생성 여부 심층 판별 모듈 (제13장 확장).

법률문서(답변서, 소장, 준비서면 등) 전체가 AI(ChatGPT, Gemini 등)에 의해 임의로
작성되었는지, 또는 일부 내용에 AI가 관여하였는지를 메타데이터, 가짜 판례/조문 환각 빈도,
구조적 특징 및 LLM(OpenAI/Gemini) 심층 분석을 결합하여 판정한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.legal_engine.normalize import case_number_possible
from packages.common.enums import (
    EvidenceGrade,
    ExternalAIPolicy,
    FindingType,
    LLMRole,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.common.textutil import sentences
from packages.llm_router import LLMRouter
from packages.llm_router.providers import LLMRequest

ENGINE_NAME = "verification_engine.ai_document_detector"

# AI 챗봇이 생성한 한국어 법률 서면에서 빈번하게 관찰되는 상투적 패턴
CHATBOT_CLICHE_PATTERNS = [
    (re.compile(r"(도움이\s*되었기를\s*바랍니다|추가적인\s*질문이\s*있으시면|언제든\s*문의해\s*주십시오)", re.IGNORECASE), "챗봇 응답 잔재 상투구"),
    (re.compile(r"(AI\s*(어시스턴트|모델|언어모델)|인공지능으로서)", re.IGNORECASE), "AI 자기 정체성 언급 잔재"),
    (re.compile(r"(다음과\s*같은\s*(점|측면|이유|법리)(?:들)?이\s*있습니다)", re.IGNORECASE), "기계적 나열 도입구"),
    (re.compile(r"(요약하자면|종합하자면|결론적으로\s*말씀드리면)", re.IGNORECASE), "전형적 요약 상투구"),
    (re.compile(r"(법률적\s*조언이\s*아니며|전문\s*변호사와\s*상담하시기\s*바랍니다)", re.IGNORECASE), "AI 법률 면책 고지 잔재"),
]


@dataclass
class AIDetectorResult:
    verdict: str  # AI_FULL_GENERATION_LIKELY, AI_PARTIAL_GENERATION, HUMAN_AUTHORED_LIKELY, UNCERTAIN
    score: float  # 0.0 ~ 1.0 (AI 작성 확률/확신도)
    reasons: List[str] = field(default_factory=list)
    suspicious_excerpts: List[Dict[str, Any]] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)
    used_llm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "suspicious_excerpts": self.suspicious_excerpts,
            "signals": self.signals,
            "used_llm": self.used_llm,
        }


def _rule_based_ai_detection(
    doc: NormalizedDocument,
    citation_findings: List[Finding],
    metadata_indications: bool,
) -> AIDetectorResult:
    """LLM이 없을 때 휴리스틱, 가짜 판례 정황, 메타데이터 등을 바탕으로 결정론적 검출 수행."""
    text = doc.visible_text
    sents = sentences(text)
    signals: Dict[str, Any] = {}
    reasons: List[str] = []
    suspicious_excerpts: List[Dict[str, Any]] = []

    score = 0.0

    # 1. 메타데이터 표기
    if metadata_indications:
        score += 0.35
        reasons.append("문서 메타데이터(Producer/Creator 등)에 AI 생성 도구(ChatGPT/Claude/Gemini 등) 표기가 확인됨")

    # 2. 챗봇 상투구 잔재 탐지
    cliche_hits = 0
    for pat, desc in CHATBOT_CLICHE_PATTERNS:
        for m in pat.finditer(text):
            cliche_hits += 1
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            snippet = text[start:end].strip()
            suspicious_excerpts.append({
                "type": "chatbot_cliche",
                "pattern": desc,
                "snippet": snippet,
                "reason": f"AI 챗봇 전형적 관용구 잔재 발견: '{m.group(0)}'",
            })
    if cliche_hits > 0:
        score += min(0.40, cliche_hits * 0.20)
        reasons.append(f"AI 챗봇의 전형적인 관용구/면책/대화형 잔재 문구가 {cliche_hits}건 발견됨")

    # 3. 판례 인용 정황 결합
    #
    # "공식 DB에서 확인하지 못함"과 "그 표기로는 존재할 수 없음"은 증거력이 전혀
    # 다르다. 국가법령정보 판례 DB는 모든 재판을 수록하지 않으므로(미공개 결정,
    # 하급심, 수록범위 밖) 미확인만으로 AI 생성을 추정하면, 실재하는 판례를 제대로
    # 인용한 서면이 "AI 임의 작성"으로 판정된다. 실제로 그런 일이 있었다.
    unconfirmed = [f for f in citation_findings
                   if f.type == FindingType.CASE_NOT_FOUND and f.status == VerificationStatus.NOT_FOUND]
    impossible = [f for f in unconfirmed
                  if (f.confidence_features or {}).get("case_number")
                  and not case_number_possible(str(f.confidence_features["case_number"]))]
    total_case_count = sum(1 for f in citation_findings if "CASE" in f.tags)
    signals["impossible_case_numbers"] = [str(f.confidence_features["case_number"]) for f in impossible]

    if impossible:
        # 있을 수 없는 연도·사건부호. 수록 범위와 무관하게 실재할 수 없다.
        score += 0.30 if len(impossible) / max(1, total_case_count) >= 0.5 else 0.15
        reasons.append(f"실재할 수 없는 사건번호(있을 수 없는 연도 또는 사건부호)가 {len(impossible)}건 인용됨")
    remaining = len(unconfirmed) - len(impossible)
    if remaining > 0:
        ratio = remaining / max(1, total_case_count)
        if ratio >= 0.5:
            # 참고 신호로만 둔다. 이것만으로 AI 작성을 추정하지 않는다.
            score += 0.10
            reasons.append(f"인용 판례 중 공식 DB에서 확인되지 않은 것이 다수({remaining}건)임. "
                           "공식 DB 수록 범위 밖일 수 있어 그 자체로 임의 생성을 뜻하지는 않으며 원문 확인이 필요함")
        else:
            reasons.append(f"공식 DB에서 확인되지 않은 판례 인용 {remaining}건(원문 확인 필요). "
                           "점수에는 반영하지 않음")

    # 4. 구조적 특징 (단락별 지나치게 기계적인 번호 매기기, 대칭적 서술)
    list_markers = len(re.findall(r"^\s*(?:\d+\.|\([0-9]\)|첫째|둘째|셋째|넷째|마지막으로)", text, re.MULTILINE))
    if list_markers >= 5 and len(sents) >= 15:
        score += 0.10
        signals["heavy_listing"] = True
        reasons.append("기계적인 나열식 번호 체계와 전형적인 개조식 설명문 구조가 두드러짐")

    # 종합 판정 도출
    score = min(1.0, score)
    if score >= 0.65:
        verdict = "AI_FULL_GENERATION_LIKELY"
    elif score >= 0.35:
        verdict = "AI_PARTIAL_GENERATION"
    elif len(sents) < 5:
        verdict = "UNCERTAIN"
        reasons.append("문서 분량이 너무 적어 판정을 유보함")
    else:
        verdict = "HUMAN_AUTHORED_LIKELY"
        reasons.append("AI 특유의 환각이나 챗봇 잔재가 발견되지 않고 전통적인 법률 서면 작성 양식을 따르고 있음")

    return AIDetectorResult(
        verdict=verdict,
        score=score,
        reasons=reasons,
        suspicious_excerpts=suspicious_excerpts,
        signals=signals,
        used_llm=False,
    )


async def detect_ai_document(
    doc: NormalizedDocument,
    citation_findings: List[Finding],
    *,
    router: Optional[LLMRouter] = None,
    external_ai_policy: ExternalAIPolicy = ExternalAIPolicy.MASKED,
    metadata_indications: bool = False,
    mask: Optional[Callable[[str], str]] = None,
) -> AIDetectorResult:
    """문서의 AI 전체/부분 생성 여부를 종합 분석하여 판정한다.
    
    LLM(OpenAI/Gemini 등)이 활성화되어 있고 정책상 허용되면 심층 분석을 수행하고,
    그렇지 않으면 고도화된 규칙 기반 검출기로 대체한다.
    """
    text = doc.visible_text
    if not text.strip():
        return AIDetectorResult(
            verdict="UNCERTAIN",
            score=0.0,
            reasons=["문서 본문이 비어 있어 분석할 수 없음"],
        )

    # 1차 규칙 기반 특징 추출
    rule_res = _rule_based_ai_detection(doc, citation_findings, metadata_indications)

    # LLM을 사용할 수 없거나 정책이 LOCAL_ONLY인 경우 규칙 기반 결과 반환
    can_use_llm = bool(router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY
                       and hasattr(router, "consult_all")
                       and router.has_available_provider(policy=external_ai_policy))

    if not can_use_llm:
        return rule_res

    # 모델에게는 사실만 준다. 공식 DB 미확인을 "가짜 판례"라고 넘기면 모델이
    # 그 전제를 받아 AI 작성으로 기운다. 성립 불가 사건번호만 적극적 근거로 준다.
    impossible = rule_res.signals.get("impossible_case_numbers", [])
    hide = mask or (lambda value: value)

    system_prompt = (
        "당신은 법률 문서의 작성 경위를 감정하는 대한민국 법률 포렌식 전문가입니다.\n"
        "제공된 법률 서면 텍스트를 분석하여, 이 문서가 LLM(ChatGPT, Gemini 등)에 의해 전체 작성되었는지, "
        "일부 AI가 작성한 내용을 옮긴 것인지, 아니면 사람(변호사/당사자)이 작성한 실무 서면인지 판정하십시오.\n\n"
        "판정 기준:\n"
        "1. 대한민국 법원 제출 실무 서면(소장, 답변서, 준비서면 등)의 전형적인 형식과의 부합성.\n"
        "2. AI 특유의 번역투, 피상적이고 일반론적인 서술, 과도한 나열식 설명문 형식, 챗봇 상투구.\n"
        "3. 형식상 성립할 수 없는 사건번호 인용(제공된 경우에만). 공식 DB에서 찾지 못한 판례는 수록 범위 "
        "밖일 수 있으므로 근거로 삼지 마십시오.\n"
        "확신할 근거가 부족하면 UNCERTAIN으로 답하십시오. suspicious_excerpts의 snippet은 본문에 있는 "
        "문장을 그대로 옮기십시오.\n\n"
        "반드시 아래 JSON 형식으로만 응답하십시오:\n"
        "{\n"
        '  "verdict": "AI_FULL_GENERATION_LIKELY" | "AI_PARTIAL_GENERATION" | "HUMAN_AUTHORED_LIKELY" | "UNCERTAIN",\n'
        '  "ai_score": 0.0 ~ 1.0,\n'
        '  "reasons": ["구체적인 판단 근거 1", "근거 2", ...],\n'
        '  "suspicious_excerpts": [\n'
        '    {"snippet": "의심 문장 또는 문단", "reason": "이 부분이 AI 생성으로 의심되는 구체적 이유"}\n'
        "  ]\n"
        "}"
    )

    sample = hide(text[:6000])  # 상위 6000자 검토
    user_payload = {
        "document_filename": hide(doc.filename),
        "metadata_ai_hint": metadata_indications,
        "impossible_case_numbers": [hide(str(n)) for n in impossible][:5],
        "document_sample_text": sample,
    }
    req = LLMRequest(
        system=system_prompt,
        user=json.dumps(user_payload, ensure_ascii=False),
        temperature=0.1,
        max_tokens=1500,
        schema=_DETECTOR_SCHEMA,
    )
    try:
        answers = await router.consult_all(LLMRole.PRIMARY_REASONER, req, policy=external_ai_policy,
                                           expected_task="AI 작성 여부 판별")
    except Exception:
        return rule_res  # LLM 호출 실패 시 규칙 기반 결과
    return _combine_model_verdicts(rule_res, answers, sample)


_DETECTOR_SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "properties": {
        "verdict": {"enum": ["AI_FULL_GENERATION_LIKELY", "AI_PARTIAL_GENERATION",
                             "HUMAN_AUTHORED_LIKELY", "UNCERTAIN"]},
        "ai_score": {"type": "number"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "suspicious_excerpts": {"type": "array", "items": {"type": "object"}},
    },
}

# 심각도 순서. 여러 모델의 판정을 합칠 때 쓴다.
_VERDICT_RANK = {"HUMAN_AUTHORED_LIKELY": 0, "UNCERTAIN": 1, "AI_PARTIAL_GENERATION": 2,
                 "AI_FULL_GENERATION_LIKELY": 3}


def _combine_model_verdicts(rule_res: AIDetectorResult, answers: List[Any], sample: str) -> AIDetectorResult:
    """모델 판정을 교차검증해 합친다.

    과반이 지지하는 가장 무거운 판정을 택한다. 모델 둘이면 둘 다 동의해야
    올라가고, 셋이면 가운데 판정이 된다. 한 모델만 'AI 작성'이라 해도 그대로
    채택하던 것을 막는다. 의심 문단은 본문에 실제로 있는 것만 남긴다.
    """
    import statistics

    from packages.llm_router.providers import _extract_json

    opinions = []
    for answer in answers:
        if not getattr(answer, "used", False):
            continue
        execution = next((e for e in reversed(answer.executions) if getattr(e, "provider", "")), None)
        parsed = answer.parsed or _extract_json(answer.text) or {}
        verdict = parsed.get("verdict")
        if verdict not in _VERDICT_RANK:
            continue
        try:
            score = min(1.0, max(0.0, float(parsed.get("ai_score", rule_res.score))))
        except (TypeError, ValueError):
            score = rule_res.score
        opinions.append({"provider": getattr(execution, "provider", "unknown"),
                         "model": getattr(execution, "model", ""), "verdict": verdict, "score": score,
                         "reasons": [str(r)[:300] for r in (parsed.get("reasons") or [])][:4],
                         "excerpts": [e for e in (parsed.get("suspicious_excerpts") or []) if isinstance(e, dict)]})
    if not opinions:
        return rule_res

    ranks = sorted(_VERDICT_RANK[o["verdict"]] for o in opinions)
    majority = len(opinions) // 2 + 1
    # 과반이 "이 정도 이상"이라고 본 가장 높은 단계
    final_rank = max(r for r in ranks if sum(x >= r for x in ranks) >= majority)
    verdict = next(v for v, r in _VERDICT_RANK.items() if r == final_rank)
    agreement = ("SINGLE" if len(opinions) == 1
                 else "AGREE" if len({o["verdict"] for o in opinions}) == 1 else "DISAGREE")

    reasons = []
    if agreement == "DISAGREE":
        reasons.append("모델 간 판단 불일치: " + ", ".join(f"{o['provider']}={o['verdict']}" for o in opinions)
                       + ". 과반이 지지하는 판단을 택함")
    elif agreement == "SINGLE":
        reasons.append(f"1개 모델({opinions[0]['provider']})의 의견만 있어 교차검증되지 않음")
    for o in opinions:
        reasons.extend(f"[{o['provider']}] {r}" for r in o["reasons"][:2])
    for r in rule_res.reasons:
        if not any(r[:10] in cr for cr in reasons):
            reasons.append(r)

    normalized = " ".join(sample.split())
    excerpts, seen = [], set()
    for o in opinions:
        for e in o["excerpts"]:
            snippet = " ".join(str(e.get("snippet") or "").split())
            if len(snippet) >= 8 and snippet in normalized and snippet not in seen:
                seen.add(snippet)
                excerpts.append({"snippet": snippet, "reason": f"[{o['provider']}] {str(e.get('reason') or '')[:200]}"})
    excerpts += [e for e in rule_res.suspicious_excerpts if e.get("snippet") not in seen]

    return AIDetectorResult(
        verdict=verdict,
        score=float(statistics.median(o["score"] for o in opinions)),
        reasons=reasons,
        suspicious_excerpts=excerpts,
        signals={**rule_res.signals,
                 "llm_providers": [o["provider"] for o in opinions],
                 "llm_verdicts": {o["provider"]: o["verdict"] for o in opinions},
                 "llm_agreement": agreement,
                 "rule_score": rule_res.score},
        used_llm=True,
    )


def create_ai_detector_findings(doc: NormalizedDocument, result: AIDetectorResult) -> List[Finding]:
    """분석 결과를 시스템 Finding 목록으로 변환."""
    findings: List[Finding] = []
    features = {
        "ai_score": result.score,
        "used_llm": result.used_llm,
        "verdict": result.verdict,
        "llm_agreement": result.signals.get("llm_agreement", "NONE"),
    }
    # 여러 모델이 같은 판단을 냈을 때만 한 단계 높은 증거등급을 준다.
    cross_checked_grade = (EvidenceGrade.B if result.used_llm and result.signals.get("llm_agreement") == "AGREE"
                           else EvidenceGrade.C)

    if result.verdict == "AI_FULL_GENERATION_LIKELY":
        findings.append(
            Finding.create(
                type=FindingType.AI_FULL_GENERATION_SUSPECTED,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH,
                evidence_grade=cross_checked_grade,
                title=f"문서 전체의 AI 임의 생성 유력 (신뢰도: {int(result.score * 100)}%)",
                detail="; ".join(result.reasons[:3]) + " 법원 제출 전 실무 법률문서 요건과 진정성립에 대한 면밀한 검토가 필요합니다.",
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                tags=["AUTHORSHIP", "AI_DETECTION"],
                evidence=[
                    Evidence.create(
                        description="AI 생성 판단 근거",
                        grade=cross_checked_grade,
                        document_id=doc.document_id,
                        excerpt=" / ".join(result.reasons[:3]),
                    )
                ],
            )
        )
    elif result.verdict == "AI_PARTIAL_GENERATION":
        findings.append(
            Finding.create(
                type=FindingType.AI_AUTHORSHIP_LIKELY,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.C,
                title=f"문서 내 일부 AI 작성·인용 내용 확인 (신뢰도: {int(result.score * 100)}%)",
                detail="; ".join(result.reasons[:3]),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                tags=["AUTHORSHIP", "AI_DETECTION"],
            )
        )

    # 개별 의심 문단에 대해 Finding 생성
    for exc in result.suspicious_excerpts[:4]:
        snippet = exc.get("snippet", "")
        reason = exc.get("reason", "")
        if snippet:
            findings.append(
                Finding.create(
                    type=FindingType.AI_HALLUCINATED_CONTENT,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.C,
                    title="AI 임의 생성 의심 문단 발견",
                    detail=f"근거: {reason}. 발췌: \"{snippet[:150]}...\"",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    tags=["AUTHORSHIP", "AI_HALLUCINATION"],
                    evidence=[
                        Evidence.create(
                            description="의심 문구 발췌",
                            grade=EvidenceGrade.C,
                            document_id=doc.document_id,
                            excerpt=snippet[:300],
                            supports=False,
                        )
                    ],
                )
            )

    return findings
