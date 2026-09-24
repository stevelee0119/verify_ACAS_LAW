"""휴지통에 있는 프로젝트를 영구 삭제한다.

프로젝트에서 외래키로 이어지는 모든 행(자료·검증 실행·판정·보고서·검토 기록 등)을 찾아
자식부터 지운 뒤 프로젝트 행을 지운다. 테이블 목록을 손으로 적지 않고 스키마의 외래키를
따라가므로, 테이블이 늘어도 빠뜨리지 않는다.

지우지 않는 것:
- 감사기록(audit_events): 수정·삭제하지 않는 해시 체인이다(부록 C 제7항). 영구 삭제
  사실도 여기에 남긴다. 사건 내용은 싣지 않고 지운 건수만 적는다.
- 사용자·조직 등 프로젝트에 속하지 않는 행.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import delete, func, or_, select

from packages.common.config import data_dir
from packages.common.storage import PROJECT_ID_RE, get_storage

from .db import Base

logger = logging.getLogger(__name__)
KEEP_TABLES = {"audit_events"}


def _conditions(project_id: str) -> Dict[str, object]:
    """테이블마다 '이 프로젝트에 속한 행' 조건. 부모 조건을 하위 질의로 물려받는다."""
    from . import identity, job_control, workspace  # noqa: F401 - 모든 테이블을 메타데이터에 등록한다
    projects = Base.metadata.tables["projects"]
    conditions: Dict[str, object] = {"projects": projects.c.id == project_id}
    for table in Base.metadata.sorted_tables:  # 부모가 자식보다 먼저 나온다
        if table.name in conditions or table.name in KEEP_TABLES:
            continue
        links = [column.in_(select(fk.column).where(conditions[fk.column.table.name]))
                 for column in table.columns for fk in column.foreign_keys
                 if fk.column.table.name in conditions]
        if links:
            conditions[table.name] = or_(*links)
    return conditions


def purge_rows(session, project_id: str) -> Dict[str, int]:
    """프로젝트에 속한 행을 자식부터 지운다. 커밋은 호출자가 한다."""
    conditions = _conditions(project_id)
    order: List = [t for t in reversed(Base.metadata.sorted_tables) if t.name in conditions]
    counts = {t.name: session.scalar(select(func.count()).select_from(t).where(conditions[t.name])) or 0
              for t in order}
    for table in order:
        if counts[table.name]:
            session.execute(delete(table).where(conditions[table.name]))
    return {name: n for name, n in counts.items() if n}


def purge_files(project_id: str) -> Dict[str, object]:
    """DB 삭제를 커밋한 뒤 호출한다. 파일 삭제가 실패해도 DB는 이미 지워졌으므로 결과만 알린다."""
    result: Dict[str, object] = {"files_removed": 0, "file_errors": []}
    try:
        result["files_removed"] = get_storage().delete_project_files(project_id)
    except Exception as exc:  # 저장소 오류는 삭제 결과와 로그로 알린다
        logger.error("project_purge_files_failed project=%s error_type=%s", project_id, type(exc).__name__)
        result["file_errors"].append(f"원본·보고서 파일: {type(exc).__name__}")
    if PROJECT_ID_RE.match(project_id):
        vault = data_dir() / "pii_vault" / f"{project_id}.vault"
        try:
            if vault.exists():
                vault.unlink()
        except OSError as exc:
            logger.error("project_purge_vault_failed project=%s error_type=%s", project_id, type(exc).__name__)
            result["file_errors"].append(f"가명 처리 보관소: {type(exc).__name__}")
    return result
