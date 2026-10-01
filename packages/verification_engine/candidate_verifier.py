"""모델 의견 후보 제안 및 결정적 검증기 승격 엔진 (TK-09).

모델(LLM)은 결함 후보(주장 인용문, 결함 유형, 근거 인용문)를 제안하고,
결정적 검증기가 이를 엄격히 대조·검증하여 통과한 후보만 정식 Finding(SUSPICIOUS, B등급)으로 승격한다.
통과하지 못한 후보는 탈락 사유(rejected)를 남기며, 모델의 단순 주장만으로 결론을 바꾸지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "verification_engine.candidate_verifier"

# 날짜 추출 정규식: 'YYYY. M. D.', 'YYYY-MM-DD' 및 'YYYY년 M월 D일'
DATE_PATTERN = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[-.년]\s*(?P<m>\d{1,2})\s*[-.월]\s*(?P<d>\d{1,2})\s*[.일]?")


def _clean_str(s: str) -> str:
    """공백·줄바꿈을 단일 공백으로 치환하여 유연한 텍스트 대조를 지원합니다."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _contains_flexible(haystack: str, needle: str) -> bool:
    """문자열의 공백/줄바꿈 차이를 허용하는 포함 검사."""
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    return _clean_str(needle) in _clean_str(haystack)


def parse_dates_from_text(text: str) -> List[Tuple[date, str]]:
    """텍스트에서 날짜 목록을 (date 객체, 원문 표기) 튜플 형태로 추출합니다."""
    found = []
    for m in DATE_PATTERN.finditer(text or ""):
        try:
            d = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
            found.append((d, m.group(0).strip()))
        except ValueError:
            continue
    return found


@dataclass
class ModelCandidate:
    """모델이 제안한 결함 후보 데이터 클래스."""
    claim_quote: str                          # 서면 본문 주장 인용문
    defect_type: str                          # 결함 유형 (TEMPORAL_LAW_MISMATCH, STATUTE_MISMATCH 등)
    basis_quote: str                          # 근거 규정/자료/조문 인용문
    candidate_id: str = ""
    source_id: Optional[str] = None           # RAG 출처 ID (예: R01 등)
    source_title: Optional[str] = None         # 출처 제목
    law_name: Optional[str] = None            # 법령명 (해당 시)
    article: Optional[str] = None             # 조문 (해당 시)
    explanation: str = ""                     # 모델의 상세 설명
    model_name: Optional[str] = None          # 제안 모델명 (openai, anthropic, gemini 등)


