"""실연동 결과 요약·무응답 경고(scripts/live_summary.py)."""
from __future__ import annotations

from scripts.live_summary import summarize

SHA = "075cf9411379adde45645bfbfdd288190b57e2c1"


def _item(status, commit="075cf94", last=None, **extra):
    entry = {"status": status, "passed": status == "passed", "run_commit": commit, "prepared": 3,
             "detected": 3 if status == "passed" else 0, "false_positive": 0, "summary": "요약", **extra}
    if last:
        entry["last_pass"] = last
    return entry


def test_unreachable_with_previous_pass_warns_and_names_the_basis():
    payload = {"commit": "075cf94", "G1": _item("unreachable", unreachable="헌재 결정 조회: 무응답 11건",
                                                  last={"commit": "b73504d", "at": "t0"})}
    lines, commands = summarize(payload, SHA)
    assert commands == ["::warning title=실연동 G1 판정 보류::헌재 결정 조회: 무응답 11건. 이번 실행으로는 확인하지 못했습니다. "
                        "감사표는 직전 통과 기록(커밋 b73504d)을 근거로 씁니다"]
    assert any("직전 통과 기록(커밋 b73504d" in line for line in lines)
    assert any(line.startswith("> 경고: 1개 항목(G1)") for line in lines)


def test_unreachable_without_previous_pass_is_reported_as_unconfirmed():
    lines, commands = summarize({"R3": _item("unreachable")}, SHA)
    assert "직전 통과 기록이 없어 감사표에서 미확인" in commands[0]
    assert any(line.endswith("| 미확인 |") for line in lines)


def test_passed_items_raise_no_annotation_and_failures_raise_errors():
    payload = {"J2": _item("passed"), "R10": _item("failed", summary="문서 판정 불일치")}
    lines, commands = summarize(payload, SHA)
    assert commands == ["::error title=실연동 R10 실패::문서 판정 불일치"]
    assert not any(line.startswith("> 경고") for line in lines)


def test_items_from_earlier_runs_are_not_counted_for_this_run():
    payload = {"G1": _item("unreachable", commit="e41c7b6"), "J2": _item("passed")}
    lines, commands = summarize(payload, SHA)
    assert commands == [] and not any("| G1 |" in line for line in lines)


def test_no_items_for_this_run_warns():
    _, commands = summarize({"G1": _item("passed", commit="b73504d")}, SHA)
    assert commands and commands[0].startswith("::warning title=실연동 결과 없음")
