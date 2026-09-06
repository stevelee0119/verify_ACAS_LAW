"""FastAPI 진입점 (제3장 모듈형 모놀리스)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from packages.common.config import get_settings

from .db import init_db
from .routers import audit, projects, reports, settings_router, verification, viewer

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

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
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

    for module in (projects, verification, reports, settings_router, viewer, audit):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "principles": ["Source First", "Evidence First", "Human Final Decision"],
        }

    web_dir = Path(__file__).resolve().parents[1] / "web"
    if (web_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(str(web_dir / "index.html"))

    return app


app = create_app()