def verify_rag_candidate(
    candidate: ModelCandidate,
    document_text: str,
    sources: List[Dict[str, Any]],
    document_id: Optional[str] = None,
) -> Tuple[Optional[Finding], Optional[Dict[str, str]]]:
    """RAG 기반 모델 제안 후보를 결정적으로 검증하여 정식 Finding 또는 거부 사유를 반환합니다.

    1) 서면 본문에 claim_quote가 실제로 존재하는가?
    2) 참고자료 원문에 basis_quote가 실제로 존재하는가?
    3) 두 조건 모두 충족 시 SUSPICIOUS 등급의 정식 Finding으로 승격합니다.
    """
    if not candidate.claim_quote or not candidate.claim_quote.strip():
        return None, {"candidate_id": candidate.candidate_id, "reason": "EMPTY_CLAIM_QUOTE"}

    if not _contains_flexible(document_text, candidate.claim_quote):
        return None, {"candidate_id": candidate.candidate_id, "reason": "CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT"}

    # 출처 자료 검색 및 대조
    by_id = {s.get("source_id"): s for s in sources}
    source = by_id.get(candidate.source_id) if candidate.source_id else None
    if not source and sources:
        # source_id가 없으면 전체 sources 중 basis_quote를 포함하는 소스를 탐색
        for s in sources:
            if _contains_flexible(s.get("text", ""), candidate.basis_quote):
                source = s
                break

    if not source:
        return None, {"candidate_id": candidate.candidate_id, "reason": "SOURCE_NOT_FOUND"}

    if not candidate.basis_quote or not candidate.basis_quote.strip():
        return None, {"candidate_id": candidate.candidate_id, "reason": "EMPTY_BASIS_QUOTE"}

    if not _contains_flexible(source.get("text", ""), candidate.basis_quote):
        return None, {"candidate_id": candidate.candidate_id, "reason": "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE"}

    source_title = candidate.source_title or source.get("title") or candidate.source_id or "참고자료"
    finding_title = f"참고자료 대조 모순: {source_title} — {candidate.explanation[:80]}"
    detail = (
        f"서면 주장 '{candidate.claim_quote.strip()[:120]}'이(가) 참고자료({source_title})의 "
        f"규정 '{candidate.basis_quote.strip()[:120]}'과(와) 정면으로 모순됩니다. "
        f"{candidate.explanation.strip()}"
    )

    evidences = [
        Evidence.create(
            description="서면 주장 인용 (원문 확인됨)",
            grade=EvidenceGrade.B,
            document_id=document_id,
            excerpt=candidate.claim_quote.strip()[:300],
            supports=False,
        ),
        Evidence.create(
            description=f"참고자료 규정 원문 ({source_title})",
            grade=EvidenceGrade.A,
            document_id=document_id,
            excerpt=candidate.basis_quote.strip()[:300],
            supports=True,
        ),
    ]

    finding = Finding.create(
        type=FindingType.FACT_CONTRADICTION,
        status=VerificationStatus.SUSPICIOUS,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.B,
        title=finding_title,
        detail=detail,
        confidence=0.75,
        confidence_features={
            "rule_id": "RAG.GROUNDED_CONTRADICTION",
            "candidate_id": candidate.candidate_id,
            "source_id": candidate.source_id,
            "source_title": source_title,
            "claim_quote": candidate.claim_quote,
            "basis_quote": candidate.basis_quote,
            "model_name": candidate.model_name,
            "human_review": True,
        },
        document_id=document_id,
        engine=ENGINE_NAME,
        tags=["RAG", "MODEL_CANDIDATE", "GROUNDED_CONTRADICTION"],
        advisory_only=False,  # 정식 Finding 목록에 등재
        evidence=evidences,
    )
    return finding, None


