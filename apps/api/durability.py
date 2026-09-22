"""배포 저장소가 재시작을 견디는지 스스로 점검한다.

이 점검이 없으면 잘못된 구성이 조용히 정상처럼 동작한다. 실제로 SQLite가
컨테이너 내부에 생성된 배포에서, 화면은 정상인데 재시작마다 로그인·프로젝트·
업로드 원본·감사기록이 통째로 사라지는 상태가 오래 발견되지 않았다.

확정할 수 없는 것은 확정하지 않는다. 경로가 마운트된 디스크인지는 프로세스
안에서 알 수 없으므로, 명백히 위험한 경우만 AT_RISK로 표시하고 나머지는
UNKNOWN으로 남긴다. 판단 근거를 함께 싣는다.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlsplit

from packages.common.config import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

# 관리형 플랫폼 표지. 이런 환경의 컨테이너 파일시스템은 디스크를 따로 붙이지
# 않으면 재배포·재시작 때 초기화된다.
PLATFORM_MARKERS = ("RENDER_SERVICE_ID", "K_SERVICE", "DYNO", "WEBSITE_SITE_NAME",
                    "FLY_APP_NAME", "RAILWAY_SERVICE_ID")

DURABLE, AT_RISK, UNKNOWN = "DURABLE", "AT_RISK", "UNKNOWN"
_RANK = {DURABLE: 0, UNKNOWN: 1, AT_RISK: 2}

AT_RISK_CONTENTS = ["로그인 세션", "프로젝트와 검증 기록", "업로드 원본", "감사기록"]


def managed_platform() -> str:
    return next((name for name in PLATFORM_MARKERS if os.getenv(name)), "")


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    path = urlsplit(url).path.lstrip("/")
    return Path("/" + path) if url.startswith("sqlite:////") else Path(path or ":memory:")


def mounted_volume(path: Path) -> bool:
    """경로가 상위와 다른 파일시스템에 있으면 별도 볼륨이 붙어 있는 것이다.

    디스크를 애플리케이션 디렉터리 안에 마운트하는 배포도 있다. 경로만 보고
    위험하다고 하면 정상 구성을 잘못 경고하게 되므로 실제 마운트를 확인한다.
    """
    node = path
    while not node.exists() and node != node.parent:
        node = node.parent
    if node == node.parent:
        return False
    try:
        return os.stat(node).st_dev != os.stat(node.parent).st_dev
    except OSError:  # pragma: no cover - 접근 불가 경로
        return False


def _path_state(path: Path, *, configured: bool) -> tuple[str, str]:
    """경로 하나의 내구성 추정. 마운트 여부는 알 수 없으므로 단정하지 않는다."""
    platform = managed_platform()
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover - 접근 불가 경로
        return UNKNOWN, "경로를 확인하지 못했습니다"
    if str(resolved) == ":memory:" or "memory" in str(resolved):
        return AT_RISK, "메모리 저장소입니다. 프로세스가 끝나면 사라집니다"
    if mounted_volume(resolved):
        return UNKNOWN, (f"{resolved}는 별도 볼륨에 있습니다. 영구 디스크인지, "
                         f"tmpfs 같은 휘발성 볼륨인지는 배포 설정에서 확인하세요")
    if resolved.is_relative_to(REPO_ROOT):
        return AT_RISK, f"애플리케이션 디렉터리 안({resolved})에 있습니다. 재배포하면 사라집니다"
    if platform and not configured:
        return AT_RISK, (f"{platform} 환경인데 저장 위치가 지정되지 않았습니다. "
                         f"컨테이너 파일시스템({resolved})은 재시작 시 초기화됩니다")
    if platform:
        return UNKNOWN, (f"{resolved}가 영구 디스크에 마운트되어 있는지는 "
                         f"프로세스 안에서 확인할 수 없습니다. 배포 설정에서 확인하세요")
    return UNKNOWN, f"{resolved}의 보존 여부는 운영 환경 설정에 달려 있습니다"


def durability_report() -> Dict[str, Any]:
    """저장소 내구성 점검 결과."""
    settings = get_settings()
    url = settings.database_url or ""
    dialect = urlsplit(url).scheme.split("+")[0] or "unknown"

    if dialect and dialect != "sqlite":
        database = {"kind": dialect, "state": DURABLE,
                    "reason": "외부 데이터베이스를 사용합니다. 컨테이너 수명과 분리됩니다"}
    else:
        sqlite_path = _sqlite_path(url) or Path("unknown")
        state, reason = _path_state(sqlite_path,
                                    configured=bool(os.getenv("LV_DATABASE_URL") or os.getenv("DATABASE_URL")))
        database = {"kind": "sqlite", "state": state, "reason": reason, "path": str(sqlite_path)}

    storage_state, storage_reason = _path_state(
        Path(settings.storage_root),
        configured=bool(os.getenv("LV_STORAGE_ROOT") or os.getenv("LV_DATA_DIR")),
    )
    storage = {"kind": getattr(settings, "storage_backend", "local"), "state": storage_state,
               "reason": storage_reason, "path": str(settings.storage_root)}
    if storage["kind"] in ("s3", "minio"):
        storage.update(state=DURABLE, reason="외부 객체 저장소를 사용합니다")

    verdict = max((database["state"], storage["state"]), key=lambda s: _RANK[s])
    at_risk: List[str] = []
    if database["state"] == AT_RISK:
        at_risk.extend(["로그인 세션", "프로젝트와 검증 기록", "감사기록"])
    if storage["state"] == AT_RISK:
        at_risk.append("업로드 원본")

    return {
        "verdict": verdict,
        "database": database,
        "storage": storage,
        "at_risk": at_risk,
        "platform": managed_platform(),
        "remedy": ("LV_DATABASE_URL을 외부 데이터베이스로 지정하고, 업로드 원본은 "
                   "영구 디스크(LV_DATA_DIR) 또는 객체 저장소에 두세요."),
        "note": ("경로가 영구 디스크에 마운트되었는지는 프로세스 안에서 확인할 수 없습니다. "
                 "UNKNOWN은 '안전함'이 아니라 '확인하지 못함'입니다."),
    }


def log_durability_warning(report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """기동 시 한 번 경고한다. 배포 직후 로그에서 바로 보이게 한다."""
    report = report or durability_report()
    if report["verdict"] != AT_RISK:
        return report
    log.warning(
        "저장소가 재시작을 견디지 못합니다. 재시작·재배포 때 %s이(가) 사라집니다. "
        "데이터베이스: %s / 업로드 원본: %s / 조치: %s",
        ", ".join(report["at_risk"]) or "저장된 내용",
        report["database"]["reason"], report["storage"]["reason"], report["remedy"],
    )
    return report
