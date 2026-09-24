"""저장 공간 점검·회수와 DB 연결 상태.

PostgreSQL은 행을 지워도 디스크 파일을 바로 줄이지 않는다(MVCC: 지운 행은 '죽은 행'으로 남는다).
- VACUUM: 죽은 행 자리를 다시 쓸 수 있게 하고, 테이블 끝의 빈 페이지만 운영체제에 돌려준다.
  읽기·쓰기를 막지 않는다. 영구 삭제 뒤 자동으로 실행한다.
- VACUUM FULL: 테이블을 새로 써서 빈 공간을 돌려준다. 그동안 그 테이블을 잠그고, 테이블 크기만큼의
  여유 공간이 필요하다. 관리자가 사용량이 적을 때 직접 실행한다.
Render Postgres는 늘린 저장 용량을 줄일 수 없다. 이 기능은 같은 용량 안에서 공간을 다시 쓰게 할 뿐이다.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

from packages.common.config import get_settings

from .db import get_engine
from .db_errors import db_error_info, error_label

logger = logging.getLogger(__name__)
TOP_TABLES = 12


def database_status() -> Dict[str, Any]:
    """헬스체크용. DB에 짧은 질의를 보내 연결을 확인한다. 실패해도 예외를 내지 않는다."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # 헬스체크는 원인만 알리고 실패하지 않는다
        info = db_error_info(exc) or {}
        return {"status": "error", "error_type": error_label(exc), "sqlstate": info.get("sqlstate")}


def _dir_size(path: Path) -> int:
    total = 0
    if path.exists():
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    return total


def _file_storage() -> Dict[str, Any]:
    root = Path(get_settings().storage_root)
    parts = {name: _dir_size(root / name) for name in ("originals", "derivatives", "tmp", "plaintext-cache")}
    return {"root_bytes": sum(parts.values()), "parts": parts}


def storage_report() -> Dict[str, Any]:
    """DB·파일 저장소 사용량. 테이블별 크기와 죽은 행 수로 회수 가능한 공간을 가늠한다."""
    engine = get_engine()
    report: Dict[str, Any] = {"dialect": engine.dialect.name, "files": _file_storage()}
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            report["database_bytes"] = connection.scalar(text("SELECT pg_database_size(current_database())"))
            rows = connection.execute(text(
                "SELECT relname, pg_total_relation_size(relid) AS total, n_live_tup, n_dead_tup, "
                "last_vacuum, last_autovacuum FROM pg_stat_user_tables "
                "ORDER BY pg_total_relation_size(relid) DESC")).mappings().all()
            tables = [{"table": r["relname"], "bytes": int(r["total"] or 0), "live_rows": int(r["n_live_tup"] or 0),
                       "dead_rows": int(r["n_dead_tup"] or 0),
                       "last_vacuum": str(max(filter(None, [r["last_vacuum"], r["last_autovacuum"]]), default="") or "")}
                      for r in rows]
            report["dead_rows"] = sum(t["dead_rows"] for t in tables)
            report["tables"] = tables[:TOP_TABLES]
        else:
            page_size = connection.scalar(text("PRAGMA page_size")) or 0
            pages = connection.scalar(text("PRAGMA page_count")) or 0
            free = connection.scalar(text("PRAGMA freelist_count")) or 0
            report["database_bytes"] = int(page_size * pages)
            report["free_bytes"] = int(page_size * free)
            report["tables"] = []
    report["note"] = ("행을 지워도 DB 파일은 바로 줄지 않습니다. '빈 공간 정리'는 지운 자리를 다시 쓰게 하고, "
                      "'디스크 반환'은 테이블을 새로 써서 공간을 돌려줍니다(그동안 해당 테이블 잠김). "
                      "호스팅에서 늘린 저장 용량은 줄어들지 않습니다.")
    return report


def vacuum(tables: Optional[Iterable[str]] = None, *, full: bool = False) -> Dict[str, Any]:
    """VACUUM(또는 VACUUM FULL)을 실행한다. 트랜잭션 밖(autocommit)에서만 실행된다."""
    engine = get_engine()
    started = time.monotonic()
    before = _database_bytes(engine)
    done: List[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if engine.dialect.name == "postgresql":
            names = list(tables) if tables else [None]
            for name in names:
                target = "" if name is None else f' "{_safe_name(name)}"'
                connection.execute(text(f"VACUUM ({'FULL, ' if full else ''}ANALYZE){target}"))
                done.append(name or "*")
        else:
            connection.execute(text("VACUUM"))
            done.append("*")
    after = _database_bytes(engine)
    return {"full": full, "tables": done, "before_bytes": before, "after_bytes": after,
            "freed_bytes": max(0, (before or 0) - (after or 0)), "seconds": round(time.monotonic() - started, 2)}


def vacuum_in_background(tables: Iterable[str]) -> None:
    """영구 삭제 뒤 지운 테이블을 정리한다. 요청 응답을 늦추지 않도록 따로 실행한다."""
    names = sorted(set(tables))
    if not names or get_engine().dialect.name != "postgresql":
        return

    def run():
        try:
            vacuum(names)
        except Exception as exc:  # 정리 실패는 다음 자동 정리(autovacuum)에 맡긴다
            logger.warning("post_purge_vacuum_failed error=%s", error_label(exc))

    threading.Thread(target=run, name="post-purge-vacuum", daemon=True).start()


def _database_bytes(engine) -> Optional[int]:
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            return int(connection.scalar(text("SELECT pg_database_size(current_database())")) or 0)
        page_size = connection.scalar(text("PRAGMA page_size")) or 0
        return int(page_size * (connection.scalar(text("PRAGMA page_count")) or 0))


def _safe_name(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError("invalid table name")
    return name
