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
    LLMRole,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Citation, Claim, Evidence, Finding, NormalizedDocument
from packages.legal_engine.normalize import case_number_possible
from packages.llm_router import LLMRouter
from packages.llm_router.providers import LLMRequest

ENGINE_NAME = "legal_engine.argument_validity"


def _fabrication_row(c: Any) -> "HallucinationTableRow":
    """사건번호가 성립할 수 없는 경우. 여기서는 단정해도 된다."""
    return HallucinationTableRow(
        location=f"{c.page or 1}면",
        claim_text=c.context[:150] if c.context else f"{c.raw_text}에 기반한 법률적 주장",
        cited_authority=c.raw_text,
        authority_exists=False,
        basis="FABRICATION_SUSPECTED",
        ai_generation_basis=("사건번호 자체가 성립할 수 없음(있을 수 없는 연도 또는 재판예규에 없는 "
                             "사건부호). 공식 DB 수록 여부와 무관하게 실재할 수 없는 표기임."),
        validity_verdict="근거 결여 (성립 불가한 사건번호)",
        legal_reasoning=("실재할 수 없는 사건번호를 전제로 하고 있어 법리적 타당성을 인정할 수 "
                         "없습니다. 임의 생성(환각)이 의심됩니다."),
        recommended_counteraction="상대방에게 판결문 사본 제출 또는 사건번호 정정 석명을 신청할 것.",
    )


def _fabrication_finding(c: Any, doc: Any) -> Finding:
    feats = {"deterministic_rule": True, "impossible_case_number": c.raw_text}
    return Finding.create(
        type=FindingType.LEGAL_ARGUMENT_INVALID,
        status=VerificationStatus.SUSPICIOUS,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.B,
        title=f"성립할 수 없는 사건번호에 근거한 법률 주장: {c.raw_text}",
        detail=("사건번호의 연도 또는 사건부호가 실재할 수 없는 값입니다. 공식 DB 수록 여부와 "
                "무관하게 그 표기로는 사건이 존재할 수 없습니다."),
        confidence=confidence_score(feats),
        confidence_features=feats,
        document_id=doc.document_id,
        page=c.page,
        engine=ENGINE_NAME,
        tags=["LEGAL", "ARGUMENT_VALIDITY", "AI_HALLUCINATION"],
    )


def _basis_for(citation: Any, status: str) -> str:
    """표에 오른 이유를 가른다.

    확인하지 못한 것을 허위라고 부르지 않는다. 공식 DB는 모든 재판을 수록하지
    않으므로 미확인은 미확인일 뿐이다. 다만 사건번호 자체가 성립할 수 없으면
    (있을 수 없는 연도, 알려지지 않은 사건부호) 그것은 적극적 근거가 된다.
    """
    if not case_number_possible(citation.canonical_case_number or citation.case_number or ""):
        return "FABRICATION_SUSPECTED"
    return "CONTENT_MISMATCH" if status == "CONTRADICTED" else "UNCONFIRMED"


