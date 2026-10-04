"""보호 경로 변경 점검 (평가 에이전트 소관, 보호 경로). 2026-10-04 사용자 승인 '검증 실행 중복 줄이기'의 선행 조건.

같은 SHA의 CI 결과를 평가 판정에 그대로 쓰려면, CI가 무엇을 어떻게 재는지(평가 도구·시험 자료·워크플로)를
구현 측이 바꾸지 않았다는 것이 기계로 확인되어야 한다. 이 도구는 `--base`부터 HEAD까지 바뀐 보호 경로 파일마다
그 파일을 마지막으로 바꾼 커밋(병합 해결로 바뀐 경우 그 병합 커밋)을 찾아, `Agent: evaluator` 꼬리표가 없으면 실패한다.

- 실패(종료 코드 1): 평가 측이 아닌 커밋이 보호 경로를 바꿨다. 평가 측이 검토해 승인하면
  `docs/scorecards/approved_protected_changes.json`에 {"path", "commit"}를 적는다. 그 파일을 마지막으로 바꾼 커밋이
  `Agent: evaluator`일 때만 목록을 믿는다(시험 표시 승인 목록과 같은 방식).
- 한계: 꼬리표는 커밋 작성자의 선언이다. 평가 측의 diff 검토가 마지막 방어선이며, 이 도구는 놓침을 줄이는 장치다.
사용: python scripts/check_protected_paths.py --base <기준 커밋>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import List, Optional, Set, Tuple

# docs/AGENT_ROLES.md 1장 보호 경로 + CI 신뢰에 필요한 워크플로·평가 도구(2026-10-04 추가)
PROTECTED = (
    "tests/acceptance/**", "tests/fixtures/**",
    "scripts/verify_all.py", "scripts/eval_testset.py", "scripts/scorecard.py", "scripts/score_gate.py",
    "scripts/probe_document.py", "scripts/score_report.py", "scripts/check_case_literals.py",
    "scripts/check_version_policy.py", "scripts/review_feedback_report.py",
    "scripts/regression_gate.py", "scripts/check_hardcoding_diff.py", "scripts/check_test_edits.py",
    "scripts/check_protected_paths.py", "scripts/ci_failed_tests.py",
    "docs/scorecards/**", ".github/workflows/score-gate.yml", ".github/workflows/ci.yml",
    "docs/AGENT_ROLES.md", "AGENTS.md", "CLAUDE.md", ".github/CODEOWNERS",
)
APPROVALS = "docs/scorecards/approved_protected_changes.json"
EVALUATOR = re.compile(r"^Agent:\s*evaluator\s*$", re.MULTILINE)


def _git(*args: str) -> Tuple[int, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return r.returncode, r.stdout


def changed_files(base: str) -> List[str]:
    code, out = _git("diff", "--name-only", "--no-renames", base, "HEAD", "--", *[f":(glob){p}" for p in PROTECTED])
    if code != 0:
        raise RuntimeError(f"기준 커밋 {base}과 비교하지 못했다")
    return sorted(line for line in out.splitlines() if line)


def last_change(path: str) -> Tuple[str, str]:
    """(커밋 SHA, 커밋 메시지). 기본 이력 단순화를 쓰므로 병합 해결로만 바뀐 경우 그 병합 커밋이 나온다."""
    _, out = _git("log", "-1", "--format=%H%x00%B", "HEAD", "--", path)
    sha, _, body = out.partition("\x00")
    return sha.strip(), body


def approved() -> Set[Tuple[str, str]]:
    code, source = _git("show", f"HEAD:{APPROVALS}")
    if code != 0:
        return set()
    _, body = last_change(APPROVALS)
    if not EVALUATOR.search(body):
        return set()
    try:
        items = json.loads(source).get("approved", [])
    except (ValueError, AttributeError):
        return set()
    return {(str(i.get("path", "")), str(i.get("commit", ""))) for i in items if isinstance(i, dict)}


def _is_approved(path: str, sha: str, allowed: Set[Tuple[str, str]]) -> bool:
    return any(p == path and len(c) >= 7 and sha.startswith(c) for p, c in allowed)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        files = changed_files(a.base)
    except RuntimeError as exc:
        print(f"보호 경로 점검: 측정 못 함 — {exc}")
        return 2
    if not files:
        print("보호 경로 점검: 바뀐 보호 경로 없음")
        return 0
    allowed = approved()
    bad = []
    for path in files:
        sha, body = last_change(path)
        subject = body.strip().splitlines()[0][:80] if body.strip() else ""
        if EVALUATOR.search(body):
            print(f"  [평가 측] {path} — {sha[:7]} {subject}")
        elif _is_approved(path, sha, allowed):
            print(f"  [승인] {path} — {sha[:7]} {subject}")
        else:
            print(f"  [보호 경로 변경] {path} — {sha[:7]} {subject}")
            bad.append(path)
    if bad:
        print(f"보호 경로 점검: 평가 측이 아닌 커밋이 보호 경로 {len(bad)}개를 바꿨다 — 평가 측 검토·승인이 필요하다")
        return 1
    print(f"보호 경로 점검: 바뀐 보호 경로 {len(files)}개 모두 평가 측 커밋 또는 승인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
