"""법률적 주장 타당성 검토 및 AI 임의 생성(환각) 대조표 생성 엔진 (제9·11장 확장).

문서에 인용된 판례 중 공식 DB에서 확인되지 않는 가짜 판례(할루시네이션)가
어떤 법률적 주장의 근거로 쓰였는지 추적하고, 해당 주장의 대한민국 법리상 타당성 여부와
구체적 반박 근거를 분석하여 가시적인 대조표(Table) 형태로 도출한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    CitationType,
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


def _context_review(verdict, reviews, mask=None):
    """Reuse only the grounded review of this citation and official record, never infer from status alone."""
    result = {"status": "UNVERIFIED", "advisory_only": True, "opinions": [],
              "reason": "공식 원문에 근거한 의미·맥락 검토가 완료되지 않아 취지 동일 여부는 판단 유보합니다."}
    source = str((verdict.get("official_record") or {}).get("full_text") or "")
    if mask and source:
        source = mask(source)
    for review in reviews:
        if (review.get("citation_id") != verdict.get("citation_id")
                or review.get("review_id") != verdict.get("review_id")):
            continue
        result["reason"] = review.get("reason") or result["reason"]
        quotes = review.get("evidence_quotes") or []
        if not (source and review.get("model_executed") and review.get("source_quotes_validated")
                and quotes and all(isinstance(q, str) and q.strip() and q in source for q in quotes)):
            result["reason"] = "공식 원문과 근거 인용을 확인하지 못해 취지 동일 여부는 판단 유보합니다."
            continue
        opinions = []
        for stage in review.get("stages") or []:
            opinion = stage.get("verdict") or {}
            evidence = opinion.get("evidence_quotes") or []
            if (stage.get("used") and opinion.get("rationale") and evidence
                    and all(isinstance(q, str) and q.strip() and q in source for q in evidence)):
                opinions.append({"stage": stage.get("name", "model"), "status": opinion.get("status"),
                                 "rationale": opinion["rationale"], "evidence_quotes": evidence})
        if opinions:
            result.update(status="ADVISORY_REVIEWED", opinions=opinions,
                          source_record_ids=review.get("source_record_ids", []),
                          source_truncated=bool(review.get("source_truncated")), source_quotes_validated=True)
        break
    return result


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
    citation_id: str = ""
    context_review: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        review = self.review_text or self.legal_reasoning
        opinions = self.ai_opinions if self.ai_label else []
        return {
            "citation_id": self.citation_id,
            "context_review": self.context_review,
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
            "error_category": ("CITATION_CONTRADICTION" if self.basis == "CONTRADICTION"
                               else "APPLICATION_DIFFERENCE" if self.basis == "DISTINGUISHABLE"
                               else "LEGAL_CITATION_ERROR" if self.basis in ("FABRICATION_SUSPECTED", "CONTENT_MISMATCH")
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


def _extract_linked_claim(citation: Citation, doc: NormalizedDocument) -> str:
    """인용 판례와 직접 연결된 법률적 주장 문장을 추출한다.

    앞 문단의 인적사항이나 의료정보 등 무관한 내용이 잘려 들어가지 않도록
    줄바꿈(\\n) 및 문장 경계를 엄격히 준수한다.
    """
    raw_text = citation.raw_text or ""
    case_no = citation.case_number or citation.canonical_case_number or ""

    # 1. context가 있을 때 줄바꿈 기준 인용구 속한 줄(문단) 우선 추출
    if citation.context:
        lines = [line.strip() for line in citation.context.split("\n") if line.strip()]
        target_line = ""
        for line in lines:
            if (raw_text and raw_text in line) or (case_no and case_no in line):
                target_line = line
                break
        if not target_line and lines:
            target_line = lines[-1]

        if target_line:
            # 문단 내에서 문장 단위 분리
            sentences = re.split(r"(?<=[.?!])\s+", target_line)
            matched = [s for s in sentences if (raw_text and raw_text in s) or (case_no and case_no in s)]
            if matched:
                return " ".join(matched)[:200].strip()
            return target_line[:200].strip()

    # 2. span 정보 기반 전체 텍스트에서 해당 문단 영역 슬라이싱
    full_text = getattr(doc, "full_text", "") or ""
    if citation.span and full_text:
        start, end = citation.span
        prev_newline = full_text.rfind("\n", 0, start)
        para_start = prev_newline + 1 if prev_newline != -1 else max(0, start - 150)
        next_newline = full_text.find("\n", end)
        para_end = next_newline if next_newline != -1 else min(len(full_text), end + 200)
        para_text = full_text[para_start:para_end].strip()
        if para_text:
            return para_text[:200].strip()

    return f"{raw_text}에 기반한 법률적 주장"


async def verify_argument_validity(
    doc: NormalizedDocument,
    citations: List[Citation],
    legal_verdicts: List[Dict[str, Any]],
    claims: List[Claim],
    *,
    router: Optional[LLMRouter] = None,
    external_ai_policy: ExternalAIPolicy = ExternalAIPolicy.MASKED,
    mask: Optional[Callable[[str], str]] = None,
    semantic_reviews: Optional[List[Dict[str, Any]]] = None,
) -> ArgumentValidityResult:
    """허위 판례 인용 및 법률 주장에 대한 타당성 종합 검토를 수행하고 대조표를 생성한다."""
    result = ArgumentValidityResult()

    # 1. 공식 DB에서 미확인된(가짜) 판례, 불일치 판례, 및 시맨틱 검토 결과(취지 모순·적용 차이) 선별
    unverified_cases: List[Dict[str, Any]] = []
    citation_by_id = {c.citation_id: c for c in citations}
    sem_by_cid = {r.get("citation_id"): r for r in (semantic_reviews or [])}

    for verdict in legal_verdicts:
        cid = verdict.get("citation_id")
        citation = citation_by_id.get(cid)
        if not citation:
            continue

        status = str(verdict.get("status", ""))
        levels = verdict.get("levels", {})
        sem_rev = sem_by_cid.get(cid)
        sem_status = str(sem_rev.get("status", "")) if sem_rev and sem_rev.get("source_quotes_validated") else ""

        # 판례가 공식 소스에서 발견되지 않았거나(NOT_FOUND), 심각한 불일치가 있거나,
        # 시맨틱 검토에서 판례 취지 왜곡(CONTRADICTED) 또는 사실관계 적용 차이(DISTINGUISHABLE)가 확인된 경우
        is_unverified = (status in ("NOT_FOUND", "CONTRADICTED") or levels.get("level1") == "NOT_FOUND"
                         or levels.get("number_format") == "IMPOSSIBLE")
        is_semantic_issue = sem_status in ("CONTRADICTED", "DISTINGUISHABLE")
        # 공식 DB에서 원문이 일치 확인된 판례도 대조표에 포함(사건 적용성은 직접 검토 안내)
        is_official_confirmed = (
            citation.type in (CitationType.CASE, CitationType.CONSTITUTIONAL)
            and status in ("VERIFIED", "PARTIALLY_VERIFIED")
            and not is_unverified
            and not is_semantic_issue
            and bool(verdict.get("official_record"))
        )

        if is_unverified or is_semantic_issue or is_official_confirmed:
            if is_official_confirmed:
                basis = "OFFICIAL_CONFIRMED"
            elif not case_number_possible(citation.canonical_case_number or citation.case_number or ""):
                basis = "FABRICATION_SUSPECTED"
            elif sem_status == "CONTRADICTED":
                basis = "CONTRADICTION"
            elif sem_status == "DISTINGUISHABLE":
                basis = "DISTINGUISHABLE"
            elif status == "CONTRADICTED":
                basis = "CONTENT_MISMATCH"
            else:
                basis = "UNCONFIRMED"

            unverified_cases.append({
                "citation": citation,
                "verdict": verdict,
                "basis": basis,
                "sem_status": sem_status,
                "sem_review": sem_rev,
                "quote_diff": (verdict.get("review") or {}).get("quote_diff"),
                "context": citation.context or doc.full_text[max(0, citation.span[0] - 200) : min(len(doc.full_text), citation.span[1] + 200)] if citation.span else "",
            })

    # 2. 가짜 판례가 하나도 없고 주장도 없으면 기본 정상 반환
    if not unverified_cases and not claims:
        result.overall_validity_summary = "인용 근거 대조표에 표시할 항목이 없습니다. 법률 주장 전체의 적정성이 확인되었다는 뜻은 아닙니다."
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
        contradiction = basis == "CONTRADICTION"
        distinguishable = basis == "DISTINGUISHABLE"
        sem_rev = item.get("sem_review") or {}
        sem_reason = str(sem_rev.get("reason") or "")

        if basis == "FABRICATION_SUSPECTED":
            row = _fabrication_row(c)
            row.item_id = index
            row.citation_id = c.citation_id
            row.context_review = _context_review(item["verdict"], semantic_reviews or [], mask)
            result.rows.append(row)
            result.findings.append(_fabrication_finding(c, doc))
            continue

        statute = c.type in (CitationType.STATUTE, CitationType.ADMIN_RULE)
        noun = "법령" if statute else "판례"

        if contradiction:
            ai_basis = ("공식 판결 전문의 핵심 법리·취지와 정반대로 인용됨 (결론 뒤집힘). "
                        "단순 문구 차이가 아니라 판시사항의 부정·예외 요건을 반대로 왜곡하여 인용한 것으로 확인됨.")
            verdict_text = "판례 취지 왜곡 (판시사항과 상반 / 부당)"
            legal_reason = (sem_reason or
                            "공식 판결 전문의 취지와 정반대되는 내용으로 인용되어, 해당 판례를 근거로 한 주장은 법리적 타당성을 인정하기 어렵습니다.")
            counteraction = ("대법원 판결의 명시적 판시 취지와 정반대이므로 이를 근거로 한 주장은 철회하고, "
                             "독자적인 적법 요건이나 다른 선례를 찾아 변론을 재구성해야 함.")
        elif distinguishable:
            ai_basis = ("사건 자체는 실재하나, 원 판결의 사실관계(처분 유형·적용 법령)와 본 사안 사이에 "
                        "중대한 차이가 있음. 허위 판례가 아니므로 부존재나 임의 생성으로 단정하지 않음.")
            verdict_text = "적용 차이 (사실관계 상이 / 전문가 검토 필요)"
            legal_reason = (sem_reason or
                            "판례 사안과 본 건의 사실관계 및 법적 성격이 상이하여, 기존 판례의 법리가 본 건에 그대로 유추적용될 수 있는지 검토가 필요합니다.")
            counteraction = ("판례 사안과 본 건의 사실관계 차이를 인정하고, 신뢰보호 등 일반 행정법 원칙이 "
                             "본 사안에도 유추적용되어야 하는 구체적 당위성을 보강하여 변론할 것.")
        elif basis == "OFFICIAL_CONFIRMED":
            ai_basis = "공식DB 확인 완료 (판례 실재 및 원문 일치 — 사건 적용성은 직접 검토 필요)"
            verdict_text = "공식 원문 일치 (사건 적용성 직접 검토 필요)"
            legal_reason = (
                f"대법원 공식 판례 DB에서 {c.raw_text}의 판결 요지 및 원문 일치가 확인되었습니다. "
                f"다만, 본 판례의 법리가 당해 사건의 계약 조건(예: 감액 청구 배제 특약의 유효성, 위약벌 인정 여부 등) 및 "
                f"구체적 사실관계에 타당하게 적용되는지(사건 적용성)는 AI 작성 여부 판단과 별개로 검토자가 직접 검토해야 합니다."
            )
            counteraction = "공식 판례의 원문 취지와 당해 사건의 계약 조건(손해배상액 예정 vs 위약벌 법리 등)을 직접 비교 검토할 것."
        elif mismatch:
            ai_basis = (
                "공식 기록은 조회되었으나 인용된 내용이 공식 기록과 일치하지 않음. "
                + (f"원문과 다른 어절: {item['quote_diff']}. " if item.get("quote_diff") else "")
                + "인용 오류·발췌 왜곡·임의 생성 가능성을 모두 열어 두고 원문과 대조가 필요함."
            )
            verdict_text = ("인용문 변형 (원문과 어절 차이)" if item.get("quote_diff")
                            else "인용 내용 불일치 (원문 대조 필요)")
            legal_reason = ("사건 자체는 확인되나 인용 내용이 공식 기록과 달라, 그 취지를 전제로 한 주장은 "
                            "원문 대조 전까지 근거가 확정되지 않습니다.")
            counteraction = ("공식 기록 원문과 인용 부분을 대조하고, 차이가 있으면 정확한 판시사항으로 "
                             "정정하거나 그 취지가 주장을 뒷받침하는지 다시 검토해야 함.")
        else:
            ai_basis = (
                ("국가법령정보 법령 목록에서 같은 이름의 법령·조문을 확인하지 못함. 법령명 오기·약칭·폐지 "
                 "가능성이 있으므로 이 사실만으로 부존재나 임의 생성으로 단정하지 않음.") if statute else
                ("국가법령정보 공식 DB 검색 결과 같은 사건번호의 기록을 확인하지 못함. "
                 "공식 DB는 모든 재판을 수록하지 않으므로(미공개·수록범위 밖) 이 사실만으로 "
                 "부존재나 임의 생성으로 단정하지 않음.")
            )
            verdict_text = "공식 DB 미확인 (원문 확인 필요)"
            legal_reason = (f"공식 DB에서 확인하지 못한 {noun}을(를) 근거로 삼고 있어, 원문을 확인하기 전까지 "
                            f"그 주장의 근거가 확정되지 않습니다. {noun}이(가) 존재하지 않는다는 뜻은 아닙니다.")
            counteraction = (
                ("정식 법령명·약칭·시행 여부를 국가법령정보센터에서 다시 확인하고, 조문 원문과 대조할 것."
                 if statute else
                 "판결문 사본 또는 출처를 확인하고, 대법원 종합법률정보 등 다른 공식 경로에서도 "
                 "조회해 볼 것. 어느 경로에서도 확인되지 않을 때 비로소 부존재를 다툴 수 있음.")
            )

        linked_claim = _extract_linked_claim(c, doc)

        row = HallucinationTableRow(
            location=f"{c.page or 1}면",
            claim_text=linked_claim,
            cited_authority=c.raw_text,
            authority_exists=bool(item["verdict"].get("official_record")),
            basis=basis,
            ai_generation_basis=ai_basis,
            validity_verdict=verdict_text,
            legal_reasoning=legal_reason,
            recommended_counteraction=counteraction,
        )
        row.item_id = index
        row.citation_id = c.citation_id
        row.context_review = _context_review(item["verdict"], semantic_reviews or [], mask)
        result.rows.append(row)

        has_official = bool(item["verdict"].get("official_record"))
        feats = {
            "deterministic_rule": not (contradiction or distinguishable),
            "unconfirmed_citation": c.raw_text,
            "citation_id": c.citation_id,
            "official_source_match": has_official,
            "error_category": ("CITATION_CONTRADICTION" if contradiction
                               else "APPLICATION_DIFFERENCE" if distinguishable
                               else "LEGAL_CITATION_ERROR" if mismatch else "UNSUPPORTED_LEGAL_BASIS"),
            "semantic_status": sem_status,
        }
        finding_status = VerificationStatus.CONTRADICTED if contradiction else VerificationStatus.UNVERIFIED
        finding_severity = Severity.HIGH if contradiction else Severity.LOW if distinguishable else Severity.MEDIUM
        finding_title = (
            f"판례 취지 왜곡 인용: {c.raw_text}" if contradiction
            else f"판례 사실관계 및 적용 차이 (전문가 검토 필요): {c.raw_text}" if distinguishable
            else f"인용 내용이 공식 기록과 다른 판례: {c.raw_text}" if mismatch
            else f"공식 DB에서 확인되지 않은 {noun} 인용: {c.raw_text}"
        )
        finding_tags = ["LEGAL", "ARGUMENT_VALIDITY"] + (
            ["CONTRADICTION", "CITATION_DISTORTION"] if contradiction
            else ["DISTINGUISHABLE", "APPLICATION_DIFFERENCE"] if distinguishable
            else ["SOURCE_UNCONFIRMED"]
        )

        if basis != "OFFICIAL_CONFIRMED":
            result.findings.append(
                Finding.create(
                    type=FindingType.LEGAL_ARGUMENT_INVALID,
                    status=finding_status,
                    severity=finding_severity,
                    evidence_grade=EvidenceGrade.B if (contradiction or distinguishable) else EvidenceGrade.C,
                    title=finding_title,
                    detail=legal_reason,
                    confidence=confidence_score(feats),
                    confidence_features=feats,
                    document_id=doc.document_id,
                    page=c.page,
                    engine=ENGINE_NAME,
                    tags=finding_tags,
                    advisory_only=contradiction or distinguishable,
                )
            )

    # 4. AI 교차검토(참고). 판정·심각도는 바꾸지 않는다.
    can_use_llm = bool(router and external_ai_policy != ExternalAIPolicy.LOCAL_ONLY
                       and hasattr(router, "consult_all")
                       and router.has_available_provider(policy=external_ai_policy))
    cases_for_ai = [item for item in unverified_cases if item.get("basis") != "OFFICIAL_CONFIRMED"]
    if can_use_llm and cases_for_ai:
        await _attach_ai_opinions(result, cases_for_ai, router, external_ai_policy, mask)

    if result.rows:
        counts = {basis: sum(r.basis == basis for r in result.rows)
                  for basis in ("FABRICATION_SUSPECTED", "CONTRADICTION", "DISTINGUISHABLE", "CONTENT_MISMATCH", "UNCONFIRMED", "OFFICIAL_CONFIRMED")}
        parts = [
            f"성립할 수 없는 사건번호 {counts['FABRICATION_SUSPECTED']}건" if counts["FABRICATION_SUSPECTED"] else "",
            f"판례 취지 왜곡(상반 인용) {counts['CONTRADICTION']}건" if counts["CONTRADICTION"] else "",
            f"사실관계 및 적용 차이 {counts['DISTINGUISHABLE']}건" if counts["DISTINGUISHABLE"] else "",
            f"인용 내용이 공식 기록과 다른 판례 {counts['CONTENT_MISMATCH']}건" if counts["CONTENT_MISMATCH"] else "",
            f"공식 DB에서 확인되지 않은 판례·법령 {counts['UNCONFIRMED']}건" if counts["UNCONFIRMED"] else "",
            f"공식 DB 확인 완료(사건 적용성 직접 검토 필요) 판례 {counts['OFFICIAL_CONFIRMED']}건" if counts.get("OFFICIAL_CONFIRMED") else "",
        ]
        summary = ", ".join(p for p in parts if p) + "에 대한 검토 내용이 포함되어 있습니다. "
        if counts["UNCONFIRMED"]:
            summary += "미확인은 부존재를 뜻하지 않으므로 원문 확인이 필요합니다."
        elif counts["FABRICATION_SUSPECTED"] or counts["CONTRADICTION"] or counts["CONTENT_MISMATCH"]:
            summary += "원문 대조 및 법리 재검토가 필요합니다."
        else:
            summary += "공식 원문이 확인된 판례는 사안 적용성을 검토하십시오."
        if result.ai_summary:
            summary += f" {result.ai_summary}"
        result.overall_validity_summary = summary
    else:
        result.overall_validity_summary = "인용 근거 대조표에 표시할 항목이 없습니다. 법률 주장 전체의 적정성이 확인되었다는 뜻은 아닙니다."

    return result


def summarize_argument_findings(findings, citation_summary: str) -> Dict[str, Any]:
    """Summarize all legal claim engines, without treating silence as clearance."""
    relevant = [f for f in findings if f.type in (
        FindingType.LEGAL_ARGUMENT_INVALID, FindingType.UNSUPPORTED_GENERALIZATION,
        FindingType.OVERCLAIM, FindingType.LEGAL_REQUIREMENT_OMITTED, FindingType.REASONING_GAP)]
    contradicted = sum(f.status == VerificationStatus.CONTRADICTED for f in relevant)
    pending = len(relevant) - contradicted
    summary = (f"법률 주장 검토: 근거와 모순되는 항목 {contradicted}건, 추가 확인 필요 {pending}건. "
               if relevant else "자동 규칙으로 확인한 법률 주장 경고는 없습니다. ")
    return {"summary": summary + citation_summary,
            "scope": "DETECTED_CLAIMS_ONLY", "complete_legal_validation": False,
            "contradicted_count": contradicted, "review_required_count": pending,
            "finding_ids": [f.finding_id for f in relevant]}


_BASIS_LABEL = {
    "UNCONFIRMED": "공식 DB에서 같은 사건번호를 찾지 못함(공식 DB는 모든 재판을 수록하지 않으므로 부존재를 뜻하지 않음)",
    "CONTENT_MISMATCH": "사건은 확인되나 인용 내용이 공식 기록과 다름",
    "FABRICATION_SUSPECTED": "사건번호 형식상 성립할 수 없음(있을 수 없는 연도 또는 사건부호)",
    "CONTRADICTION": "공식 판결 전문의 핵심 법리·취지와 정반대로 인용됨(취지 왜곡)",
    "DISTINGUISHABLE": "공식 판결 사안과 문서 사안의 사실관계·적용 요건이 상이함(적용 차이 / 전문가 검토 필요)",
}

# 한 요청에 묻는 인용 수. 인용 1건에 Anthropic이 약 900토큰을 썼다(실측)는 전제로 4건씩 묻다가,
# 0.9.4 실제 실행에서 3건 묶음도 출력 한도(4096토큰)에서 잘려 그 모델이 교차검증에서 빠졌다. 2건씩 묻는다.
_OPINION_BATCH = 2

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


def _answer_provider(answer) -> str:
    execution = next((e for e in reversed(answer.executions) if getattr(e, "provider", "")), None)
    return getattr(execution, "provider", "") or ""


async def _retry_truncated_singly(router: Any, replies: List[Any], batch: List[Dict[str, Any]],
                                  policy: ExternalAIPolicy) -> List[Any]:
    if len(batch) < 2:
        return []
    providers = [p for p in (_answer_provider(a) for a in replies) if p]
    truncated = [_answer_provider(a) for a in replies if not a.used and any(
        str(getattr(e, "error", "") or "").startswith("OUTPUT_TRUNCATED") for e in a.executions)]
    out = []
    for provider in (p for p in truncated if p):
        others = [p for p in providers if p != provider]
        for item in batch:
            single = LLMRequest(system=_OPINION_SYSTEM, user=json.dumps({"items": [item]}, ensure_ascii=False),
                                temperature=0.1, max_tokens=4096, schema=_OPINION_SCHEMA,
                                input_contract="argument_review_v1")
            reply = await router.run(LLMRole.PRIMARY_REASONER, single, policy=policy, exclude=others,
                                     expected_task="법률 주장 타당성 검토")
            if _answer_provider(reply) == provider or not reply.executions:
                out.append(reply)
    return out


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
                             temperature=0.1, max_tokens=4096, schema=_OPINION_SCHEMA,
                             input_contract="argument_review_v1")
        try:
            batch = items[start:start + _OPINION_BATCH]
            replies = await router.consult_all(LLMRole.PRIMARY_REASONER, request, policy=policy,
                                               expected_task="법률 주장 타당성 검토")
            answers += replies
            # 2건 묶음도 출력 한도에서 잘린 공급자(0.9.8 실제 실행 1건)에는 그 공급자에게만 1건씩 다시 묻는다.
            answers += await _retry_truncated_singly(router, replies, batch, policy)
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
