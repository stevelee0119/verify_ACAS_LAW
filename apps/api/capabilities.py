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


def _storage_encryption_state() -> Dict[str, Any]:
    """저장 시 암호화 상태. 키 값은 절대 담지 않고 공급자 종류만 알린다."""
    from packages.common.storage import storage_encryption_enabled, storage_encryption_error

    enabled = storage_encryption_enabled()
    provider = (os.getenv("LV_VAULT_KEY_PROVIDER")
                or ("env" if os.getenv("LV_VAULT_KEYS") or os.getenv("LV_PSEUDONYM_SECRET") else "file"))
    failure = storage_encryption_error()
    if failure:
        # 키가 없으면 자료를 읽지도 쓰지도 못한다. 서비스는 떠 있으므로
        # 화면이 원인을 말해 주지 않으면 이용자는 로그인을 의심하게 된다.
        return {
            "enabled": enabled, "key_provider": provider, "configured": False,
            "note": ("저장 시 암호화가 켜져 있으나 키 설정이 올바르지 않아 사건자료를 "
                     "업로드하거나 열 수 없습니다. LV_VAULT_KEYS는 {\"키ID\": \"base64 32바이트\"} "
                     "형식의 JSON이어야 하며 꺾쇠(<>)를 포함하면 안 됩니다. "
                     "LV_VAULT_ACTIVE_KEY_ID도 함께 있어야 합니다. 키를 확인할 수 없으면 "
                     "LV_STORAGE_ENCRYPTION을 끄십시오. 이미 암호화된 자료는 올바른 키가 있어야 읽힙니다."),
            "error": failure,
        }
    return {
        "enabled": enabled,
        "key_provider": provider,
        "configured": True,
        "note": ("업로드 원본과 보고서 산출물을 봉투 암호화해 보관합니다. 처리 중에는 "
                 "파서를 위해 평문을 임시로 풀어 두므로 그 구간은 가려지지 않습니다."
                 if enabled else
                 "저장 시 암호화가 꺼져 있습니다. 디스크 스냅샷·백업본이 유출되면 "
                 "사건자료를 그대로 읽을 수 있습니다. 실제 사건자료를 다루면 "
                 "LV_STORAGE_ENCRYPTION=on으로 켜고 키를 따로 보관하세요."),
    }


def _worker_state() -> Dict[str, Any]:
    """설정한 값이 실제로 적용됐는지 배포 후 확인할 수 있어야 한다."""
    try:
        from .services import get_runner

        runner = get_runner()
        mode = runner.mode
        return {"mode": mode, "concurrency": runner.concurrency(mode),
                "shares_api_process": mode == "inprocess"}
    except Exception as exc:  # pragma: no cover - 기동 순서에 따라 아직 없을 수 있다
        return {"mode": "unknown", "concurrency": None, "shares_api_process": None,
                "error": f"{type(exc).__name__}: {exc}"}


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
        "storage_encryption": _storage_encryption_state(),
        "worker_mode": settings.worker_mode,
        # 동시 실행 수. 인프로세스에서 둘 이상이면 검증이 API 응답을 밀어낸다.
        "worker": _worker_state(),
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
