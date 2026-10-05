"""미확인 사유 사람 말(Human-Readable) 변환표 단위 시험.

19b 설계 2.5절 및 F2 요구사항에 따라 실제 엔진 코드베이스의 사유 코드가
누락 없이 사용자 친화적 문구로 안전하게 변환되는지 검증합니다.
"""
import pytest

from packages.verification_engine.review_items import (
    HUMAN_READABLE_UNVERIFIED_REASONS,
    humanize_unverified_reason,
)


def test_registered_unverified_reasons_mapping():
    """사전 등록된 모든 사유 코드가 적절한 한국어 안내 문구로 변환되는지 검증."""
    for raw_reason, expected_msg in HUMAN_READABLE_UNVERIFIED_REASONS.items():
        converted = humanize_unverified_reason(raw_reason)
        assert converted == expected_msg, f"{raw_reason} 매핑 불일치"
        # 영문 에러 코드가 그대로 노출되지 않아야 함
        assert "Multiple versions" not in converted


def test_fallback_for_unknown_reasons():
    """사전에 등록되지 않은 새 사유 코드가 들어와도 정보 손실 없이 fallback 문구를 제공하는지 검증."""
    unknown = "SOME_CUSTOM_UNEXPECTED_ERROR"
    converted = humanize_unverified_reason(unknown)
    assert converted == f"미확인 사유: {unknown}"


def test_empty_or_none_reason_handling():
    """빈 문자열 또는 공백 사유 처리 방어 검증."""
    assert humanize_unverified_reason("") == "미확인 사유 미기재"
