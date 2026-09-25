"""실행 환경 점검 및 필수 자원 가용성 검사(과제 1).

LV_LAW_GO_KR_OC, AI 공급자 키(Anthropic, OpenAI, Gemini 등), Tesseract OCR(kor+OSD)
엔진 가용 여부를 점검하고, 출처별 상태(READY/MISSING_KEY)와 필수 자원 누락 시
'회귀 비교 불가: 필수 자원 누락' 경고를 생성한다.
"""
from __future__ import annotations

from typing import Any, Dict

from .environment import incomplete_banner, preflight


def check_execution_environment() -> Dict[str, Any]:
    """실행 환경의 법령 API 키, AI 키, OCR 엔진 상태를 점검한다."""
    environment = preflight()
    return {
        **environment,
        "ocr_engine_available": bool(environment["resources"]["korean_ocr"]),
        "ocr_details": dict(environment["ocr"]),
        "missing_resources": list(environment["missing_required"]),
        "regression_comparable": bool(environment["complete"]),
        "warning": incomplete_banner(environment),
    }