def verify_model_fact_recalculation(
    remark_text: str,
    document_text: str,
    reference_date_str: Optional[str] = None,
    document_id: Optional[str] = None,
) -> Tuple[Optional[Finding], Optional[Dict[str, str]]]:
    """모델의 사실 모순 지적을 서면 내부 날짜 및 처분/행위 시점으로 재계산하여 검증합니다.

    - 지적에 언급된 날짜들이 서면 원문에 실제로 존재하는지 확인.
    - 서면 내부의 기준일(처분일 등)과 개정·시행일 간의 선후관계 모순(처분일 < 시행일) 재계산.
    - 불변기간·제소기간 초과 또는 시점 역전 모순 재계산.
    - 재계산 검증 통과 시 SUSPICIOUS 등급의 정식 Finding으로 승격.
    """
    remark_dates = parse_dates_from_text(remark_text)
    if not remark_dates:
        return None, {"reason": "NO_DATES_IN_REMARK", "remark": remark_text}

    # 지적의 날짜가 서면 원문에 존재하는지 검증
    doc_dates = parse_dates_from_text(document_text)
    doc_date_set = {d[0] for d in doc_dates}

    grounded_dates = [d for d in remark_dates if d[0] in doc_date_set]
    if not grounded_dates:
        # 서면 원문과 일치하는 날짜가 하나도 없으면 기각
        return None, {"reason": "REMARK_DATES_NOT_IN_DOCUMENT", "remark": remark_text}

    # 1) 처분일/행위일 기준 선후관계 모순 (처분일보다 뒤에 개정/시행된 규정 적용 주장)
    ref_d = None
    if reference_date_str:
        ref_parsed = parse_dates_from_text(reference_date_str)
        if ref_parsed:
            ref_d = ref_parsed[0][0]

    # 모순 확인 플래그
    is_contradiction = False
    finding_type = FindingType.TEMPORAL_LAW_MISMATCH
    reason_note = ""

    # (A) 기준일(처분일)과 지적된 개정/시행일 비교
    if ref_d:
        for d, raw in grounded_dates:
            if d > ref_d and any(w in remark_text for w in ("시행", "개정", "공포", "적용")):
                is_contradiction = True
                finding_type = FindingType.TEMPORAL_LAW_MISMATCH
                reason_note = f"기준일({ref_d}) 이후 시행/개정된 날짜({d}) 규정을 적용하라는 모순이 서면 내부 날짜로 재계산 확인됨"
                break

    # (B) 지적 내부 날짜 간의 선후관계 비교 (2개 이상의 날짜가 언급된 경우)
    if not is_contradiction and len(grounded_dates) >= 2:
        sorted_dates = sorted(grounded_dates, key=lambda x: x[0])
        earlier_d, earlier_raw = sorted_dates[0]
        later_d, later_raw = sorted_dates[-1]

        # 송달일과 제소일 사이의 기간 초과 검증 (예: 60일, 90일 제소기간 초과)
        days_diff = (later_d - earlier_d).days
        period_match = re.search(r"(\d{1,3})\s*일\s*(?:이내|경과|초과)", remark_text)
        if period_match:
            claimed_days = int(period_match.group(1))
            if days_diff > claimed_days:
                is_contradiction = True
                finding_type = FindingType.TEMPORAL_LAW_MISMATCH
                reason_note = (
                    f"기재된 날짜 간격({earlier_d} ~ {later_d}, {days_diff}일)이 "
                    f"주장된 기간({claimed_days}일)을 초과함이 서면 내부 날짜로 재계산 확인됨"
                )

        # 서면 작성일보다 뒤인 증거 작성일 (시점 역전 모순)
        if not is_contradiction and any(w in remark_text for w in ("작성일", "늦음", "이후", "역전")):
            if earlier_d < later_d:
                is_contradiction = True
                finding_type = FindingType.EVIDENCE_TIMELINE_INVERSION
                reason_note = f"날짜 역전 모순({earlier_d} vs {later_d})이 서면 내부 날짜로 재계산 확인됨"

    if not is_contradiction:
        return None, {"reason": "RECALCULATION_UNCONFIRMED", "remark": remark_text}

    # 정식 Finding 생성
    clean_remark = re.sub(r"^\[[^\]]+\]\s*", "", remark_text).strip()
    finding = Finding.create(
        type=finding_type,
        status=VerificationStatus.SUSPICIOUS,
        severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.B,
        title=f"재계산 확인 사실 모순: {clean_remark[:80]}",
        detail=f"AI 모델 지적('{clean_remark}')을 서면 내부 기재 날짜로 재계산한 결과 모순이 확인되었습니다. {reason_note}",
        confidence=0.75,
        confidence_features={
            "rule_id": "MODEL_REMARK.RECALCULATED_VERIFIED",
            "model_remark": remark_text,
            "recalculated": "RECALCULATED_VERIFIED",
            "reason_note": reason_note,
            "human_review": True,
        },
        document_id=document_id,
        engine=ENGINE_NAME,
        tags=["MODEL_CANDIDATE", "RECALCULATED", "TEMPORAL"],
        advisory_only=False,  # 정식 Finding 목록에 등재
        evidence=[
            Evidence.create(
                description="서면 내부 기재 날짜 재계산 대조",
                grade=EvidenceGrade.B,
                document_id=document_id,
                excerpt=clean_remark[:300],
                supports=False,
            )
        ],
    )
    return finding, None
