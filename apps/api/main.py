"""FastAPI 진입점 (제3장 모듈형 모놀리스)."""
from __future__ import annotations

import logging
import os
import re
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from packages.common.config import get_settings

from fastapi import Depends

from .auth import require_admin
from packages.common.storage import (StorageKeyConfigurationError,
                                     record_storage_encryption_error,
                                     verify_storage_encryption_config)
from .capabilities import runtime_capabilities
from .durability import log_durability_warning
from .db_errors import database_unavailable_reason, error_label
from .storage_admin import database_status, storage_report, vacuum
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType

from .db import User, get_db, get_session_factory
from .db import init_db
from .access import workspace_access
from .routers import (audit, auth_router, projects, reports, settings_router, verification,
                      viewer, calculations, workspace, document_review, identity, jobs)

# 제21.1장: 로그에 실명·주민번호·API Key·원문 전체를 남기지 않는다
SENSITIVE_PATTERNS = [
    re.compile(r"\d{6}[-\s]?[1-4]\d{6}"),
    re.compile(r"(sk-[A-Za-z0-9]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{10,})"),
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        for pattern in SENSITIVE_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def _bootstrap_admin() -> None:
    """환경변수로 최초 관리자를 만든다.

    운영 모드에서는 유효한 계정 없이 보호된 API에 접근할 수 없다.
    무인증으로 열지 않으므로 최초 관리자 부트스트랩 경로를 제공한다.
    """
    from .auth import bootstrap_admin_from_env
    from .db import get_session_factory

    session = get_session_factory()()
    try:
        user = bootstrap_admin_from_env(session)
        if user is not None:
            logging.getLogger(__name__).info("최초 관리자 계정을 생성했다")
    except Exception as exc:  # pragma: no cover - 부트스트랩 실패가 기동을 막지 않게 한다
        logging.getLogger(__name__).warning("관리자 부트스트랩 실패: %s", type(exc).__name__)
    finally:
        session.close()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.getLogger().addFilter(RedactingFilter())

    @asynccontextmanager
    async def lifespan(app):
        import asyncio
        from .services import get_runner
        if os.getenv("LV_REQUIRE_OCR", "").lower() in {"1", "true", "yes", "on"}:
            from packages.document_engine.ocr_readiness import require_ocr_ready
            await asyncio.to_thread(require_ocr_ready)
        runner = get_runner()
        await asyncio.to_thread(runner.start)
        try:
            yield
        finally:
            await asyncio.to_thread(runner.stop)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        description=(
            "ACASia_LAW 법률문서 검증시스템. "
            "Source First / Evidence First / Human Final Decision 원칙에 따라 동작한다."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(workspace_access)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        """처리하지 못한 오류도 원인을 추적할 수 있게 문의 번호와 함께 남긴다.

        예외 메시지에는 SQL 인자·파일 경로 같은 사건 정보가 섞일 수 있어 기록하지 않는다.
        예외 종류와 호출 위치(스택)만 남기고, 화면에는 같은 문의 번호를 보인다.
        """
        request_id = uuid4().hex[:12]
        route = request.url.path
        # 소스 줄은 싣지 않는다. 파일·줄 번호·함수 이름이면 원인 위치를 찾기에 충분하다.
        frames = "\n".join(f"  {Path(f.filename).name}:{f.lineno} in {f.name}"
                           for f in traceback.extract_tb(exc.__traceback__)[-12:])
        # DB 오류는 드라이버 예외 종류와 SQLSTATE까지 적는다(교착·잠금 대기·연결 끊김을 가를 수 있게).
        label = error_label(exc)
        unavailable = database_unavailable_reason(exc)
        logging.getLogger(__name__).error(
            "unhandled_error request_id=%s method=%s route=%s error_type=%s\n%s",
            request_id, request.method, route, label, frames)
        if unavailable:
            # DB에 연결할 수 없거나 저장 공간이 찬 상태는 기능 오류가 아니다. 모든 기능이 같은 오류를 내므로
            # 사용자가 무엇을 확인해야 하는지 알린다.
            message = f"{unavailable} ({label}). 문의 번호 {request_id}."
            return JSONResponse(status_code=503, headers={"X-Request-ID": request_id, "Retry-After": "30"},
                                content={"detail": {"message": message, "code": "DATABASE_UNAVAILABLE",
                                                    "request_id": request_id, "error_type": label}})
        message = (f"서버 내부 오류로 요청을 처리하지 못했습니다 ({label}). "
                   f"문의 번호 {request_id}로 서버 기록에서 원인을 확인할 수 있습니다.")
        return JSONResponse(status_code=500, headers={"X-Request-ID": request_id},
                            content={"detail": {"message": message, "code": "INTERNAL_ERROR",
                                                "request_id": request_id, "error_type": label}})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'self'",
        )
        return response

    # 스키마는 앱 생성 시점에 준비한다(운영에서는 Alembic migration을 사용한다).
    init_db()
    _bootstrap_admin()
    # 저장소가 휘발성이면 재시작마다 로그인·원본·감사기록이 사라진다.
    # 화면상 정상으로 보이므로 기동 로그에서 먼저 알린다.
    log_durability_warning()
    # 암호화 키 설정 오류는 첫 업로드가 아니라 기동 시점에 드러나야 한다.
    #
    # 다만 기동 자체를 막지는 않는다. 설정 오류로 서비스가 뜨지 않으면
    # 로그인도, 기존 사건자료 조회도, 원인을 알려 줄 진단 화면도 막힌다.
    # 보고하려던 문제보다 나쁜 상태다. 크게 남기고 진단에 실어 알리되,
    # 자료를 다루는 경로는 storage 계층이 계속 거부한다.
    record_storage_encryption_error(None)
    try:
        verify_storage_encryption_config()
    except StorageKeyConfigurationError as exc:
        record_storage_encryption_error(str(exc))
        logging.getLogger(__name__).error(
            "저장 시 암호화 키 설정이 잘못되어 자료 업로드·조회가 거부됩니다. "
            "서비스는 기동하지만 이 설정을 고치기 전까지 사건자료를 다룰 수 없습니다. %s", exc)

    for module in (projects, verification, reports, settings_router, viewer, audit, calculations, workspace, document_review, identity, jobs):
        app.include_router(module.router, prefix="/api")
    # auth_router는 경로에 이미 /api가 들어 있으므로 prefix를 붙이지 않는다
    app.include_router(auth_router.router)

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        """무인증 헬스체크. 배포 플랫폼이 호출하므로 설정을 노출하지 않는다."""
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "commit": (os.getenv("RENDER_GIT_COMMIT") if re.fullmatch(
                r"[0-9a-fA-F]{40}", os.getenv("RENDER_GIT_COMMIT", "")) else None),
            "principles": ["Source First", "Evidence First", "Human Final Decision"],
            # DB가 끊겨도 웹 서버는 살아 있어 배포 플랫폼은 '정상'으로 본다. 원인을 가를 수 있게 따로 싣는다.
            # 재시작이 반복되지 않도록 응답 코드는 200을 유지한다.
            "database": database_status(),
        }

    @app.get("/api/diagnostics/sources")
    def source_diagnostics(admin: User = Depends(require_admin)) -> Dict[str, Any]:
        """이 서버에서 국가법령정보를 실제로 조회해 본다(관리자 전용, 요청 2~3건).

        판례 전문을 받지 못하면 의미·적용 검토(세 모델 교차검증)가 건너뛰어진다.
        GitHub 러너는 국외 IP라 law.go.kr 응답이 불안정해 이 판단에 쓸 수 없다.
        실제 분석이 도는 서버에서 확인해야 한다. 비밀값은 담지 않는다.
        """
        from packages.legal_engine.normalize import same_case_number

        from .services import get_registry

        adapter = get_registry().law
        case_number = "2011모1839"
        steps: List[Dict[str, Any]] = []
        found = adapter.search_case(case_number)
        record = next((r for r in found.records
                       if same_case_number(case_number, str(r.get("case_number") or ""))), None)
        steps.append({"step": "사건번호 조회(lawSearch)", "status": str(found.status),
                      "matched": record is not None, "records": len(found.records),
                      "has_source_id": bool(record and record.get("source_id")),
                      "message": found.message})
        full_text = ""
        if record is not None:
            full_text = str(record.get("full_text") or "")
            if not full_text:
                detail = adapter.fetch_case(record)
                full_text = str((detail.records[0] if detail.records else {}).get("full_text") or "")
                steps.append({"step": "판례 전문 조회(lawService)", "status": str(detail.status),
                              "full_text_chars": len(full_text), "message": detail.message})
        return {"case_number": case_number, "full_text_available": bool(full_text), "steps": steps,
                "verdict": "READY" if full_text else "FULL_TEXT_UNAVAILABLE",
                "note": ("판례 전문을 받을 수 있어 의미·적용 검토(세 모델 교차검증)가 수행됩니다."
                         if full_text else
                         "판례 전문을 받지 못해 의미·적용 검토(세 모델 교차검증)가 수행되지 않습니다. "
                         "steps의 message가 원인입니다.")}

    @app.get("/api/diagnostics")
    def diagnostics(admin: User = Depends(require_admin)) -> Dict[str, Any]:
        """배포 환경이 무엇을 할 수 있는지 스스로 밝힌다.

        OCR이 없으면 스캔본·이미지 문서의 본문 검증은 수행되지 않고 UNVERIFIED로
        남는다. 배포 직후 이 값을 확인하지 않으면, 아무것도 읽지 못한 실행을
        정상 실행으로 오인하게 된다.

        비밀값은 담지 않는다. 키의 존재 여부(불리언)만 알린다.
        """
        capabilities = runtime_capabilities()
        blocking = [name for name, ready in (
            ("ocr", capabilities["ocr"]["ready"]),
            ("rasterizer", capabilities["rasterizer"]["available"]),
        ) if not ready]
        # 저장소 내구성은 분석 능력과 별개다. blocking에 넣어 OCR 판정을
        # 흐리지 않고, 따로 경고로 싣는다. 진단 응답이 한 항목 때문에 통째로
        # 실패하면 남은 항목까지 볼 수 없으므로 없는 키는 건너뛴다.
        warnings = (["durability"]
                    if (capabilities.get("durability") or {}).get("verdict") == "AT_RISK" else [])
        return {
            "capabilities": capabilities,
            "blocking": blocking,
            "warnings": warnings,
            "verdict": "READY" if not blocking else "DEGRADED",
            "note": (
                "스캔 문서 읽기 준비가 완료되지 않았습니다. 이미지·스캔 PDF의 본문 검증은 "
                "미검증(UNVERIFIED)으로 남을 수 있습니다. 아래 점검 결과와 관리자 조치를 확인하세요."
                if "ocr" in blocking
                else "PDF를 이미지로 변환할 수 없어 스캔 PDF 검증이 제한됩니다."
                if "rasterizer" in blocking
                else "한국어 스캔 시험 문서의 본문·페이지 위치 인식을 확인했습니다. 개별 문서의 인식 결과는 별도 검토가 필요합니다."
            ),
        }

    @app.get("/api/admin/storage")
    def admin_storage(admin: User = Depends(require_admin)) -> Dict[str, Any]:
        """DB·파일 저장소 사용량(관리자 전용). 사건 내용은 싣지 않고 크기·행 수만 싣는다."""
        return storage_report()

    @app.post("/api/admin/storage/reclaim")
    def admin_storage_reclaim(payload: Dict[str, Any], admin: User = Depends(require_admin),
                              session: Session = Depends(get_db)) -> Dict[str, Any]:
        """빈 공간 정리(VACUUM) 또는 디스크 반환(VACUUM FULL, 테이블 잠김). 실행 사실은 감사기록에 남긴다."""
        full = bool((payload or {}).get("full"))
        session.close()  # VACUUM은 트랜잭션 밖에서 실행되어야 하므로 요청 세션의 연결을 먼저 돌려준다
        result = vacuum(full=full)
        from .services import make_audit
        with get_session_factory()() as audit_session:
            make_audit(audit_session).record(AuditEventType.USER_OVERRIDE,
                {"action": "STORAGE_RECLAIMED", **{k: result[k] for k in ("full", "before_bytes", "after_bytes", "seconds")}},
                actor=admin.id)
        return result

    web_dir = Path(__file__).resolve().parents[1] / "web"
    if (web_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(str(web_dir / "index.html"))

    return app


app = create_app()
