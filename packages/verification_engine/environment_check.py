"""실행 환경 점검 및 필수 자원 가용성 검사(과제 1).

LV_LAW_GO_KR_OC, AI 공급자 키(Anthropic, OpenAI, Gemini 등), Tesseract OCR(kor+OSD)
엔진 가용 여부를 점검하고, 출처별 상태(READY/MISSING_KEY)와 필수 자원 누락 시
'회귀 비교 불가: 필수 자원 누락' 경고를 생성한다.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional

from packages.common.config import get_settings
from packages.document_engine.ocr_readiness import ocr_readiness


def check_execution_environment() -> Dict[str, Any]:
    """실행 환경의 법령 API 키, AI 키, OCR 엔진 상태를 점검한다."""
    settings = get_settings()

    # 1. 법령정보센터 Open API OC 키 점검
    law_go_kr_key = (
        os.getenv("LV_LAW_GO_KR_OC")
        or getattr(settings, "law_go_kr_oc", "")
        or getattr(settings, "law_api_oc", "")
    )
    law_go_kr_status = "READY" if bool(law_go_kr_key and law_go_kr_key.strip()) else "MISSING_KEY"

    # 2. AI 공급자 키 점검
    ai_keys = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY") or getattr(settings, "anthropic_api_key", None)),
        "openai": bool(os.getenv("OPENAI_API_KEY") or getattr(settings, "openai_api_key", None)),
        "gemini": bool(os.getenv("GEMINI_API_KEY") or getattr(settings, "gemini_api_key", None)),
    }
    ai_provider_ready = any(ai_keys.values())
    ai_status = {k: ("READY" if v else "MISSING_KEY") for k, v in ai_keys.items()}

    # 3. OCR 엔진 점검 (Tesseract kor+osd)
    ocr_state = ocr_readiness(refresh=False)
    ocr_available = bool(ocr_state.get("available") and ocr_state.get("ready"))

    # 4. 필수 자원 누락 여부 판정
    missing_resources: List[str] = []
    if law_go_kr_status == "MISSING_KEY":
        missing_resources.append("LV_LAW_GO_KR_OC(국가법령정보센터 키)")
    if not ai_provider_ready:
        missing_resources.append("AI 공급자 키(ANTHROPIC/OPENAI/GEMINI 중 최소 1개)")
    if not ocr_available:
        missing_resources.append("tesseract(kor+OSD)")

    regression_comparable = len(missing_resources) == 0
    warning: Optional[str] = None
    if not regression_comparable:
        warning = f"회귀 비교 불가: 필수 자원 누락 ({', '.join(missing_resources)})"

    return {
        "sources": {
            "law_go_kr": law_go_kr_status,
            "ai_providers": ai_status,
        },
        "ocr_engine_available": ocr_available,
        "ocr_details": ocr_state,
        "missing_resources": missing_resources,
        "regression_comparable": regression_comparable,
        "warning": warning,
    }
