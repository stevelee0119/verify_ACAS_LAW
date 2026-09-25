"""실연동 결과를 GitHub Actions 작업 요약과 경고 주석으로 보여 준다.

외부 출처 무응답으로 판정 보류된 항목은 테스트에서 건너뜀으로 처리되어 작업이 초록색으로 끝난다.
그런 실행을 '확인됨'으로 오해하지 않도록 항목마다 경고(::warning)를 띄우고, 감사표가 무엇을 근거로 쓰는지
(직전 통과 기록 또는 미확인)를 적는다. 작업의 성공·실패는 바꾸지 않는다(실패는 기존 '실패 표시' 단계가 정한다).

사용: python scripts/live_summary.py --results docs/live_integration_results.json --sha "$GITHUB_SHA"
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

STATUS_LABELS = {"passed": "통과", "failed": "실패", "unreachable": "판정 보류(외부 출처 무응답)", "not_run": "실행 안 됨"}


def items_of_run(payload: dict, sha: str) -> dict:
    """이번 실행(커밋 sha)에서 기록된 항목만 고른다. 짧은 커밋 값은 전체 sha의 앞부분이다."""
    return {k: v for k, v in payload.items()
            if isinstance(v, dict) and v.get("run_commit") and sha.startswith(str(v["run_commit"]))}


def summarize(payload: dict, sha: str) -> tuple[list[str], list[str]]:
    """(작업 요약 Markdown 줄, 워크플로 명령 줄)을 돌려준다."""
    items = items_of_run(payload, sha)
    if not items:
        return (["## 실연동 통합 테스트", "", "이번 실행에서 기록된 항목이 없습니다."],
                ["::warning title=실연동 결과 없음::이번 실행에서 기록된 실연동 항목이 없습니다"])
    lines = ["## 실연동 통합 테스트", "", "| 항목 | 이번 실행 | 준비 | 탐지 | 오탐 | 감사표 근거 |", "|---|---|---|---|---|---|"]
    commands = []
    for item_id in sorted(items):
        entry = items[item_id]
        status = entry.get("status") or ("passed" if entry.get("passed") else "failed")
        last = entry.get("last_pass") or {}
        if status == "passed":
            basis = "이번 실행 통과"
        elif status == "unreachable" and last:
            basis = f"직전 통과 기록(커밋 {last.get('commit')}, {last.get('at')})"
        else:
            basis = "미확인"
        lines.append(f"| {item_id} | {STATUS_LABELS.get(status, status)} | {entry.get('prepared', '—')} | "
                     f"{entry.get('detected', '—')} | {entry.get('false_positive', '—')} | {basis} |")
        if status == "unreachable":
            why = entry.get("unreachable") or "외부 출처 무응답"
            tail = (f"감사표는 직전 통과 기록(커밋 {last.get('commit')})을 근거로 씁니다"
                    if last else "직전 통과 기록이 없어 감사표에서 미확인입니다")
            commands.append(f"::warning title=실연동 {item_id} 판정 보류::{why}. 이번 실행으로는 확인하지 못했습니다. {tail}")
        elif status == "failed":
            commands.append(f"::error title=실연동 {item_id} 실패::{entry.get('summary') or '기준 미달'}")
    silent = [k for k, v in items.items() if v.get("status") == "unreachable"]
    if silent:
        lines += ["", f"> 경고: {len(silent)}개 항목({', '.join(sorted(silent))})은 외부 출처가 응답하지 않아 이번 실행으로 확인하지 못했습니다. "
                      "작업이 성공으로 표시되어도 이 항목들은 이번 코드로 다시 확인된 것이 아닙니다."]
    return lines, commands


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="docs/live_integration_results.json")
    parser.add_argument("--sha", default=os.getenv("GITHUB_SHA", ""))
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.results).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    lines, commands = summarize(payload, args.sha)
    for command in commands:
        print(command)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
