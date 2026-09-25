"""실연동 결과 저장소. conftest와 테스트 모듈이 같은 객체를 쓰도록 따로 둔다(모듈 사본 문제 방지)."""
from __future__ import annotations

import pytest

RESULTS: dict = {}

# 출처가 응답하지 않은 조회. 판정 근거가 없으므로 실패도 통과도 아니다(ERROR는 어댑터 결함일 수 있어 넣지 않는다).
UNREACHABLE = {"TIMEOUT", "RATE_LIMITED"}


def record(item_id: str, *, prepared: int, detected: int, false_positive: int = 0, summary: str = "",
           cases: list | None = None, diagnostics: dict | None = None) -> None:
    """테스트가 항목별 준비·탐지·오탐 수와 진단 정보를 남긴다(통과 여부는 테스트 결과로 정한다)."""
    RESULTS.setdefault(item_id, {}).update({"prepared": prepared, "detected": detected,
                                             "false_positive": false_positive, "summary": summary,
                                             "cases": cases or [], "diagnostics": diagnostics or {}})


def unreachable(statuses) -> bool:
    """조회 상태가 모두 '응답 없음'이면 참."""
    statuses = [str(s).rsplit(".", 1)[-1] for s in statuses]
    return bool(statuses) and all(s in UNREACHABLE for s in statuses)


def skip_if_inconclusive(item_id: str, reachable_failures: int, unreachable_cases: int, why: str) -> None:
    """응답한 조회는 모두 맞았고 나머지가 무응답이라 기준을 못 채운 경우만 판정 보류(skip)로 둔다.
    응답한 조회 가운데 하나라도 틀리면 그대로 실패다."""
    if reachable_failures == 0 and unreachable_cases:
        RESULTS.setdefault(item_id, {})["unreachable"] = f"{why}: 무응답 {unreachable_cases}건"
        pytest.skip(f"외부 출처 무응답으로 판정 보류({why}: {unreachable_cases}건)")


NOTE = ("CI '실연동 통합 테스트'가 국가법령정보센터·모델 API를 실제로 호출한 결과다. status: passed(통과)·"
        "failed(응답을 받았으나 기준 미달)·unreachable(외부 출처 무응답으로 판정 보류, last_pass는 이전 통과 기록). "
        "기록이 없는 항목은 실행되지 않았다.")


def merge(previous: dict, results: dict, commit: str, now: str) -> dict:
    """이번 실행 결과를 이전 결과 파일과 합친다.

    - 통과: last_pass를 이번 실행으로 바꾼다.
    - 판정 보류(무응답)·실패: 이전 통과 기록을 last_pass로 남긴다. 실패는 감사표에서 last_pass와 관계없이 미확인이다.
    - 이번에 실행하지 않은 항목은 이전 기록을 그대로 둔다.
    """
    items = {}
    for key, value in previous.items():
        if isinstance(value, dict):
            # 이번에 다시 쓰지 않는 항목도 원래 실행의 커밋·시각을 지닌다. 같은 실행 중 여러 번 쓰면 파일 머리의
            # commit이 이번 커밋으로 바뀌므로, 머리 값에 기대면 이전 통과가 이번 커밋으로 잘못 찍힌다.
            value = dict(value)
            value.setdefault("run_commit", previous.get("commit"))
            value.setdefault("run_at", previous.get("generated_at"))
            items[key] = value
    for item_id, entry in results.items():
        entry = dict(entry)
        tests = entry.get("tests") or []
        outcomes = {t["outcome"] for t in tests}
        entry["passed"] = bool(tests) and outcomes == {"passed"}
        entry["status"] = ("passed" if entry["passed"] else "failed" if "failed" in outcomes
                           else "unreachable" if "skipped" in outcomes else "not_run")
        entry["run_commit"], entry["run_at"] = commit, now
        if not entry.get("summary") or entry["summary"].startswith("실연동 테스트 "):
            entry["summary"] = f"실연동 테스트 {sum(t['outcome'] == 'passed' for t in tests)}/{len(tests)} 통과"
        old = items.get(item_id) or {}
        entry.pop("last_pass", None)
        if entry["passed"]:
            last = {"commit": commit, "at": now}
            source = entry
        else:
            last = old.get("last_pass")
            source = None
            if last is None and old.get("passed"):
                last = {"commit": old.get("run_commit"), "at": old.get("run_at")}
                source = old
        if source is not None:
            last.update({k: source.get(k) for k in ("prepared", "detected", "false_positive", "summary")})
        if last:
            entry["last_pass"] = last
        items[item_id] = entry
    return {"generated_at": now, "commit": commit, "note": NOTE, **items}
