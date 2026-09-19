"""법률적 주장 타당성 검토 및 AI 임의 생성(환각) 대조표 생성 엔진 (제9·11장 확장).

문서에 인용된 판례 중 공식 DB에서 확인되지 않는 가짜 판례(할루시네이션)가
어떤 법률적 주장의 근거로 쓰였는지 추적하고, 해당 주장의 대한민국 법리상 타당성 여부와
구체적 반박 근거를 분석하여 가시적인 대조표(Table) 형태로 도출한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    ExternalAIPolicy,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Citation, Claim, Evidence, Finding, NormalizedDocument
from packages.llm_router import LLMRouter
from packages.llm_router.providers import LLMRequest

ENGINE_NAME = "legal_engine.argument_validity"


@dataclass
class HallucinationTableRow:
    """AI 임의 생성 의심 내용 및 법률 주장 타당성 검토 대조표의 단일 행."""

    location: str                   # 위치 (예: 2페이지 3단락)
    claim_text: str                 # 문서에 기재된 법률적 주장
    cited_authority: str            # 인용된 판례/조문/문헌
    authority_exists: bool          # 실제 공식 존재 여부 (False: 허위 판례)
    ai_generation_basis: str        # AI 임의 생성으로 판단되는 근거
    validity_verdict: str           # 주장 타당성 평가 (타당 / 부당 / 근거결여 / 검토필요)
    legal_reasoning: str            # 법리적 타당성 검토 및 반박 근거
    recommended_counteraction: str  # 실무상 대응 방안 및 반박 논거

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location": self.location,
            "claim_text": self.claim_text,
            "cited_authority": self.cited_authority,
            "authority_exists": self.authority_exists,
            "ai_generation_basis": self.ai_generation_basis,
            "validity_verdict": self.validity_verdict,
            "legal_reasoning": self.legal_reasoning,
            "recommended_counteraction": self.recommended_counteraction,
        }


@dataclass
class ArgumentValidityResult:
    rows: List[HallucinationTableRow] = field(default_factory=list)
    overall_validity_summary: str = ""
    findings: List[Finding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "overall_validity_summary": self.overall_validity_summary,
            "findings_count": len(self.findings),
        }


async def verify_argument_validity(
    doc: NormalizedDocument,
    citations: List[Citation],
    legal_verdicts: List[Dict[str, Any]],
    claims: List[Claim],
    *,
    router: Optional[LLMRouter] = None,
    external_ai_policy: ExternalAIPolicy = ExternalAIPolicy.MASKED,
) -> ArgumentValidityResult:
    """허위 판례 인용 및 법률 주장에 대한 타당성 종합 검토를 수행하고 대조표를 생성한다."""
    result = ArgumentValidityResult()

    # 1. 공식 DB에서 미확인된(가짜) 판례 및 불일치 판례 선별
    unverified_cases: List[Dict[str, Any]] = []
    citation_by_id = {c.citation_id: c for c in citations}

    for verdict in legal_verdicts:
        cid = verdict.get("citation_id")
        citation = citation_by_id.get(cid)
        if not citation:
            continue

        status = str(verdict.get("status", ""))
        levels = verdict.get("levels", {})

        # 판례가 공식 소스에서 발견되지 않았거나(NOT_FOUND), 심각한 불일치가 있는 경우
        if status in ("NOT_FOUND", "CONTRADICTED") or levels.get("level1") == "NOT_FOUND":
            unverified_cases.append({
                "citation": citation,
                "verdict": verdict,
                "context": citation.context or doc.full_text[max(0, citation.span[0] - 200) : min(len(doc.full_text), citation.span[1] + 200)] if citation.span else "",
            })

    # 2. 가짜 판례가 하나도 없고 주장도 없으면 기본 정상 반환
    if not unverified_cases and not claims:
        result.overall_validity_summary = "공식 소스에서 확인되지 않는 허위 판례나 중대한 법률 주장 결함이 발견되지 않았습니다."
        return result

    # 3. LLM(OpenAI/Gemini)을 활용한 심층 법률 타당성 검토
    can_use_llm = router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY and router.has_available_provider()

    if can_use_llm and unverified_cases:
        # LLM 프롬프트 준비
        case_items_for_prompt = []
        for idx, item in enumerate(unverified_cases, 1):
            c: Citation = item["citation"]
            case_items_for_prompt.append({
                "item_id": idx,
                "page": c.page or 1,
                "cited_case": c.raw_text,
                "surrounding_context_and_claim": item["context"][:1000],
            })

        system_prompt = (
            "당신은 대한민국 최고 수준의 판사·변호사 출신 법률 인공지능 검토관입니다.\n"
            "법률문서 검토 중 '공식 법원 판례 DB에서 전혀 존재하지 않는 가공의 판례(AI 환각 생성 판례)'가 인용된 정황이 발견되었습니다.\n\n"
            "각 항목에 대해 다음 사항을 정밀하게 검토하십시오:\n"
            "1. 작성자가 해당 가짜 판례를 통해 입증하려고 하는 '법률적 주장(Claim)'이 무엇인가?\n"
            "2. 왜 이 판례가 AI의 임의 생성(환각)으로 판단되는가? (사건번호 형식, 존재하지 않는 법리 등)\n"
            "3. [중요] 해당 가공의 판례를 제외하고 볼 때, 해당 법률적 주장이 대한민국 실정법(민법, 형법 등) 및 실제 대법원 확립된 판례 법리에 비추어 타당한가, 아니면 법리적으로 배척될 부당한 주장인가?\n"
            "4. 상대방 또는 검토 변호사가 법정에서 이를 어떻게 지적하고 반박해야 하는가? (구체적 실무 반박 논거 및 실제 관련 판례 제시)\n\n"
            "반드시 아래 JSON 포맷으로만 응답하십시오:\n"
            "{\n"
            '  "overall_summary": "종합적인 법률 주장 타당성 및 AI 환각 발생 평가 요약",\n'
            '  "rows": [\n'
            "    {\n"
            '      "item_id": 1,\n'
            '      "claim_text": "문서에 기재된 법률적 주장 핵심 요약",\n'
            '      "ai_generation_basis": "AI 임의 생성(가짜 판례)으로 판단되는 구체적 이유",\n'
            '      "validity_verdict": "부당 (법리 오해)" | "근거 결여" | "일부 타당하나 증명 부족" | "타당",\n'
            '      "legal_reasoning": "실제 대한민국 법리 및 대법원 실제 태도에 비춘 심층 검토 내용",\n'
            '      "recommended_counteraction": "상대방에 대한 효과적인 실무 반박 논거 및 지적 방안"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = json.dumps({
            "unverified_cases": case_items_for_prompt,
            "document_title": doc.filename,
        }, ensure_ascii=False)

        req = LLMRequest(
            system=system_prompt,
            user=user_content,
            temperature=0.1,
            max_tokens=2500,
        )

        try:
            provider = router.primary()
            resp = await provider.structured_output(schema={}, request=req)
            if resp.ok and resp.parsed:
                parsed = resp.parsed
                result.overall_validity_summary = parsed.get("overall_summary", "")
                parsed_rows = {r.get("item_id"): r for r in parsed.get("rows", [])}

                for idx, item in enumerate(unverified_cases, 1):
                    c = item["citation"]
                    p_row = parsed_rows.get(idx, {})

                    claim = p_row.get("claim_text") or (c.context[:150] if c.context else "판례 인용 주장")
                    basis = p_row.get("ai_generation_basis") or "대법원 종합법률정보 공식 DB 검색 결과 일치하는 판례 없음 (NOT_FOUND)"
                    verdict_text = p_row.get("validity_verdict") or "근거 결여 (허위 판례 인용)"
                    reasoning = p_row.get("legal_reasoning") or "존재하지 않는 가공의 판례를 근거로 삼고 있어 법리적 타당성을 인정하기 어렵습니다."
                    counter = p_row.get("recommended_counteraction") or "판례 부존재 석명 요구 및 실제 확립된 법리에 따른 배척 주장 필요."

                    row = HallucinationTableRow(
                        location=f"{c.page or 1}면",
                        claim_text=claim,
                        cited_authority=c.raw_text,
                        authority_exists=False,
                        ai_generation_basis=basis,
                        validity_verdict=verdict_text,
                        legal_reasoning=reasoning,
                        recommended_counteraction=counter,
                    )
                    result.rows.append(row)

                    # Finding 생성
                    feats = {"deterministic_rule": False, "used_llm": True, "fake_citation": c.raw_text}
                    result.findings.append(
                        Finding.create(
                            type=FindingType.LEGAL_ARGUMENT_INVALID,
                            status=VerificationStatus.CONTRADICTED,
                            severity=Severity.HIGH,
                            evidence_grade=EvidenceGrade.B,
                            title=f"허위 판례에 근거한 법률 주장 발견: {c.raw_text}",
                            detail=f"주장: {claim}. 검토 결과: [{verdict_text}] {reasoning}",
                            confidence=confidence_score(feats),
                            confidence_features=feats,
                            document_id=doc.document_id,
                            page=c.page,
                            engine=ENGINE_NAME,
                            tags=["LEGAL", "ARGUMENT_VALIDITY", "AI_HALLUCINATION"],
                            evidence=[
                                Evidence.create(
                                    description="가짜 판례 인용 법률 주장",
                                    grade=EvidenceGrade.B,
                                    document_id=doc.document_id,
                                    excerpt=c.context[:300] if c.context else c.raw_text,
                                    supports=False,
                                )
                            ],
                        )
                    )
                return result
        except Exception:
            # LLM 장애 시 규칙 기반 폴백
            pass

    # 4. 규칙 기반 폴백 처리
    for item in unverified_cases:
        c = item["citation"]
        row = HallucinationTableRow(
            location=f"{c.page or 1}면",
            claim_text=c.context[:150] if c.context else f"{c.raw_text}에 기반한 법률적 주장",
            cited_authority=c.raw_text,
            authority_exists=False,
            ai_generation_basis="대법원 종합법률정보 및 국가법령정보 공식 DB 검색 결과 일치하는 판례 없음 (AI 환각 의심)",
            validity_verdict="근거 결여 (허위 판례 인용)",
            legal_reasoning="존재하지 않는 가공의 판례를 전제로 하고 있으므로 법리적 타당성을 인정할 수 없으며 원문 확인이 필수적입니다.",
            recommended_counteraction="상대방에게 해당 판결문 사본 제출 또는 사건번호 정정 석명을 신청하고, 판례 부존재를 이유로 주장 배척을 구해야 함.",
        )
        result.rows.append(row)

        feats = {"deterministic_rule": True, "fake_citation": c.raw_text}
        result.findings.append(
            Finding.create(
                type=FindingType.LEGAL_ARGUMENT_INVALID,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.C,
                title=f"공식 미확인 판례에 근거한 법률 주장: {c.raw_text}",
                detail="공식 DB에서 확인되지 않는 판례를 주요 근거로 삼고 있어 법리적 타당성 결여 위험이 큽니다.",
                confidence=confidence_score(feats),
                confidence_features=feats,
                document_id=doc.document_id,
                page=c.page,
                engine=ENGINE_NAME,
                tags=["LEGAL", "ARGUMENT_VALIDITY", "AI_HALLUCINATION"],
            )
        )

    if result.rows:
        result.overall_validity_summary = f"공식 DB에서 확인되지 않는 가짜 판례가 {len(result.rows)}건 인용되어, 이에 기초한 법률적 주장의 타당성에 중대한 결함이 있습니다."
    else:
        result.overall_validity_summary = "중대한 법률적 주장 결함이 발견되지 않았습니다."

    return result
