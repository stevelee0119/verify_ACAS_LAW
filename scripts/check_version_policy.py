"""프로그램 버전 정책 점검(평가 에이전트 소관, 보호 경로). 정책: docs/scorecards/VERSION_POLICY.md

버전(`packages/common/config.py`의 `Settings.version`, X.Y.Z)은 **커밋이 아니라 평가 측이 잰 성능**으로만 올린다.
- 정수 X: 성능의 급격한 상승 (사용자 승인 필요)
- 소수점 첫째 자리 Y: 일부 성능 개선
- 소수점 둘째 자리 Z: 미세한 성능 개선
이 도구는 기준 커밋 이후 버전이 바뀐 모든 커밋을 찾아 다음을 확인한다.
1. 바뀐 버전은 **한 단계만** 오른다(내려가기·단계 건너뛰기 불가). 올린 자리 아래 자리는 0으로 되돌린다(예: 0.9.13 → 0.9.14 / 0.10.0 / 1.0.0).
2. `docs/scorecards/version_verdicts.json`에 그 버전의 **판정서**(평가 측이 작성)가 있고, 판정서의 `from`·`level`이 실제 상향과 같다.
3. 판정서에 측정 커밋·측정 조건·근거 수치가 있다. 정수 상향은 `user_approved: true`다.
4. 판정서 하나는 한 번만 쓰인다(같은 버전을 두 번 올리거나 한 판정으로 두 단계를 올릴 수 없다).
버전이 바뀌지 않은 커밋은 통과다. 즉 **판정서 없는 상향(커밋마다 올리기)은 실패**한다.

    python scripts/check_version_policy.py --base HEAD~1        # 종료 코드: 0 통과, 1 위반, 2 측정 못 함
    python scripts/check_version_policy.py --base origin/main   # 범위 안 모든 커밋을 본다
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "packages/common/config.py"
VERDICTS = ROOT / "docs" / "scorecards" / "version_verdicts.json"
VERSION_RE = re.compile(r'^\s*version:\s*str\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.M)
LEVELS = ("major", "minor", "patch")
REQUIRED = ("version", "from", "level", "measured_commit", "conditions", "evidence", "decided_by", "decided_at")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    match = VERSION_RE.search(text or "")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def fmt(version: Tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def bump_level(old: Tuple[int, int, int], new: Tuple[int, int, int]) -> Optional[str]:
    """한 단계 상향이면 'major'|'minor'|'patch', 같으면 None, 그 밖에는 'invalid'."""
    if new == old:
        return None
    if new[0] == old[0] + 1 and new[1:] == (0, 0):
        return "major"
    if new[0] == old[0] and new[1] == old[1] + 1 and new[2] == 0:
        return "minor"
    if new[:2] == old[:2] and new[2] == old[2] + 1:
        return "patch"
    return "invalid"


def load_verdicts(path: Path = VERDICTS) -> List[Dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def check_bump(old: Tuple[int, int, int], new: Tuple[int, int, int], verdicts: List[Dict], used: set) -> List[str]:
    """한 번의 상향을 판정서와 대조한다. 위반 사유 목록(비어 있으면 통과)."""
    problems: List[str] = []
    level = bump_level(old, new)
    if level is None:
        return problems
    label = f"{fmt(old)} → {fmt(new)}"
    if level == "invalid":
        return [f"{label}: 한 단계 상향이 아니다(내려가기·건너뛰기·아래 자리 미초기화). 허용: "
                f"{old[0]}.{old[1]}.{old[2] + 1} / {old[0]}.{old[1] + 1}.0 / {old[0] + 1}.0.0"]
    matches = [v for v in verdicts if v.get("version") == fmt(new)]
    if not matches:
        return [f"{label}: 판정서가 없다(docs/scorecards/version_verdicts.json). 버전은 평가 측 판정 뒤에만 올린다"]
    verdict = matches[-1]
    missing = [key for key in REQUIRED if not verdict.get(key)]
    if missing:
        problems.append(f"{label}: 판정서에 빠진 항목 {missing}")
    if verdict.get("from") != fmt(old):
        problems.append(f"{label}: 판정서의 from({verdict.get('from')})이 실제 이전 버전과 다르다")
    if verdict.get("level") != level:
        problems.append(f"{label}: 판정서의 등급({verdict.get('level')})과 실제 상향 자리({level})가 다르다")
    if level == "major" and verdict.get("user_approved") is not True:
        problems.append(f"{label}: 정수 상향은 사용자 승인(user_approved: true)이 필요하다")
    if fmt(new) in used:
        problems.append(f"{label}: 같은 판정서로 이미 상향했다")
    used.add(fmt(new))
    return problems


def git(*args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def version_at(rev: str) -> Optional[Tuple[int, int, int]]:
    return parse_version(git("show", f"{rev}:{CONFIG}") or "")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="HEAD~1", help="이 커밋 이후(제외) HEAD까지의 모든 커밋을 본다")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    commits_out = git("rev-list", "--reverse", f"{args.base}..{args.head}")
    previous = version_at(args.base)
    if commits_out is None or previous is None:
        print("측정하지 못했다: 기준 커밋·버전을 읽지 못했다", file=sys.stderr)
        return 2
    verdicts = load_verdicts()
    problems: List[str] = []
    used: set = set()
    steps: List[str] = []
    for sha in commits_out.split():
        current = version_at(sha)
        if current is None:
            print(f"측정하지 못했다: {sha[:7]}에서 버전을 읽지 못했다", file=sys.stderr)
            return 2
        found = check_bump(previous, current, verdicts, used)
        if current != previous:
            steps.append(f"{sha[:7]} {fmt(previous)} → {fmt(current)}")
        problems.extend(f"{sha[:7]} {p}" for p in found)
        previous = current
    if problems:
        print("버전 정책 위반:")
        for p in problems:
            print("  - " + p)
        return 1
    print("버전 정책: 위반 없음" + (f" (상향 {len(steps)}건: " + "; ".join(steps) + ")" if steps else " (버전 변경 없음)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
