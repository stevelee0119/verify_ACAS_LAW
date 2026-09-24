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

from packages.document_engine.reading_text import build_reading_text

from .ai_residue import scan_residue

ENGINE_NAME = "verification_engine.ai_document_detector"

# AI 응답 잔재 규칙은 ai_residue.RESIDUE_RULES에 있다.


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

    # 2. AI 응답 잔재(ai_residue): 대화형 서두·면책 안내·지식 기준일·마크다운은 객관적 흔적,
    #    상투 표현·영문 병기는 문체 신호로만 센다.
    # 줄바꿈으로 갈린 문구("드리겠습 / 니다")를 잇기 위해 읽기 본문에서 찾는다.
    residues = scan_residue(build_reading_text(doc).text)
    signals["residues"] = [{"category": r.category, "label": r.label, "objective": r.objective,
                            "matches": r.matches} for r in residues]
    cliche_hits = sum(len(r.matches) for r in residues if r.objective)
    style_hits = sum(1 for r in residues if not r.objective)
    if cliche_hits > 0:
        score += min(0.60, 0.20 * cliche_hits)
        reasons.append("AI 챗봇의 전형적인 관용구·면책·대화형 응답 잔재(" + ", ".join(
            r.label for r in residues if r.objective) + f")가 {cliche_hits}건 발견됨")
    if style_hits:
        score += 0.05 * style_hits
        signals["style_signals"] = [r.label for r in residues if not r.objective]

    # 3. 판례 인용 오류는 작성 주체의 근거로 쓰지 않는다.
    #
    # 가공·오류 인용은 '법률 인용 오류' 축에서 다룬다. 사람도 사건번호를 잘못 적고,
    # 검증용 자료는 일부러 가공 인용을 넣는다. 예전에는 성립 불가 사건번호가 있으면
    # AI 점수에 0.30을 더해, 인용 오류가 AI 작성 판정으로 두 번 계산됐다.
    unconfirmed = [f for f in citation_findings
                   if f.type == FindingType.CASE_NOT_FOUND and f.status == VerificationStatus.NOT_FOUND]
    impossible = [f for f in unconfirmed
                  if (f.confidence_features or {}).get("case_number")
                  and not case_number_possible(str(f.confidence_features["case_number"]))]
    signals["impossible_case_numbers"] = [str(f.confidence_features["case_number"]) for f in impossible]
    signals["citation_errors_used_for_authorship"] = False
    if unconfirmed:
        reasons.append(f"법률 인용 오류·미확인 {len(unconfirmed)}건은 인용 검증 축에서 다루며, "
                       "작성 주체(AI 사용 여부) 판단에는 반영하지 않음")

    # 4. 구조적 특징 (단락별 지나치게 기계적인 번호 매기기, 대칭적 서술)
    list_markers = len(re.findall(r"^\s*(?:\d+\.|\([0-9]\)|첫째|둘째|셋째|넷째|마지막으로)", text, re.MULTILINE))
    if list_markers >= 5 and len(sents) >= 15:
        score += 0.10
        signals["heavy_listing"] = True
        reasons.append("기계적인 나열식 번호 체계와 전형적인 개조식 설명문 구조가 두드러짐")

    # 종합 판정 도출
    #
    # 객관적 작성 흔적(도구 표기·챗봇 응답 잔재)이 있어야 AI 판정을 낸다. 서식·나열 구조는
    # 사람이 쓴 법률 서면에도 흔하다. 흔적이 없다는 사실은 '사람이 썼다'는 근거도 아니다.
    score = min(1.0, score)
    objective_traces = cliche_hits + (1 if metadata_indications else 0)
    signals["objective_traces"] = objective_traces
    if score >= 0.65 and objective_traces:
        verdict = "AI_FULL_GENERATION_LIKELY"
    elif score >= 0.35 and objective_traces:
        verdict = "AI_PARTIAL_GENERATION"
    else:
        verdict = "UNCERTAIN"
        reasons.append("문서 분량이 너무 적어 판정을 유보함" if len(sents) < 5 else
                       "객관적 작성 흔적을 찾지 못해 판단을 유보함(흔적이 없다는 것이 사람 작성의 근거는 아님)")

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
    exclude_texts: Optional[List[str]] = None,
    exclude_block_ids: Optional[List[str]] = None,
) -> AIDetectorResult:
    """문서의 AI 전체/부분 생성 여부를 종합 분석하여 판정한다.

    exclude_texts는 문서 안의 지시문(프롬프트 인젝션)처럼 공격 탐지 대상인 구간이다.
    그 문구는 작성 주체의 근거가 아니므로 모델에게 보내는 본문에서 가린다.
    
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

    # 모델에게는 작성 주체 판단에 쓸 수 있는 것만 준다. 인용 오류나 문서 속 지시문을
    # 넘기면 모델이 그것을 AI 작성의 근거로 삼아 같은 사실이 두 번 계산된다.
    hide = mask or (lambda value: value)
    excluded = 0
    if exclude_block_ids:
        # 여러 줄에 걸친 지시문은 문장 단위로 탐지되므로 줄 문자열 치환으로는 일부가 남는다. 블록째 뺀다.
        dropped = set(exclude_block_ids)
        kept = []
        for block in doc.body_blocks():
            if block.block_id in dropped:
                if not kept or kept[-1] != "[문서 내 지시문 — 작성 주체 판단에서 제외]":
                    kept.append("[문서 내 지시문 — 작성 주체 판단에서 제외]")
                    excluded += 1
            else:
                kept.append(block.text)
        text = "\n".join(kept)
    for fragment in sorted({t.strip() for t in (exclude_texts or []) if t and len(t.strip()) >= 8}, key=len, reverse=True):
        if fragment in text:
            text = text.replace(fragment, "[문서 내 지시문 — 작성 주체 판단에서 제외]")
            excluded += 1
    rule_res.signals["excluded_instruction_segments"] = excluded

    system_prompt = (
        "당신은 법률 문서의 작성 경위를 감정하는 대한민국 법률 포렌식 전문가입니다.\n"
        "제공된 법률 서면 텍스트를 분석하여, 이 문서가 LLM(ChatGPT, Gemini 등)에 의해 전체 작성되었는지, "
        "일부 AI가 작성한 내용을 옮긴 것인지, 아니면 사람(변호사/당사자)이 작성한 실무 서면인지 판정하십시오.\n\n"
        "판정 기준:\n"
        "1. AI 특유의 번역투, 피상적이고 일반론적인 서술, 챗봇 상투구·응답 잔재 같은 작성 흔적.\n"
        "2. 다음은 작성 주체의 근거가 아닙니다: 표준 서식·전문적 문체·템플릿 반복(사람도 씀), "
        "판례·법령 인용 오류나 가공 인용(인용 검증에서 따로 다룸), 문서 속 지시문('[문서 내 지시문 …]'으로 "
        "가린 부분 포함, 공격 탐지에서 따로 다룸).\n"
        "확신할 근거가 부족하면 UNCERTAIN으로 답하십시오. suspicious_excerpts의 snippet은 본문에 있는 "
        "문장을 그대로 옮기십시오.\n"
        "분량: reasons는 최대 4개(각 150자 이내), suspicious_excerpts는 최대 4개(snippet 120자·reason 100자 "
        "이내). 주민등록번호 등 개인 식별번호가 든 문장은 발췌하지 말고, 인터넷 주소(URL)는 쓰지 마십시오"
        "(응답이 보안 검사에서 격리됩니다). JSON 객체 하나만 답하십시오.\n\n"
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
        "document_sample_text": sample,
    }
    req = LLMRequest(
        system=system_prompt,
        user=json.dumps(user_payload, ensure_ascii=False),
        temperature=0.1,
        # 한국어 JSON에서 Anthropic은 OpenAI보다 몇 배 많은 토큰을 쓴다. 1500이면 짧은
        # 서면에서도 한도의 90%를 넘겨 잘리곤 했다. 과금은 실제 생성량 기준이다.
        max_tokens=4096,
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
    from packages.llm_router.router import failure_summary

    failures = failure_summary(answers)
    # 응답하지 못한 모델도 어떤 모델이었는지 남긴다.
    failure_models = {e.provider: getattr(e, "model", "") for a in answers if not getattr(a, "used", False)
                      for e in getattr(a, "executions", [])[-1:] if getattr(e, "provider", "")}
    failed_text = ", ".join(f"{name}({why})" for name, why in sorted(failures.items()))

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
        if failed_text:
            rule_res.reasons.append(f"AI 교차검토를 수행하지 못해 규칙 기반 결과만 사용함 — 응답하지 못한 모델: {failed_text}")
            rule_res.signals["llm_failures"] = failures
            rule_res.signals["llm_failure_models"] = failure_models
        return rule_res

    agreement = ("SINGLE" if len(opinions) == 1
                 else "AGREE" if len({o["verdict"] for o in opinions}) == 1 else "DISAGREE")
    # 최종 판정 규칙(과반수로 높은 확신의 결론을 고정하지 않는다)
    #   - 모델 의견이 갈리면 유보(UNCERTAIN)한다. 분포는 그대로 싣는다.
    #   - 모든 모델이 같은 'AI 작성' 판단을 내려도, 문체·형식 밖의 객관적 작성 흔적
    #     (도구 표기·챗봇 응답 잔재)이 없으면 유보한다. 문체만으로 작성자를 정하지 않는다.
    #   - 모델 하나의 의견만으로는 규칙 기반 판정보다 무겁게 올리지 않는다.
    objective = int(rule_res.signals.get("objective_traces") or 0)
    single_downgraded = False
    held_reason = ""
    if agreement == "AGREE":
        verdict = opinions[0]["verdict"]
        if verdict.startswith("AI_") and not objective:
            verdict, held_reason = "UNCERTAIN", (
                "모든 모델이 AI 작성 가능성을 높게 보았으나 문체·형식 밖의 객관적 작성 흔적이 없어 "
                "판단을 유보함(문체·표준 형식·인용 오류만으로 작성 주체를 정하지 않음)")
    elif agreement == "SINGLE":
        verdict = opinions[0]["verdict"]
        if _VERDICT_RANK[verdict] > _VERDICT_RANK.get(rule_res.verdict, _VERDICT_RANK["UNCERTAIN"]):
            verdict, single_downgraded = rule_res.verdict, True
    else:
        verdict = "UNCERTAIN"
    if verdict == "HUMAN_AUTHORED_LIKELY":
        # AI 흔적을 찾지 못했다는 것은 사람이 썼다는 근거가 아니다. '사람 작성 유력'으로 단정하지 않는다(v2 Phase 8).
        verdict, held_reason = "UNCERTAIN", (
            "모델이 사람 작성 쪽으로 판단했으나 AI 흔적이 없다는 사실만으로 사람 작성을 단정하지 않으므로 판단을 유보함")
    final_rank = _VERDICT_RANK[verdict]

    reasons = []
    if agreement == "DISAGREE":
        reasons.append("모델 간 판단 불일치: " + ", ".join(f"{o['provider']}={o['verdict']}" for o in opinions)
                       + ". 의견이 갈려 판단을 유보함(과반수로 확정하지 않음)")
    if held_reason:
        reasons.append(held_reason)
    elif agreement == "SINGLE":
        reasons.append(f"1개 모델({opinions[0]['provider']})의 의견만 있어 교차검증되지 않음"
                       + (f" — 응답하지 못한 모델: {failed_text}" if failed_text else ""))
        if single_downgraded:
            reasons.append(f"그 모델의 판단({opinions[0]['verdict']})은 참고로만 두고, "
                           f"규칙 기반 판정({rule_res.verdict})을 유지함")
    if failed_text and agreement != "SINGLE":
        reasons.append(f"응답하지 못한 모델: {failed_text}")
    # 모델마다 근거를 모두 싣는다. 앞의 두 개만 남기면 화면·보고서에서 어느 모델의
    # 설명이 빠졌는지 알 수 없었다. 모델별 결론은 llm_opinions에 따로 둔다.
    for o in opinions:
        reasons.extend(f"[{o['provider']}] {r}" for r in o["reasons"])
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

    model_median = float(statistics.median(o["score"] for o in opinions))
    return AIDetectorResult(
        verdict=verdict,
        score=(rule_res.score if single_downgraded else model_median),
        reasons=reasons,
        suspicious_excerpts=excerpts,
        signals={**rule_res.signals,
                 "llm_providers": [o["provider"] for o in opinions],
                 "llm_verdicts": {o["provider"]: o["verdict"] for o in opinions},
                 "llm_opinions": [{"provider": o["provider"], "model": o["model"], "verdict": o["verdict"],
                                   "score": round(o["score"], 3), "reasons": o["reasons"]} for o in opinions],
                 "llm_agreement": agreement,
                 "llm_failures": failures,
                 "llm_failure_models": failure_models,
                 "rule_score": rule_res.score,
                 "model_score_median": round(model_median, 3),
                 "verdict_distribution": {v: sum(o["verdict"] == v for o in opinions) for v in _VERDICT_RANK},
                 "decision_rule": ("UNANIMOUS_WITH_OBJECTIVE_TRACE" if agreement == "AGREE" and not held_reason
                                   else "HELD_NO_OBJECTIVE_TRACE" if held_reason
                                   else "HELD_DISAGREEMENT" if agreement == "DISAGREE"
                                   else "SINGLE_MODEL_CAPPED_BY_RULES"),
                 **SCORE_DEFINITIONS},
        used_llm=True,
    )


# 화면·보고서에 그대로 싣는 지표 정의. 점수와 신뢰도는 서로 다른 값이다.
SCORE_DEFINITIONS = {
    "score_definition": ("AI 작성 가능성 추정치(0~1). 응답한 모델들이 낸 ai_score의 중앙값이며, "
                         "모델 하나만 응답해 규칙 판정으로 낮춘 경우에는 규칙 점수다. 작성 주체의 증명이 아니다."),
    "confidence_definition": ("판정 근거의 신뢰도(0~1). 근거가 객관적 흔적인지, 여러 모델이 교차검증했는지로 "
                              "계산한 finding.confidence이다. 추정치가 높아도 근거가 문체뿐이면 낮다."),
}


def create_ai_detector_findings(doc: NormalizedDocument, result: AIDetectorResult) -> List[Finding]:
    """분석 결과를 시스템 Finding 목록으로 변환."""
    findings: List[Finding] = []
    features = {
        "ai_score": result.score,
        "used_llm": result.used_llm,
        "verdict": result.verdict,
        "llm_agreement": result.signals.get("llm_agreement", "NONE"),
        "objective_traces": result.signals.get("objective_traces", 0),
        # 문체만의 판단은 휴리스틱이다. 신뢰도 계산이 이것을 반영한다.
        "heuristic_only": not result.signals.get("objective_traces"),
        "score_definition": SCORE_DEFINITIONS["score_definition"],
        "confidence_definition": SCORE_DEFINITIONS["confidence_definition"],
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
                title=f"문서 전체의 AI 작성 가능성 높음 (추정치 {result.score:.2f}, 근거 신뢰도는 별도 표시)",
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
                title=f"문서 일부의 AI 작성 가능성 (추정치 {result.score:.2f}, 근거 신뢰도는 별도 표시)",
                detail="; ".join(result.reasons[:3]),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                tags=["AUTHORSHIP", "AI_DETECTION"],
            )
        )

    elif result.verdict == "UNCERTAIN" and result.used_llm and (result.signals.get("model_score_median") or 0) >= 0.5:
        # 판정은 유보했지만 모델 의견이 AI 쪽으로 기운 경우. 숨기지 않고 참고로 싣는다.
        dist = result.signals.get("verdict_distribution") or {}
        findings.append(
            Finding.create(
                type=FindingType.AI_AUTHORSHIP_LIKELY,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.INFO,
                evidence_grade=EvidenceGrade.D,
                title=f"AI 작성 가능성 판단 유보 (모델 추정치 중앙값 {result.signals.get('model_score_median'):.2f})",
                detail=("모델별 판단: " + ", ".join(f"{k} {v}건" for k, v in dist.items() if v) + ". "
                        + "; ".join(result.reasons[:2])),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=doc.document_id,
                engine=ENGINE_NAME,
                advisory_only=True,
                tags=["AUTHORSHIP", "AI_DETECTION"],
            )
        )

    # AI 응답 잔재: 범주마다 하나씩, 발견한 문구를 그대로 싣는다(참고용, 확정 불가).
    for residue in result.signals.get("residues") or []:
        sample = residue["matches"][0]
        findings.append(Finding.create(
            type=FindingType.AI_AUTHORSHIP_LIKELY,
            # 잔재 문구가 문서에 있다는 것은 관찰된 사실(의심 신호)이다. 문체 신호는 약하므로 미확인으로 둔다.
            status=VerificationStatus.SUSPICIOUS if residue["objective"] else VerificationStatus.UNVERIFIED,
            severity=Severity.LOW if residue["objective"] else Severity.INFO,
            evidence_grade=EvidenceGrade.B if residue["objective"] else EvidenceGrade.C,
            advisory_only=True,
            title=f"AI 응답 잔재 신호: {residue['label']} — '{sample[:60]}' (참고용, 확정 불가)",
            detail=("발견 문구: " + " / ".join(f"'{m[:80]}'" for m in residue["matches"]) + ". "
                    + ("서면 작성 관행에 없는 AI 답변 표지다. " if residue["objective"] else
                       "사람도 쓰는 표현이므로 문체 신호로만 표시한다. ")
                    + "이 신호만으로 AI 작성이나 사람 작성을 단정하지 않는다."),
            confidence=0.6 if residue["objective"] else 0.3,
            confidence_features={**features, "residue_category": residue["category"],
                                 "rule_id": f"AIGEN.{residue['category']}", "objective": residue["objective"]},
            document_id=doc.document_id, engine=ENGINE_NAME,
            tags=["AUTHORSHIP", "AI_RESIDUE", residue["category"]],
            evidence=[Evidence.create(description=f"{residue['label']} 발췌", grade=EvidenceGrade.C,
                                      document_id=doc.document_id, excerpt=" / ".join(residue["matches"])[:300],
                                      supports=False)],
        ))

    # 개별 의심 문단: 작성 주체에 관한 참고 신호다. 내용의 오류(환각)와 섞지 않는다.
    for exc in result.suspicious_excerpts[:4]:
        snippet = exc.get("snippet", "")
        reason = exc.get("reason", "")
        if snippet:
            findings.append(
                Finding.create(
                    type=FindingType.AI_AUTHORSHIP_LIKELY,
                    status=VerificationStatus.UNVERIFIED,
                    severity=Severity.INFO,
                    evidence_grade=EvidenceGrade.C,
                    advisory_only=True,
                    title="AI 작성 참고 신호 문구 (내용 오류 판정 아님)",
                    detail=f"근거: {reason}. 발췌: \"{snippet[:150]}...\"",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    tags=["AUTHORSHIP", "AUTHORSHIP_SIGNAL"],
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
