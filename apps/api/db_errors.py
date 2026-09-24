"""DB 오류를 사건 정보 없이 식별한다.

SQLAlchemy의 OperationalError는 교착·잠금 대기 초과·질의 취소·연결 끊김·자원 부족을 모두 담는다.
원인을 가르려면 드라이버 예외 종류와 SQLSTATE가 필요하다. 메시지 본문은 값이 섞일 수 있어 쓰지 않는다.
"""
from __future__ import annotations

from typing import Optional

# 잠시 뒤 다시 하면 풀리는 경합: 교착(40P01), 직렬화 실패(40001), 잠금 대기 초과(55P03),
# SQLite 잠김(SQLITE_BUSY·SQLITE_LOCKED).
RETRYABLE = {"40P01", "40001", "55P03", "SQLITE_BUSY", "SQLITE_LOCKED"}


def db_error_info(exc: BaseException) -> Optional[dict]:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    code = (getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
            or getattr(orig, "sqlite_errorname", None))
    return {"driver_error": type(orig).__name__, "sqlstate": code}


def error_label(exc: BaseException) -> str:
    """'OperationalError(DeadlockDetected, SQLSTATE 40P01)'처럼 화면·로그에 쓸 이름."""
    info = db_error_info(exc)
    if not info:
        return type(exc).__name__
    code = f", SQLSTATE {info['sqlstate']}" if info["sqlstate"] else ""
    return f"{type(exc).__name__}({info['driver_error']}{code})"


def is_retryable(exc: BaseException) -> bool:
    info = db_error_info(exc)
    return bool(info and info["sqlstate"] in RETRYABLE)
