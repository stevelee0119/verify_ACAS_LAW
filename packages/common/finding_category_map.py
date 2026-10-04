"""유형별 화면 배정표 (Single Source of Truth)

F1/F2 화면 개편에 따라 전체 97개 FindingType을
1) AI 작성·보안 진단 탭 (AI 진단 카드, 인젝션 검증 카드, 보안 카드)
2) 검토 항목 탭 (법률·판례 인용, 사실관계 모순, 시간축·연표, MM4 권고, 처리 품질)
으로 1:1 전수 배정하는 서버 단일 기준 모듈입니다.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Dict, Set

from packages.common.enums import (
    ADVERSARIAL_FINDING_TYPES,
    LEGAL_FINDING_TYPES,
    MM4_ADVISORY_TYPES,
    FindingType,
)


class ScreenCategory(StrEnum):
    """세부 화면 카드 / 행 카테고리"""
    # [AI 작성·보안 진단 탭 소속]
    AI_DIAGNOSIS = "AI_DIAGNOSIS"              # 문서 AI 생성 여부 진단 카드
    INJECTION_DEFENSE = "INJECTION_DEFENSE"    # 프롬프트 인젝션 검증 카드
    SECURITY_CARD = "SECURITY_CARD"            # 보안 카드 (메타데이터 노출, 포렌식 위변조, 잔류정보)

    # [검토 항목 탭 소속]
    LEGAL_CITATION = "LEGAL_CITATION"          # 법률·판례 인용 검토 행
    FACT_DISCREPANCY = "FACT_DISCREPANCY"      # 사실관계·수치·서증 모순 행 (MODEL_FACT_REMARK 포함)
    TEMPORAL_TIMELINE = "TEMPORAL_TIMELINE"    # 시점 모순·연표·행위시법 검토 행
    MM4_ADVISORY = "MM4_ADVISORY"              # MM-4 권고 신호 행
    PROCESSING_QUALITY = "PROCESSING_QUALITY"  # 처리 품질·상태 신호 (OCR_LOW_QUALITY 포함)


class ScreenTab(StrEnum):
    """최상위 소속 화면 탭"""
    AI_SECURITY = "AI_SECURITY"      # AI 작성·보안 진단 탭
    REVIEW_ITEMS = "REVIEW_ITEMS"    # 검토 항목 (통합 탭)


# 세부 카테고리별 상위 탭 매핑
CATEGORY_TO_TAB: Dict[ScreenCategory, ScreenTab] = {
    ScreenCategory.AI_DIAGNOSIS: ScreenTab.AI_SECURITY,
    ScreenCategory.INJECTION_DEFENSE: ScreenTab.AI_SECURITY,
    ScreenCategory.SECURITY_CARD: ScreenTab.AI_SECURITY,
    ScreenCategory.LEGAL_CITATION: ScreenTab.REVIEW_ITEMS,
    ScreenCategory.FACT_DISCREPANCY: ScreenTab.REVIEW_ITEMS,
    ScreenCategory.TEMPORAL_TIMELINE: ScreenTab.REVIEW_ITEMS,
    ScreenCategory.MM4_ADVISORY: ScreenTab.REVIEW_ITEMS,
    ScreenCategory.PROCESSING_QUALITY: ScreenTab.REVIEW_ITEMS,
}


# ---------------------------------------------------------------------------
# 97개 전수 FindingType 배정표 (누락·초과 0 보장)
# ---------------------------------------------------------------------------
FINDING_CATEGORY_MAP: Dict[FindingType, ScreenCategory] = {
    # -----------------------------------------------------------------------
    # 1. AI 진단 카드 (5개)
    # -----------------------------------------------------------------------
    FindingType.AI_AUTHORSHIP_LIKELY: ScreenCategory.AI_DIAGNOSIS,
    FindingType.AI_FULL_GENERATION_SUSPECTED: ScreenCategory.AI_DIAGNOSIS,
    FindingType.AI_HALLUCINATED_CONTENT: ScreenCategory.AI_DIAGNOSIS,
    FindingType.STYLE_SHIFT: ScreenCategory.AI_DIAGNOSIS,
    FindingType.MODEL_ATTRIBUTION_SIGNAL: ScreenCategory.AI_DIAGNOSIS,

    # -----------------------------------------------------------------------
    # 2. 프롬프트 인젝션 검증 카드 (17개: ADVERSARIAL 16개 + MODEL_OUTPUT_QUARANTINED)
    # -----------------------------------------------------------------------
    FindingType.PROMPT_INJECTION_SUSPECTED: ScreenCategory.INJECTION_DEFENSE,
    FindingType.HIDDEN_INSTRUCTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.META_INSTRUCTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.SYSTEM_OVERRIDE_ATTEMPT: ScreenCategory.INJECTION_DEFENSE,
    FindingType.ROLE_OVERRIDE_ATTEMPT: ScreenCategory.INJECTION_DEFENSE,
    FindingType.VERIFICATION_SUPPRESSION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.OUTPUT_MANIPULATION_ATTEMPT: ScreenCategory.INJECTION_DEFENSE,
    FindingType.ENCODED_INSTRUCTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.OBFUSCATED_INSTRUCTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.UNICODE_SMUGGLING: ScreenCategory.INJECTION_DEFENSE,
    FindingType.OCR_LAYER_INJECTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.METADATA_INJECTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.MULTIMODAL_INJECTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.RAG_POISONING_SIGNAL: ScreenCategory.INJECTION_DEFENSE,
    FindingType.TOOL_MANIPULATION_ATTEMPT: ScreenCategory.INJECTION_DEFENSE,
    FindingType.DATA_EXFILTRATION_INSTRUCTION: ScreenCategory.INJECTION_DEFENSE,
    FindingType.MODEL_OUTPUT_QUARANTINED: ScreenCategory.INJECTION_DEFENSE,

    # -----------------------------------------------------------------------
    # 3. 보안 카드 (25개: D3 메타데이터 유출, 포렌식 위변조 징후, 잔류정보, 식별자 이상)
    # -----------------------------------------------------------------------
    FindingType.AUTHORSHIP_METADATA_LEAK: ScreenCategory.SECURITY_CARD,
    FindingType.GEOLOCATION_METADATA_LEAK: ScreenCategory.SECURITY_CARD,
    FindingType.METADATA_ANOMALY: ScreenCategory.SECURITY_CARD,
    FindingType.HIDDEN_TEXT_MISMATCH: ScreenCategory.SECURITY_CARD,
    FindingType.OCR_LAYER_MISMATCH: ScreenCategory.SECURITY_CARD,
    FindingType.SIGNATURE_INVALID: ScreenCategory.SECURITY_CARD,
    FindingType.MODIFIED_AFTER_SIGNATURE: ScreenCategory.SECURITY_CARD,
    FindingType.PAGE_STRUCTURE_OUTLIER: ScreenCategory.SECURITY_CARD,
    FindingType.RESIDUAL_TRACKED_CHANGE: ScreenCategory.SECURITY_CARD,
    FindingType.RESIDUAL_COMMENT: ScreenCategory.SECURITY_CARD,
    FindingType.DELETED_TEXT_RECOVERABLE: ScreenCategory.SECURITY_CARD,
    FindingType.PRIOR_VERSION_RECOVERABLE: ScreenCategory.SECURITY_CARD,
    FindingType.REDACTION_FAILURE: ScreenCategory.SECURITY_CARD,
    FindingType.HIDDEN_SHEET_OR_ROW: ScreenCategory.SECURITY_CARD,
    FindingType.CROPPED_IMAGE_RESIDUE: ScreenCategory.SECURITY_CARD,
    FindingType.TEMPLATE_RESIDUE: ScreenCategory.SECURITY_CARD,
    FindingType.SPECIMEN_DOCUMENT_DECLARED: ScreenCategory.SECURITY_CARD,
    FindingType.INVALID_IDENTIFIER: ScreenCategory.SECURITY_CARD,
    FindingType.PLACEHOLDER_IDENTIFIER: ScreenCategory.SECURITY_CARD,
    FindingType.STEGANOGRAPHIC_PAYLOAD: ScreenCategory.SECURITY_CARD,
    FindingType.TRACKING_CANARY_DETECTED: ScreenCategory.SECURITY_CARD,
    FindingType.DOCUMENT_FINGERPRINT_SUSPECTED: ScreenCategory.SECURITY_CARD,
    FindingType.COVERT_CHANNEL_SUSPECTED: ScreenCategory.SECURITY_CARD,
    FindingType.PRIVILEGE_EXPOSURE_RISK: ScreenCategory.SECURITY_CARD,
    FindingType.OUTBOUND_LEAK_RISK: ScreenCategory.SECURITY_CARD,

    # -----------------------------------------------------------------------
    # 4. 법률·판례 인용 검토 행 (11개: LEGAL_FINDING_TYPES 9개 + 인용 관련)
    # -----------------------------------------------------------------------
    FindingType.CASE_NOT_FOUND: ScreenCategory.LEGAL_CITATION,
    FindingType.CASE_METADATA_MISMATCH: ScreenCategory.LEGAL_CITATION,
    FindingType.CASE_QUOTE_MISMATCH: ScreenCategory.LEGAL_CITATION,
    FindingType.CASE_HOLDING_DISTORTION: ScreenCategory.LEGAL_CITATION,
    FindingType.CASE_CITATION_ERROR: ScreenCategory.LEGAL_CITATION,
    FindingType.CASE_RELEVANCE_WEAK: ScreenCategory.LEGAL_CITATION,
    FindingType.LAW_CITATION_ERROR: ScreenCategory.LEGAL_CITATION,
    FindingType.STATUTE_NONEXISTENT: ScreenCategory.LEGAL_CITATION,
    FindingType.STATUTE_TEXT_MISMATCH: ScreenCategory.LEGAL_CITATION,
    FindingType.INTERNAL_CITATION_ERROR: ScreenCategory.LEGAL_CITATION,
    FindingType.ACADEMIC_CITATION_ERROR: ScreenCategory.LEGAL_CITATION,

    # -----------------------------------------------------------------------
    # 5. 사실관계·수치·서증 모순 행 (25개: MODEL_FACT_REMARK 포함)
    # -----------------------------------------------------------------------
    FindingType.FACT_CONTRADICTION: ScreenCategory.FACT_DISCREPANCY,
    FindingType.CROSS_DOCUMENT_CONTRADICTION: ScreenCategory.FACT_DISCREPANCY,
    FindingType.FACT_UNSUPPORTED: ScreenCategory.FACT_DISCREPANCY,
    FindingType.ARITHMETIC_MISMATCH: ScreenCategory.FACT_DISCREPANCY,
    FindingType.QUOTE_MISMATCH: ScreenCategory.FACT_DISCREPANCY,
    FindingType.CROSS_DOC_COPY: ScreenCategory.FACT_DISCREPANCY,
    # MODEL_FACT_REMARK: 평가 측 회신 3.2절에 따라 검토 항목(사실관계)으로 재배정
    FindingType.MODEL_FACT_REMARK: ScreenCategory.FACT_DISCREPANCY,
    FindingType.LEGAL_ARGUMENT_INVALID: ScreenCategory.FACT_DISCREPANCY,
    FindingType.LEGAL_REQUIREMENT_OMITTED: ScreenCategory.FACT_DISCREPANCY,
    FindingType.OVERCLAIM: ScreenCategory.FACT_DISCREPANCY,
    FindingType.UNSUPPORTED_GENERALIZATION: ScreenCategory.FACT_DISCREPANCY,
    FindingType.REASONING_GAP: ScreenCategory.FACT_DISCREPANCY,
    FindingType.AUTHORITY_RANK_ERROR: ScreenCategory.FACT_DISCREPANCY,
    FindingType.SOURCE_CONFLICT_IGNORED: ScreenCategory.FACT_DISCREPANCY,
    FindingType.CALCULATION_INVARIANT_VIOLATION: ScreenCategory.FACT_DISCREPANCY,
    FindingType.UNCERTAINTY_NOT_DISCLOSED: ScreenCategory.FACT_DISCREPANCY,
    FindingType.DRAFT_ARTIFACT: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_NOT_PROVIDED: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_REFERENCE_MISSING: ScreenCategory.FACT_DISCREPANCY,
    FindingType.HASH_FORMAT_INVALID: ScreenCategory.FACT_DISCREPANCY,
    FindingType.HASH_MISMATCH: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_NUMBERING_GAP: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_LIST_MISMATCH: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_PERSON_INCONSISTENT: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_FORM_DEFECT: ScreenCategory.FACT_DISCREPANCY,
    FindingType.EVIDENCE_PURPOSE_MISMATCH: ScreenCategory.FACT_DISCREPANCY,
    FindingType.STATEMENT_BEYOND_PERCEPTION: ScreenCategory.FACT_DISCREPANCY,

    # -----------------------------------------------------------------------
    # 6. 시점·연표·행위시법 검토 행 (4개)
    # -----------------------------------------------------------------------
    FindingType.TEMPORAL_LAW_MISMATCH: ScreenCategory.TEMPORAL_TIMELINE,
    FindingType.TIMELINE_CONTRADICTION: ScreenCategory.TEMPORAL_TIMELINE,
    FindingType.EVIDENCE_TIMELINE_INVERSION: ScreenCategory.TEMPORAL_TIMELINE,
    FindingType.EVIDENCE_DATE_INVALID: ScreenCategory.TEMPORAL_TIMELINE,

    # -----------------------------------------------------------------------
    # 7. MM-4 권고 신호 (5개: MM4_ADVISORY_TYPES 전수)
    # -----------------------------------------------------------------------
    FindingType.ISSUE_EVASION_SIGNAL: ScreenCategory.MM4_ADVISORY,
    FindingType.IMPLICIT_ADMISSION_SIGNAL: ScreenCategory.MM4_ADVISORY,
    FindingType.LIABILITY_HEDGING_SIGNAL: ScreenCategory.MM4_ADVISORY,
    FindingType.COERCIVE_LANGUAGE_SIGNAL: ScreenCategory.MM4_ADVISORY,
    FindingType.SELECTIVE_QUOTATION_SIGNAL: ScreenCategory.MM4_ADVISORY,

    # -----------------------------------------------------------------------
    # 8. 처리 품질·상태 신호 (3개: OCR_LOW_QUALITY 포함)
    # -----------------------------------------------------------------------
    # OCR_LOW_QUALITY: 평가 측 회신 3.3절에 따라 검토 항목(처리 상태)으로 재배정
    FindingType.OCR_LOW_QUALITY: ScreenCategory.PROCESSING_QUALITY,
    FindingType.UNSUPPORTED_FORMAT: ScreenCategory.PROCESSING_QUALITY,
    FindingType.PARSE_ERROR: ScreenCategory.PROCESSING_QUALITY,
}


def get_finding_category(finding_type: FindingType | str) -> ScreenCategory:
    """FindingType에 대응하는 ScreenCategory를 반환합니다."""
    ft = FindingType(finding_type) if isinstance(finding_type, str) else finding_type
    return FINDING_CATEGORY_MAP[ft]


def get_finding_tab(finding_type: FindingType | str) -> ScreenTab:
    """FindingType이 속하는 최상위 ScreenTab을 반환합니다."""
    cat = get_finding_category(finding_type)
    return CATEGORY_TO_TAB[cat]


def is_ai_security_finding(finding_type: FindingType | str) -> bool:
    """AI 작성·보안 진단 탭 소속 여부를 확인합니다."""
    return get_finding_tab(finding_type) == ScreenTab.AI_SECURITY


def is_review_item_finding(finding_type: FindingType | str) -> bool:
    """검토 항목 탭 소속 여부를 확인합니다."""
    return get_finding_tab(finding_type) == ScreenTab.REVIEW_ITEMS


def get_category_counts() -> Dict[str, int]:
    """카테고리별 및 탭별 배정 수치 통계를 반환합니다."""
    tab_counts = {ScreenTab.AI_SECURITY.value: 0, ScreenTab.REVIEW_ITEMS.value: 0}
    cat_counts = {c.value: 0 for c in ScreenCategory}
    for cat in FINDING_CATEGORY_MAP.values():
        cat_counts[cat.value] += 1
        tab_counts[CATEGORY_TO_TAB[cat].value] += 1
    return {**cat_counts, **tab_counts, "TOTAL": len(FINDING_CATEGORY_MAP)}
