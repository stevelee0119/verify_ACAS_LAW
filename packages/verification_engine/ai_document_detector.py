"""AI 법률문서 생성 여부 심층 판별 모듈 (제13장 확장).

법률문서(답변서, 소장, 준비서면 등) 전체가 AI(ChatGPT, Gemini 등)에 의해 임의로
작성되었는지, 또는 일부 내용에 AI가 관여하였는지를 메타데이터, 가짜 판례/조문 환각 빈도,
구조적 특징 및 LLM(OpenAI/Gemini) 심층 분석을 결합하여 판정한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
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

    # 3. 존재하지 않는 판례(할루시네이션) 발생 정황 결합
    fake_case_count = sum(1 for f in citation_findings if f.type == FindingType.CASE_NOT_FOUND)
    total_case_count = sum(1 for f in citation_findings if "CASE" in f.tags)
    if fake_case_count > 0:
        ratio = fake_case_count / max(1, total_case_count)
        if ratio >= 0.5:
            score += 0.30
            reasons.append(f"인용된 판례 중 공식 DB에서 확인되지 않는 판례(할루시네이션 의심)가 다수({fake_case_count}건) 존재함")
        else:
            score += 0.15
            reasons.append(f"공식 DB에서 확인되지 않는 가공의 판례가 {fake_case_count}건 인용되어 AI 생성 의심을 뒷받침함")

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
    can_use_llm = False
    if router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY:
        if hasattr(router, "has_available_provider"):
            can_use_llm = router.has_available_provider(policy=external_ai_policy)
        elif hasattr(router, "available_providers"):
            can_use_llm = len(router.available_providers(policy=external_ai_policy)) > 0

    if not can_use_llm:
        return rule_res

    # 가짜 판례 목록 요약
    fake_cases = [
        f.title for f in citation_findings if f.type == FindingType.CASE_NOT_FOUND
    ][:5]

    # LLM 심층 판별 프롬프트 구성
    system_prompt = (
        "당신은 법률 문서의 진정성 및 AI 생성(환각/위조) 여부를 전문적으로 감정하는 대한민국 법률 AI 포렌식 전문가입니다.\n"
        "제공된 법률 서면 텍스트와 정황을 분석하여, 이 문서가 LLM(ChatGPT, Gemini 등)에 의해 임의로 전체 작성되었는지, "
        "일부 AI가 작성한 내용을 복사·인용한 것인지, 아니면 실제 인간(변호사/당사자)이 작성한 실무 서면인지 판정하십시오.\n\n"
        "판정 기준:\n"
        "1. 대한민국 법원 제출 실무 서면(소장, 답변서, 준비서면 등)의 전형적인 형식(당사자 표시, 청구취지에 대한 답변, "
        "청구원인에 대한 인부 및 항변 구조)과의 부합성.\n"
        "2. AI 특유의 번역투, 피상적이고 일반론적인 원론 서술, 과도한 나열식 설명문 형식, 챗봇 상투구.\n"
        "3. 존재하지 않는 가공의 판례나 조문을 지어내어 논리의 근거로 삼았는지 여부.\n\n"
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

    user_payload = {
        "document_filename": doc.filename,
        "metadata_ai_hint": metadata_indications,
        "unverified_fake_cases_found": fake_cases,
        "document_sample_text": text[:6000],  # 상위 6000자 검토
    }

    req = LLMRequest(
        system=system_prompt,
        user=json.dumps(user_payload, ensure_ascii=False),
        temperature=0.1,
        max_tokens=1500,
    )

    try:
        # LLMRouter의 primary provider(OpenAI 또는 Gemini)를 통해 분석 요청
        provider = (
            router.primary(policy=external_ai_policy)
            if hasattr(router, "primary")
            else (router.pick(LLMRole.PRIMARY_REASONER, policy=external_ai_policy) if hasattr(router, "pick") else None)
        )
        if not provider:
            return rule_res
        resp = await provider.structured_output(schema={}, request=req)
        if resp.ok and resp.parsed:
            parsed = resp.parsed
            llm_verdict = parsed.get("verdict", rule_res.verdict)
            llm_score = float(parsed.get("ai_score", rule_res.score))
            llm_reasons = parsed.get("reasons", [])
            llm_excerpts = parsed.get("suspicious_excerpts", [])

            # 규칙 기반에서 발견된 치명적 상투구/정황이 있다면 병합
            combined_reasons = list(llm_reasons)
            for r in rule_res.reasons:
                if not any(r[:10] in cr for cr in combined_reasons):
                    combined_reasons.append(r)

            combined_excerpts = list(llm_excerpts) + rule_res.suspicious_excerpts

            return AIDetectorResult(
                verdict=llm_verdict,
                score=llm_score,
                reasons=combined_reasons,
                suspicious_excerpts=combined_excerpts,
                signals={
                    "llm_provider": resp.provider,
                    "llm_model": resp.model,
                    "rule_score": rule_res.score,
                },
                used_llm=True,
            )
    except Exception:
        # LLM 호출 실패 시 안전하게 규칙 기반 결과로 fallback
        pass

    return rule_res


def create_ai_detector_findings(doc: NormalizedDocument, result: AIDetectorResult) -> List[Finding]:
    """분석 결과를 시스템 Finding 목록으로 변환."""
    findings: List[Finding] = []
    features = {
        "ai_score": result.score,
        "used_llm": result.used_llm,
        "verdict": result.verdict,
    }

    if result.verdict == "AI_FULL_GENERATION_LIKELY":
        findings.append(
            Finding.create(
                type=FindingType.AI_FULL_GENERATION_SUSPECTED,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.B if result.used_llm else EvidenceGrade.C,
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
                        grade=EvidenceGrade.B if result.used_llm else EvidenceGrade.C,
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
