"""실연동 통합 테스트 공통 설정.

LV_LIVE_TESTS=1일 때만 돈다(국가법령정보 OC·모델 API 키가 있는 CI 러너). 로컬·일반 CI에서는 건너뛴다.
항목(G1·J1·J2·R3·R4·R6·R10)마다 결과를 모아 LV_LIVE_RESULTS_OUT 파일(JSON)로 남긴다. 감사표(implementation_audit)는
이 파일에서 통과가 기록된 항목만 '완료(실연동)'로 바꾼다.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIVE = os.getenv("LV_LIVE_TESTS") == "1"
from tests.live._results import RESULTS, record  # noqa: F401  (테스트 모듈도 같은 객체를 쓴다)


def pytest_configure(config):
    config.addinivalue_line("markers", "live_item(item_id): 실연동 통합 테스트가 확인하는 감사 항목")


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="실연동 통합 테스트는 LV_LIVE_TESTS=1(API 키가 있는 CI)에서만 실행한다")
    for item in items:
        if "tests/live/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("live_item")
    if marker is None or report.when not in ("setup", "call"):
        return
    if report.when == "setup" and report.passed:
        return  # 준비 단계가 통과하면 본 실행 결과로 기록한다
    for item_id in marker.args:
        entry = RESULTS.setdefault(item_id, {})
        entry.setdefault("tests", []).append({"test": item.name, "outcome": report.outcome,
                                              "seconds": round(report.duration, 1)})
    _write()  # 테스트마다 바로 쓴다. 제한 시간으로 중간에 끊겨도 끝난 항목의 기록은 남는다


def _write() -> None:
    out = os.getenv("LV_LIVE_RESULTS_OUT")
    if not (LIVE and out and RESULTS):
        return
    for entry in RESULTS.values():
        tests = entry.get("tests") or []
        entry["passed"] = bool(tests) and all(t["outcome"] == "passed" for t in tests)
        entry["summary"] = entry.get("summary") or ""
        if not entry["summary"] or entry["summary"].startswith("실연동 테스트 "):
            entry["summary"] = f"실연동 테스트 {sum(t['outcome'] == 'passed' for t in tests)}/{len(tests)} 통과"
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit,
               "note": "CI '실연동 통합 테스트'가 국가법령정보센터·모델 API를 실제로 호출한 결과다. 기록이 없는 항목은 실행되지 않았다.",
               **RESULTS}
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def pytest_sessionfinish(session, exitstatus):
    _write()


@pytest.fixture(scope="session")
def live_env(tmp_path_factory):
    root = tmp_path_factory.mktemp("live")
    os.environ.setdefault("LV_DATA_DIR", str(root / "data"))
    os.environ.setdefault("LV_DATABASE_URL", f"sqlite:///{root}/live.db")
    os.environ.setdefault("LV_STORAGE_ROOT", str(root / "storage"))
    os.environ.setdefault("LV_PSEUDONYM_SECRET", "live-integration-only")
    os.environ["LV_ALLOW_NETWORK"] = "1"
    from packages.common.config import reset_settings
    reset_settings()
    return root


@pytest.fixture(scope="session")
def registry(live_env):
    from packages.source_adapters import SourceRegistry
    reg = SourceRegistry()
    if not os.getenv("LV_LAW_GO_KR_OC"):
        pytest.fail("LV_LAW_GO_KR_OC가 없어 국가법령정보센터 실연동을 확인할 수 없다(미확인으로 남긴다)")
    return reg