@dataclass
class HallucinationTableRow:
    """AI 임의 생성 의심 내용 및 법률 주장 타당성 검토 대조표의 단일 행."""

    location: str                   # 위치 (예: 2페이지 3단락)
    claim_text: str                 # 문서에 기재된 법률적 주장
    cited_authority: str            # 인용된 판례/조문/문헌
    authority_exists: bool          # 공식 기록으로 확인되었는지 (False는 "확인 못 함"이지 "없음"이 아니다)
    ai_generation_basis: str        # AI 임의 생성으로 판단되는 근거
    validity_verdict: str           # 주장 타당성 평가 (타당 / 부당 / 근거결여 / 검토필요)
    legal_reasoning: str            # 법리적 타당성 검토 및 반박 근거
    recommended_counteraction: str  # 실무상 대응 방안 및 반박 논거
    # 왜 표에 올랐는지. 확인 못 한 것과 내용이 다른 것은 전혀 다른 사안이다.
    #   UNCONFIRMED    공식 DB에서 같은 사건번호를 찾지 못했다(부존재 단정 불가)
    #   CONTENT_MISMATCH 사건은 있으나 인용 내용이 공식 기록과 다르다
    #   FABRICATION_SUSPECTED 형식 자체가 성립하지 않는 등 적극적 근거가 있다
    basis: str = "UNCONFIRMED"

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
            "basis": self.basis,
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
                # 조회에서 사건번호를 찾지 못한 것과, 사건은 있으나 인용 내용이
                # 다른 것은 실무상 대응이 정반대다. 끝까지 구분한다.
                "basis": _basis_for(citation, status),
                "context": citation.context or doc.full_text[max(0, citation.span[0] - 200) : min(len(doc.full_text), citation.span[1] + 200)] if citation.span else "",
            })

    # 2. 가짜 판례가 하나도 없고 주장도 없으면 기본 정상 반환
    if not unverified_cases and not claims:
        result.overall_validity_summary = "공식 소스에서 확인되지 않은 인용이나 중대한 법률 주장 결함이 발견되지 않았습니다."
        return result

    # 3. LLM(OpenAI/Gemini)을 활용한 심층 법률 타당성 검토
    can_use_llm = False
    if router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY:
        if hasattr(router, "has_available_provider"):
            can_use_llm = router.has_available_provider(policy=external_ai_policy)
        elif hasattr(router, "available_providers"):
            can_use_llm = len(router.available_providers(policy=external_ai_policy)) > 0

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
            provider = (
                router.primary(policy=external_ai_policy)
                if hasattr(router, "primary")
                else (router.pick(LLMRole.PRIMARY_REASONER, policy=external_ai_policy) if hasattr(router, "pick") else None)
            )
            if not provider:
                raise RuntimeError("No LLM provider available")
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
    #
    # 여기서 "부존재"를 단정하지 않는다. 조회가 성공했고 같은 사건번호가 없었다는
    # 사실은 "공식 DB에 없다"까지만 말해 준다. 국가법령정보 판례 DB는 모든 재판을
    # 수록하지 않으며, 미공개 결정·하급심·최신 사건은 빠져 있을 수 있다. 실재하는
    # 판례를 "가공의 판례"로 적어 두면 그 서면을 쓴 변호사에게 실제 손해가 간다.
    # 판정을 만든 verifier도 "'존재하지 않는 판례'라고 단정하지 않는다"고 적었다.
    for item in unverified_cases:
        c = item["citation"]
        basis = item.get("basis", "UNCONFIRMED")
        mismatch = basis == "CONTENT_MISMATCH"
        if basis == "FABRICATION_SUSPECTED":
            result.rows.append(_fabrication_row(c))
            result.findings.append(_fabrication_finding(c, doc))
            continue
        row = HallucinationTableRow(
            location=f"{c.page or 1}면",
            claim_text=c.context[:150] if c.context else f"{c.raw_text}에 기반한 법률적 주장",
            cited_authority=c.raw_text,
            authority_exists=False,
            basis=item.get("basis", "UNCONFIRMED"),
            ai_generation_basis=(
                "공식 기록은 조회되었으나 인용된 내용이 공식 기록과 일치하지 않음. "
                "인용 오류·발췌 왜곡·임의 생성 가능성을 모두 열어 두고 원문과 대조가 필요함."
                if mismatch else
                "국가법령정보 공식 DB 검색 결과 같은 사건번호의 기록을 확인하지 못함. "
                "공식 DB는 모든 재판을 수록하지 않으므로(미공개·수록범위 밖) 이 사실만으로 "
                "부존재나 임의 생성으로 단정하지 않음."),
            validity_verdict="인용 내용 불일치 (원문 대조 필요)" if mismatch else "공식 DB 미확인 (원문 확인 필요)",
            legal_reasoning=(
                "사건 자체는 확인되나 인용 내용이 공식 기록과 달라, 그 취지를 전제로 한 주장은 "
                "원문 대조 전까지 근거가 확정되지 않습니다."
                if mismatch else
                "공식 DB에서 확인하지 못한 판례를 근거로 삼고 있어, 원문을 확인하기 전까지 "
                "그 주장의 근거가 확정되지 않습니다. 판례가 존재하지 않는다는 뜻은 아닙니다."),
            recommended_counteraction=(
                "공식 기록 원문과 인용 부분을 대조하고, 차이가 있으면 정확한 판시사항으로 "
                "정정하거나 그 취지가 주장을 뒷받침하는지 다시 검토해야 함."
                if mismatch else
                "판결문 사본 또는 출처를 확인하고, 대법원 종합법률정보 등 다른 공식 경로에서도 "
                "조회해 볼 것. 어느 경로에서도 확인되지 않을 때 비로소 부존재를 다툴 수 있음."),
        )
        result.rows.append(row)

        feats = {"deterministic_rule": True, "unconfirmed_citation": c.raw_text}
        result.findings.append(
            Finding.create(
                type=FindingType.LEGAL_ARGUMENT_INVALID,
                status=VerificationStatus.UNVERIFIED,
                severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.C,
                title=(f"인용 내용이 공식 기록과 다른 판례: {c.raw_text}" if mismatch
                       else f"공식 DB에서 확인되지 않은 판례 인용: {c.raw_text}"),
                detail=("사건은 확인되나 인용 내용이 공식 기록과 다릅니다. 원문 대조가 필요합니다."
                        if mismatch else
                        "공식 DB에서 같은 사건번호를 확인하지 못했습니다. 공식 DB는 모든 재판을 "
                        "수록하지 않으므로 이 사실만으로 부존재나 임의 생성으로 단정하지 않습니다. "
                        "원문 확인이 필요합니다."),
                confidence=confidence_score(feats),
                confidence_features=feats,
                document_id=doc.document_id,
                page=c.page,
                engine=ENGINE_NAME,
                # 확인하지 못한 것을 환각으로 분류하지 않는다. 적극적 근거가
                # 있을 때만 AI_HALLUCINATION을 붙인다.
                tags=["LEGAL", "ARGUMENT_VALIDITY", "SOURCE_UNCONFIRMED"],
            )
        )

    if result.rows:
        result.overall_validity_summary = f"공식 DB에서 확인되지 않는 가짜 판례가 {len(result.rows)}건 인용되어, 이에 기초한 법률적 주장의 타당성에 중대한 결함이 있습니다."
    else:
        result.overall_validity_summary = "중대한 법률적 주장 결함이 발견되지 않았습니다."

    return result
