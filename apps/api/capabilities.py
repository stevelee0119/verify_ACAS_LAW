"""배포 환경의 실행 능력 점검.

배포가 끝났다고 검증이 되는 것은 아니다. OCR이 없으면 이미지·스캔 PDF는
본문을 읽지 못하고, 그 실행은 "이상 없음"이 아니라 "확인하지 못함"이다.
운영자가 배포 직후 한 번에 확인할 수 있도록 능력을 모아 보고한다.

비밀값은 담지 않는다. 키의 존재 여부와 공개 가능한 버전 문자열만 다룬다.
"""
from __future__ import annotations

import os
import platform
from typing import Any, Dict

from packages.common.config import get_settings


def _ocr_state() -> Dict[str, Any]:
    from packages.document_engine.ocr_readiness import ocr_readiness
    return ocr_readiness()


def _rasterizer_state() -> Dict[str, Any]:
    """스캔 PDF를 이미지로 만들 수 있는지. 없으면 독립 OCR 교차검증이 불가능하다."""
    try:
        import pypdfium2

        return {"available": True, "library": "pypdfium2", "version": str(getattr(pypdfium2, "V_PYPDFIUM2", ""))}
    except Exception as exc:  # pragma: no cover - 환경 의존
        return {"available": False, "library": "pypdfium2", "error": type(exc).__name__}


def _database_state() -> Dict[str, Any]:
    from .db import get_engine

    try:
        engine = get_engine()
        dialect = engine.dialect.name
    except Exception as exc:  # pragma: no cover - 환경 의존
        return {"dialect": "unknown", "error": type(exc).__name__}
    pgvector = False
    if dialect == "postgresql":
        try:
            from pgvector.sqlalchemy import Vector  # noqa: F401

            pgvector = True
        except Exception:
            pgvector = False
    return {"dialect": dialect, "pgvector": pgvector}


def _container_state() -> Dict[str, Any]:
    """컨테이너(도커) 안에서 도는지 추정한다.

    Render의 docker 런타임은 컨테이너로 돌고, native 런타임도 격리 환경이므로
    OCR 가용성이나 컨테이너 표지만으로 런타임 종류를 단정하지 않는다.
    """
    markers = {
        "dockerenv": os.path.exists("/.dockerenv"),
        "render_service_id": bool(os.getenv("RENDER_SERVICE_ID")),
    }
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "markers": markers,
        "note": "컨테이너 표지와 OCR 상태만으로 런타임 종류를 확정할 수 없습니다. 배포 설정과 빌드 로그를 확인하세요.",
    }


def _source_keys() -> Dict[str, bool]:
    """외부 Source 키의 '존재 여부'만 본다. 값은 절대 담지 않는다."""
    return {
        name: bool(os.getenv(env))
        for name, env in (
            ("law_go_kr", "LV_LAW_GO_KR_OC"),
            ("kci", "LV_KCI_KEY"),
            ("crossref", "LV_CROSSREF_MAILTO"),
            ("semantic_scholar", "LV_SEMANTIC_SCHOLAR_KEY"),
        )
    }


def runtime_capabilities() -> Dict[str, Any]:
    from .durability import durability_report
    from .session_policy import analysis_lifetimes, session_lifetimes

    settings = get_settings()
    idle, absolute = session_lifetimes()
    analysis, review = analysis_lifetimes()
    return {
        "ocr": _ocr_state(),
        "rasterizer": _rasterizer_state(),
        "database": _database_state(),
        # 저장소가 재시작을 견디는지. 이 값이 없으면 잘못된 배포가 정상처럼 보인다.
        "durability": durability_report(),
        "worker_mode": settings.worker_mode,
        "browser_session": {
            "idle_hours": idle.total_seconds() / 3600,
            "absolute_hours": absolute.total_seconds() / 3600,
            "renew_on_activity": True,
            "analysis_protection_hours": analysis.total_seconds() / 3600,
            "result_review_hours": review.total_seconds() / 3600,
        },
        "network_allowed": bool(settings.allow_network),
        "source_keys_present": _source_keys(),
        "source_lookup": {
            "max_attempts": max(1, min(5, settings.source_lookup_attempts)),
            "initial_timeout_seconds": min(45.0, max(0.01, settings.http_timeout)),
            "document_base_seconds": settings.source_lookup_budget_seconds,
            "document_max_seconds": settings.source_lookup_max_document_seconds,
            "document_recovery_seconds": settings.source_lookup_recovery_seconds,
        },
        "runtime": _container_state(),
    }
