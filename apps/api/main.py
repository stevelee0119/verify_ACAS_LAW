"""FastAPI 진입점 (제3장 모듈형 모놀리스)."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from packages.common.config import get_settings

from .capabilities import runtime_capabilities
from .db import init_db
from .access import workspace_access
from .routers import audit, projects, reports, settings_router, verification, viewer, calculations, workspace, document_review, identity, jobs

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


def create_app() -> FastAPI:
    settings = get_settings()
    logging.getLogger().addFilter(RedactingFilter())

    @asynccontextmanager
    async def lifespan(app):
        import asyncio
        from .services import get_runner
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
            "법률 분야 AI 문서 검증 및 위조 식별 시스템. "
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

    for module in (projects, verification, reports, settings_router, viewer, audit, calculations, workspace, document_review, identity, jobs):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "principles": ["Source First", "Evidence First", "Human Final Decision"],
            "capabilities": runtime_capabilities(),
        }

    @app.get("/api/diagnostics")
    def diagnostics() -> Dict[str, Any]:
        """배포 환경이 무엇을 할 수 있는지 스스로 밝힌다.

        OCR이 없으면 스캔본·이미지 문서의 본문 검증은 수행되지 않고 UNVERIFIED로
        남는다. 배포 직후 이 값을 확인하지 않으면, 아무것도 읽지 못한 실행을
        정상 실행으로 오인하게 된다.

        비밀값은 담지 않는다. 키의 존재 여부(불리언)만 알린다.
        """
        capabilities = runtime_capabilities()
        blocking = [name for name, ready in (
            ("ocr", capabilities["ocr"]["available"]),
            ("rasterizer", capabilities["rasterizer"]["available"]),
        ) if not ready]
        return {
            "capabilities": capabilities,
            "blocking": blocking,
            "verdict": "READY" if not blocking else "DEGRADED",
            "note": (
                "OCR을 사용할 수 없다. 이미지·스캔 PDF는 본문을 읽지 못해 "
                "내용 검증이 UNVERIFIED로 남는다. Render라면 runtime이 docker인지 확인한다."
                if "ocr" in blocking
                else "이미지·스캔 문서를 포함해 본문 추출이 가능하다."
            ),
        }

    web_dir = Path(__file__).resolve().parents[1] / "web"
    if (web_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(str(web_dir / "index.html"))

    return app


app = create_app()
