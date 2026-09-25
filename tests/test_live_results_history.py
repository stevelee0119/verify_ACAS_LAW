"""실연동 결과 기록 규칙(오프라인). 외부 출처 무응답은 실패도 통과도 아니고, 이전 통과 기록을 지우지 않는다."""
from __future__ import annotations

import pytest

from tests.live import _results as R


def _entry(outcome, detected=3):
    return {"prepared": 3, "detected": detected, "false_positive": 0, "summary": f"조회 {detected}/3",
            "tests": [{"test": "t", "outcome": outcome, "seconds": 1.0}]}


def test_unreachable_needs_every_lookup_silent():
    assert R.unreachable(["TIMEOUT", "AdapterStatus.RATE_LIMITED"])
    assert not R.unreachable(["TIMEOUT", "READY"])
    assert not R.unreachable(["ERROR"])  # 어댑터 결함일 수 있어 무응답으로 보지 않는다
    assert not R.unreachable([])


def test_inconclusive_only_when_every_answered_lookup_was_right():
    R.RESULTS.clear()
    R.skip_if_inconclusive("G1", reachable_failures=1, unreachable_cases=5, why="조회")  # 틀린 응답이 있으면 보류하지 않는다
    R.skip_if_inconclusive("G1", reachable_failures=0, unreachable_cases=0, why="조회")  # 무응답이 없어도 보류하지 않는다
    with pytest.raises(pytest.skip.Exception):
        R.skip_if_inconclusive("G1", reachable_failures=0, unreachable_cases=4, why="조회")
    assert "무응답 4건" in R.RESULTS["G1"]["unreachable"]


def test_unreachable_run_keeps_previous_pass():
    first = R.merge({}, {"R4": _entry("passed")}, "aaa1111", "2026-09-24T00:00:00+00:00")
    second = R.merge(first, {"R4": _entry("skipped", detected=0)}, "bbb2222", "2026-09-25T00:00:00+00:00")
    item = second["R4"]
    assert item["status"] == "unreachable" and not item["passed"]
    assert item["last_pass"]["commit"] == "aaa1111" and item["last_pass"]["detected"] == 3


def test_failed_run_is_marked_failed_even_with_previous_pass():
    first = R.merge({}, {"J1": _entry("passed")}, "aaa1111", "t1")
    second = R.merge(first, {"J1": _entry("failed", detected=1)}, "ccc3333", "t2")
    assert second["J1"]["status"] == "failed" and second["J1"]["passed"] is False


def test_legacy_file_without_last_pass_is_upgraded():
    legacy = {"generated_at": "t0", "commit": "b73504d", "G1": {**_entry("passed"), "passed": True}}
    merged = R.merge(legacy, {"G1": _entry("skipped", detected=0)}, "e41c7b6", "t1")
    assert merged["G1"]["last_pass"]["commit"] == "b73504d" and merged["G1"]["last_pass"]["at"] == "t0"


def test_items_not_run_this_time_are_kept():
    first = R.merge({}, {"R3": _entry("passed")}, "aaa1111", "t1")
    second = R.merge(first, {"J2": _entry("failed", detected=0)}, "ddd4444", "t2")
    assert second["R3"]["passed"] is True and second["J2"]["status"] == "failed"
