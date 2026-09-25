"""법률적 주장 타당성 검토 및 AI 임의 생성(환각) 대조표 생성 엔진 (제9·11장 확장).

문서에 인용된 판례 중 공식 DB에서 확인되지 않는 가짜 판례(할루시네이션)가
어떤 법률적 주장의 근거로 쓰였는지 추적하고, 해당 주장의 대한민국 법리상 타당성 여부와
구체적 반박 근거를 분석하여 가시적인 대조표(Table) 형태로 도출한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    EvidenceGrade,
    ExternalAIPolicy,
    FindingType,
    LLMRole,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Citation, Claim, Finding, NormalizedDocument
from packages.legal_engine.normalize import case_number_possible
from packages.legal_engine.reasoning_format import format_counteraction, format_reasoning, reasoning_sections
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
        # 인용 오류의 근거이지 작성 주체(AI 사용 여부)의 근거가 아니다. 사람도 이런 오류를 만든다.
        ai_generation_basis=("사건번호 자체가 성립할 수 없음(있을 수 없는 연도 또는 재판예규에 없는 "
                             "사건부호). 공식 DB 수록 여부와 무관하게 실재할 수 없는 표기임. "
                             "법률 인용 오류의 근거이며, 이것만으로 AI 작성 여부를 추정하지 않음."),
        validity_verdict="근거 결여 (성립 불가한 사건번호)",
        legal_reasoning=("실재할 수 없는 사건번호를 전제로 하고 있어 그 판례를 근거로 한 부분은 "
                         "법리적 타당성을 인정할 수 없습니다. 오기(誤記)인지 원문 확인이 필요합니다."),
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
                "무관하게 그 표기로는 사건이 존재할 수 없습니다. 법률 인용 오류이며 작성 주체의 "
                "근거로 쓰지 않습니다."),
        confidence=confidence_score(feats),
        confidence_features={**feats, "citation_id": c.citation_id, "error_category": "LEGAL_CITATION_ERROR"},
        document_id=doc.document_id,
        page=c.page,
        engine=ENGINE_NAME,
        tags=["LEGAL", "ARGUMENT_VALIDITY", "CITATION_ERROR"],
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
    item_id: int = 0
    # 모델별 참고 의견. 판정(basis·Finding)에는 쓰지 않는다.
    ai_opinions: List[Dict[str, Any]] = field(default_factory=list)
    ai_agreement: str = "NONE"   # AGREE / DISAGREE / SINGLE / NONE
    # 표시용: 모델 의견을 붙이기 전의 검토 문장과 교차검증 요약. 칸 안을 항목별로 줄 나눠 그리는 데 쓴다.
    review_text: str = ""
    ai_label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        review = self.review_text or self.legal_reasoning
        opinions = self.ai_opinions if self.ai_label else []
        return {
            "ai_opinions": self.ai_opinions,
            "ai_agreement": self.ai_agreement,
            # 검토 결과·AI 교차검증 요약·모델별 의견을 나눈 구조(웹 화면이 항목별로 그린다)
            "reasoning_sections": reasoning_sections(review, self.ai_label, opinions),
            "location": self.location,
            "claim_text": self.claim_text,
            "cited_authority": self.cited_authority,
            "authority_exists": self.authority_exists,
            "ai_generation_basis": self.ai_generation_basis,
            "validity_verdict": self.validity_verdict,
            "legal_reasoning": format_reasoning(review, self.ai_label, opinions),
            "recommended_counteraction": self.recommended_counteraction,
            "basis": self.basis,
            # 이 표는 '법률 인용 오류'와 '근거가 확인되지 않은 주장'을 다룬다. 작성 주체(AI 사용
            # 여부)는 별도 축에서 판단하며, 이 표의 항목을 그 근거로 쓰지 않는다.
            "error_category": ("LEGAL_CITATION_ERROR" if self.basis in ("FABRICATION_SUSPECTED", "CONTENT_MISMATCH")
                               else "UNSUPPORTED_LEGAL_BASIS"),
            "authorship_evidence": False,
        }


@dataclass
class ArgumentValidityResult:
    rows: List[HallucinationTableRow] = field(default_factory=list)
    overall_validity_summary: str = ""
    findings: List[Finding] = field(default_factory=list)
    ai_summary: str = ""
    ai_providers: List[str] = field(default_factory=list)
    ai_failures: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "overall_validity_summary": self.overall_validity_summary,
            "findings_count": len(self.findings),
            "ai_providers": self.ai_providers,
            "ai_failures": self.ai_failures,
        }


async def verify_argument_validity(
    doc: NormalizedDocument,
    citations: List[Citation],
    legal_verdicts: List[Dict[str, Any]],
    claims: List[Claim],
    *,
    router: Optional[LLMRouter] = None,
    external_ai_policy: ExternalAIPolicy = ExternalAIPolicy.MASKED,
    mask: Optional[Callable[[str], str]] = None,
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
        if (status in ("NOT_FOUND", "CONTRADICTED") or levels.get("level1") == "NOT_FOUND"
                or levels.get("number_format") == "IMPOSSIBLE"):
            unverified_cases.append({
                "citation": citation,
                "verdict": verdict,
                # 조회에서 사건번호를 찾지 못한 것과, 사건은 있으나 인용 내용이
                # 다른 것은 실무상 대응이 정반대다. 끝까지 구분한다.
                "basis": _basis_for(citation, status),
                "quote_diff": (verdict.get("review") or {}).get("quote_diff"),
                "context": citation.context or doc.full_text[max(0, citation.span[0] - 200) : min(len(doc.full_text), citation.span[1] + 200)] if citation.span else "",
            })

    # 2. 가짜 판례가 하나도 없고 주장도 없으면 기본 정상 반환
    if not unverified_cases and not claims:
        result.overall_validity_summary = "공식 소스에서 확인되지 않은 인용이나 중대한 법률 주장 결함이 발견되지 않았습니다."
        return result

    # 3. 판정은 규칙 기반으로만 만든다.
    #
    # 여기서 "부존재"를 단정하지 않는다. 조회가 성공했고 같은 사건번호가 없었다는
    # 사실은 "공식 DB에 없다"까지만 말해 준다. 국가법령정보 판례 DB는 모든 재판을
    # 수록하지 않으며, 미공개 결정·하급심·최신 사건은 빠져 있을 수 있다. 실재하는
    # 판례를 "가공의 판례"로 적어 두면 그 서면을 쓴 변호사에게 실제 손해가 간다.
    # 판정을 만든 verifier도 "'존재하지 않는 판례'라고 단정하지 않는다"고 적었다.
    for index, item in enumerate(unverified_cases, 1):
        c = item["citation"]
        basis = item.get("basis", "UNCONFIRMED")
        mismatch = basis == "CONTENT_MISMATCH"
        if basis == "FABRICATION_SUSPECTED":
            row = _fabrication_row(c)
            row.item_id = index
            result.rows.append(row)
            result.findings.append(_fabrication_finding(c, doc))
            continue
        row = HallucinationTableRow(
            location=f"{c.page or 1}면",
            claim_text=c.context[:150] if c.context else f"{c.raw_text}에 기반한 법률적 주장",
            cited_authority=c.raw_text,
            authority_exists=False,
            basis=item.get("basis", "UNCONFIRMED"),
            ai_generation_basis=(
                ("공식 기록은 조회되었으나 인용된 내용이 공식 기록과 일치하지 않음. "
                 + (f"원문과 다른 어절: {item['quote_diff']}. " if item.get("quote_diff") else "")
                 + "인용 오류·발췌 왜곡·임의 생성 가능성을 모두 열어 두고 원문과 대조가 필요함.")
                if mismatch else
                "국가법령정보 공식 DB 검색 결과 같은 사건번호의 기록을 확인하지 못함. "
                "공식 DB는 모든 재판을 수록하지 않으므로(미공개·수록범위 밖) 이 사실만으로 "
                "부존재나 임의 생성으로 단정하지 않음."),
            validity_verdict=("인용문 변형 (원문과 어절 차이)" if mismatch and item.get("quote_diff")
                              else "인용 내용 불일치 (원문 대조 필요)") if mismatch else "공식 DB 미확인 (원문 확인 필요)",
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
        row.item_id = index
        result.rows.append(row)

        feats = {"deterministic_rule": True, "unconfirmed_citation": c.raw_text, "citation_id": c.citation_id,
                 "error_category": "LEGAL_CITATION_ERROR" if mismatch else "UNSUPPORTED_LEGAL_BASIS"}
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

    # 4. AI 교차검토(참고). 판정·심각도는 바꾸지 않는다.
    #
    # 예전에는 모델에게 "존재하지 않는 가공의 판례"라고 전제를 주고, 그 답을
    # 그대로 '허위 판례에 근거한 주장(CONTRADICTED·HIGH)'으로 기록했다. 조회가
    # 잠시 실패한 실재 판례도 모델 하나의 말로 허위가 됐다. 이제 모델에게는
    # 확인 상태를 사실대로 알리고, 사용 가능한 모델 모두의 의견을 모아 일치
    # 여부와 함께 참고 의견으로만 붙인다.
    can_use_llm = bool(router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY
                       and hasattr(router, "consult_all")
                       and router.has_available_provider(policy=external_ai_policy))
    if can_use_llm and unverified_cases:
        await _attach_ai_opinions(result, unverified_cases, router, external_ai_policy, mask)

    if result.rows:
        counts = {basis: sum(r.basis == basis for r in result.rows)
                  for basis in ("FABRICATION_SUSPECTED", "CONTENT_MISMATCH", "UNCONFIRMED")}
        parts = [f"성립할 수 없는 사건번호 {counts['FABRICATION_SUSPECTED']}건" if counts["FABRICATION_SUSPECTED"] else "",
                 f"인용 내용이 공식 기록과 다른 판례 {counts['CONTENT_MISMATCH']}건" if counts["CONTENT_MISMATCH"] else "",
                 f"공식 DB에서 확인되지 않은 판례 {counts['UNCONFIRMED']}건" if counts["UNCONFIRMED"] else ""]
        summary = ", ".join(p for p in parts if p) + "을(를) 근거로 한 주장이 있습니다. "
        summary += ("미확인은 부존재를 뜻하지 않으므로 원문 확인이 필요합니다."
                    if counts["UNCONFIRMED"] else "원문 대조가 필요합니다.")
        if result.ai_summary:
            summary += f" {result.ai_summary}"
        result.overall_validity_summary = summary
    else:
        result.overall_validity_summary = "중대한 법률적 주장 결함이 발견되지 않았습니다."

    return result


_BASIS_LABEL = {
    "UNCONFIRMED": "공식 DB에서 같은 사건번호를 찾지 못함(공식 DB는 모든 재판을 수록하지 않으므로 부존재를 뜻하지 않음)",
    "CONTENT_MISMATCH": "사건은 확인되나 인용 내용이 공식 기록과 다름",
    "FABRICATION_SUSPECTED": "사건번호 형식상 성립할 수 없음(있을 수 없는 연도 또는 사건부호)",
}

# 한 요청에 묻는 인용 수. 인용 1건에 Anthropic이 약 900토큰을 썼다(실측).
_OPINION_BATCH = 4

_OPINION_SCHEMA = {
    "type": "object",
    "required": ["rows"],
    "properties": {
        "overall_summary": {"type": "string"},
        "rows": {"type": "array", "items": {
            "type": "object",
            "required": ["item_id", "validity_verdict"],
            "properties": {
                "item_id": {"type": ["integer", "string"]},
                "claim_text": {"type": "string"},
                "validity_verdict": {"type": "string"},
                "legal_reasoning": {"type": "string"},
                "recommended_check": {"type": "string"},
            },
        }},
    },
}

_OPINION_SYSTEM = (
    "대한민국 법률 서면 검토를 보조한다. 각 항목의 인용 판례에는 국가법령정보 공식 판례 DB 조회 결과가 "
    "'확인 상태'로 적혀 있다. 확인 상태는 사실로 받아들이되 그 이상을 추정하지 마라. 특히 공식 DB에서 "
    "찾지 못했다는 사실만으로 판례가 존재하지 않는다거나 AI가 지어냈다고 단정하지 마라. 새로운 판례·조문·"
    "사건번호를 지어내지 마라. '원문 대조' 항목이 있으면 문서의 인용문이 공식 원문과 어절 단위로 어떻게 "
    "다른지 보여 준다. 이때는 문서의 인용문이 아니라 공식 원문의 표현을 기준으로 주장의 타당성을 평가하라.\n"
    "각 항목에 대해 (1) 작성자가 그 인용으로 뒷받침하려는 법률적 주장, (2) 그 인용을 빼고 볼 때 그 주장이 "
    "대한민국 실정법과 확립된 법리에 비추어 타당한지, (3) 확인하거나 다툴 때 검토할 사항을 적어라.\n"
    "validity_verdict는 '타당', '일부 타당', '부당', '판단 불가' 중 하나로 적어라.\n"
    "분량: claim_text 100자, legal_reasoning 300자, recommended_check 150자, overall_summary 200자 이내. "
    "주민등록번호 등 개인 식별번호와 인터넷 주소(URL)는 쓰지 마라(응답이 보안 검사에서 격리된다). "
    "JSON 객체 하나만 답하라:\n"
    '{"overall_summary": "...", "rows": [{"item_id": 1, "claim_text": "...", "validity_verdict": "...", '
    '"legal_reasoning": "...", "recommended_check": "..."}]}'
)


async def _attach_ai_opinions(result: ArgumentValidityResult, unverified_cases: List[Dict[str, Any]],
                              router: Any, policy: ExternalAIPolicy,
                              mask: Optional[Callable[[str], str]]) -> None:
    """사용 가능한 모델 모두에게 묻고, 항목별 의견과 일치 여부를 행에 붙인다."""
    from packages.llm_router.providers import _extract_json

    from packages.llm_router.router import failure_summary

    hide = mask or (lambda text: text)
    items = [{
        "item_id": index,
        "page": item["citation"].page or 1,
        "cited_case": hide(item["citation"].raw_text),
        "확인 상태": _BASIS_LABEL.get(item.get("basis", "UNCONFIRMED"), _BASIS_LABEL["UNCONFIRMED"]),
        "surrounding_context_and_claim": hide(item["context"][:1000]),
        **({"원문 대조(어절 단위, 원문 기준)": hide(item["quote_diff"])} if item.get("quote_diff") else {}),
    } for index, item in enumerate(unverified_cases, 1)]
    # 한 번에 모두 물으면 인용이 많을 때 응답이 출력 한도에서 잘린다. 한국어 JSON은
    # 공급자마다 토큰 사용량이 달라, 잘리는 모델만 교차검증에서 빠졌다.
    answers = []
    for start in range(0, len(items), _OPINION_BATCH):
        request = LLMRequest(system=_OPINION_SYSTEM,
                             user=json.dumps({"items": items[start:start + _OPINION_BATCH]}, ensure_ascii=False),
                             temperature=0.1, max_tokens=4096, schema=_OPINION_SCHEMA)
        try:
            answers += await router.consult_all(LLMRole.PRIMARY_REASONER, request, policy=policy,
                                                expected_task="법률 주장 타당성 검토")
        except Exception as exc:  # 참고 의견이 없어도 판정은 이미 끝났다.
            result.ai_summary = f"AI 교차검토를 수행하지 못함({type(exc).__name__})."
            return

    opinions_by_item: Dict[int, List[Dict[str, Any]]] = {}
    summaries, used = [], []
    failures = failure_summary(answers)
    for answer in answers:
        execution = next((e for e in reversed(answer.executions) if getattr(e, "provider", "")), None)
        provider = getattr(execution, "provider", "") or "unknown"
        if not answer.used:
            continue
        parsed = answer.parsed or _extract_json(answer.text) or {}
        used.append(provider)
        if parsed.get("overall_summary"):
            summaries.append(f"{provider}: {str(parsed['overall_summary'])[:300]}")
        for row in parsed.get("rows") or []:
            try:
                item_id = int(row.get("item_id"))
            except (TypeError, ValueError):
                continue
            opinions_by_item.setdefault(item_id, []).append({
                "provider": provider,
                "model": getattr(execution, "model", ""),
                "claim_text": str(row.get("claim_text") or "")[:400],
                "verdict": str(row.get("validity_verdict") or "판단 불가")[:40],
                "reasoning": str(row.get("legal_reasoning") or "")[:800],
                "check": str(row.get("recommended_check") or "")[:400],
            })

    agree = disagree = 0
    for row in result.rows:
        opinions = opinions_by_item.get(row.item_id, [])
        row.ai_opinions = opinions
        verdicts = {o["verdict"] for o in opinions}
        if not opinions:
            row.ai_agreement = "NONE"
            continue
        if len(opinions) == 1:
            missing = ", ".join(f"{n}({why})" for n, why in sorted(failures.items())
                                if n != opinions[0]["provider"])
            row.ai_agreement = "SINGLE"
            label = f"1개 모델({opinions[0]['provider']}) 의견(교차검증 아님)" + (
                f" — 응답하지 못한 모델: {missing}" if missing else "")
        elif len(verdicts) == 1:
            row.ai_agreement, label = "AGREE", f"{len(opinions)}개 모델 의견 일치"
            agree += 1
        else:
            row.ai_agreement, label = "DISAGREE", f"{len(opinions)}개 모델 의견 불일치 — 직접 검토 필요"
            disagree += 1
        # 검토 결과 / AI 교차검증 요약 / 모델별 판정·근거를 줄마다 나눠 적는다(reasoning_format)
        row.review_text = row.review_text or row.legal_reasoning
        row.ai_label = label
        row.legal_reasoning = format_reasoning(row.review_text, label, opinions)
        row.recommended_counteraction = format_counteraction(row.recommended_counteraction, opinions)

    result.ai_providers = sorted(set(used))
    if used:
        result.ai_summary = (f"AI 교차검토(참고): {len(set(used))}개 모델({', '.join(sorted(set(used)))}) 참여, "
                             f"의견 일치 {agree}건·불일치 {disagree}건. 판정에는 반영하지 않음.")
        missing = {n: why for n, why in failures.items() if n not in used}
        if missing:
            result.ai_summary += " 응답하지 못한 모델: " + ", ".join(
                f"{n}({why})" for n, why in sorted(missing.items())) + "."
    else:
        result.ai_summary = "AI 교차검토를 수행하지 못함(" + (
            ", ".join(f"{n}: {why}" for n, why in sorted(failures.items())) or "응답한 모델 없음") + ")."
    result.ai_failures = failures
