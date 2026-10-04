"""유형별 화면 배정표(finding_category_map) 전수 및 제약 검증 시험

평가 측 회신서(docs/handoff/F1_DESIGN_REVIEW_REPLY.md 3절)의 필수 수정 사항을 검증합니다:
1. 97개 FindingType 멤버의 누락·초과 0 검증
2. ADVERSARIAL_FINDING_TYPES 16개 전수 인젝션 카드 배정 검증
3. MM4_ADVISORY_TYPES 5개 전수 권고 신호(검토 항목 탭) 배정 검증
4. LEGAL_FINDING_TYPES 9개 전수 검토 항목 탭 배정 검증
5. MODEL_FACT_REMARK -> 검토 항목(사실관계) 재배정 검증 (T4 배타성 보호)
6. OCR_LOW_QUALITY -> 검토 항목(처리 상태) 재배정 검증
"""
import pytest
from packages.common.enums import (
    ADVERSARIAL_FINDING_TYPES,
    LEGAL_FINDING_TYPES,
    MM4_ADVISORY_TYPES,
    FindingType,
)
from packages.common.finding_category_map import (
    FINDING_CATEGORY_MAP,
    ScreenCategory,
    ScreenTab,
    get_category_counts,
    get_finding_category,
    get_finding_tab,
    is_ai_security_finding,
    is_review_item_finding,
)


def test_all_97_finding_types_allocated_without_omission_or_excess():
    """97개 FindingType 전체가 누락이나 초과 없이 1:1 매핑되어야 합니다."""
    all_enum_members = set(FindingType)
    allocated_types = set(FINDING_CATEGORY_MAP.keys())

    assert len(all_enum_members) == 97, f"FindingType 정의 개수가 97개가 아님: {len(all_enum_members)}"
    assert all_enum_members == allocated_types, (
        f"배정표 누락/초과 발생: "
        f"누락={all_enum_members - allocated_types}, "
        f"초과={allocated_types - all_enum_members}"
    )


def test_adversarial_types_allocated_to_injection_defense():
    """ADVERSARIAL_FINDING_TYPES 16개 전수는 인젝션 검증 카드(AI·보안 탭)에 배정되어야 합니다."""
    assert len(ADVERSARIAL_FINDING_TYPES) == 16
    for ft in ADVERSARIAL_FINDING_TYPES:
        assert get_finding_category(ft) == ScreenCategory.INJECTION_DEFENSE
        assert get_finding_tab(ft) == ScreenTab.AI_SECURITY
        assert is_ai_security_finding(ft) is True
        assert is_review_item_finding(ft) is False


def test_mm4_advisory_types_allocated_to_review_items():
    """MM4_ADVISORY_TYPES 5개 전수는 검토 항목 탭의 MM4 권고 신호에 배정되어야 합니다."""
    assert len(MM4_ADVISORY_TYPES) == 5
    for ft in MM4_ADVISORY_TYPES:
        assert get_finding_category(ft) == ScreenCategory.MM4_ADVISORY
        assert get_finding_tab(ft) == ScreenTab.REVIEW_ITEMS
        assert is_review_item_finding(ft) is True
        assert is_ai_security_finding(ft) is False


def test_legal_finding_types_allocated_to_review_items():
    """LEGAL_FINDING_TYPES 9개 전수는 검토 항목 탭(법률 인용/사실관계)에 배정되어야 합니다."""
    assert len(LEGAL_FINDING_TYPES) == 9
    for ft in LEGAL_FINDING_TYPES:
        assert get_finding_tab(ft) == ScreenTab.REVIEW_ITEMS
        assert is_review_item_finding(ft) is True
        assert is_ai_security_finding(ft) is False


def test_model_fact_remark_reassigned_to_fact_discrepancy():
    """MODEL_FACT_REMARK는 AI 탭이 아닌 검토 항목(사실관계)에 배정되어야 합니다 (회신 3.2절)."""
    assert get_finding_category(FindingType.MODEL_FACT_REMARK) == ScreenCategory.FACT_DISCREPANCY
    assert get_finding_tab(FindingType.MODEL_FACT_REMARK) == ScreenTab.REVIEW_ITEMS
    assert is_review_item_finding(FindingType.MODEL_FACT_REMARK) is True
    assert is_ai_security_finding(FindingType.MODEL_FACT_REMARK) is False


def test_ocr_low_quality_reassigned_to_processing_quality():
    """OCR_LOW_QUALITY는 위변조가 아닌 검토 항목(처리 품질)에 배정되어야 합니다 (회신 3.3절)."""
    assert get_finding_category(FindingType.OCR_LOW_QUALITY) == ScreenCategory.PROCESSING_QUALITY
    assert get_finding_tab(FindingType.OCR_LOW_QUALITY) == ScreenTab.REVIEW_ITEMS
    assert is_review_item_finding(FindingType.OCR_LOW_QUALITY) is True
    assert is_ai_security_finding(FindingType.OCR_LOW_QUALITY) is False


def test_category_counts_integrity():
    """카테고리별 통계 합계가 97개와 일치해야 합니다."""
    counts = get_category_counts()
    assert counts["TOTAL"] == 97
    assert counts[ScreenTab.AI_SECURITY.value] + counts[ScreenTab.REVIEW_ITEMS.value] == 97


def test_api_finding_categories_endpoint():
    """GET /api/finding-categories 엔드포인트가 97개 매핑을 정상 반환해야 합니다."""
    from fastapi.testclient import TestClient
    from apps.api.main import app

    client = TestClient(app)
    resp = client.get("/api/finding-categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "tabs" in data
    assert "counts" in data
    assert len(data["categories"]) == 97
    assert len(data["tabs"]) == 97
    assert data["counts"]["TOTAL"] == 97

