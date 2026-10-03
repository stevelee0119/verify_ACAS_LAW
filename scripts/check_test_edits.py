"""기존 시험의 삭제·약화를 잡는다 (TK-49·TK-50: 7차 보완·7C가 원장 기대값을 바꾸고 시험 6개를 지웠으나 게이트가 보지 못했다).

`--base`부터 HEAD까지 `tests/` 아래 파이썬 파일의 시험 함수를 비교한다.
- 실패(종료 코드 1): 기존 시험 함수가 사라졌다(파일 삭제 포함). 시험을 지워서 통과시키는 것은 허용하지 않는다.
- 실패(종료 코드 1): 기존 시험에 `skip`·`skipif`·`xfail` 표시가 새로 붙었다(표시 변경은 평가 측 소관).
- 경고(종료 코드 0): 기존 시험의 `assert` 개수가 줄었다(약화 의심 — 사람이 본다).
범위의 모든 커밋이 `Agent: evaluator` 꼬리표를 가지면(평가 측이 보호 시험을 고치는 경우) 점검을 건너뛴다.
사용: python scripts/check_test_edits.py --base <기준 커밋>
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

MARKS = ("skip", "skipif", "xfail")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def _show(ref: str, path: str) -> Optional[str]:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, check=False)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def _marks(node: ast.AST) -> set:
    found = set()
    for dec in getattr(node, "decorator_list", []):
        text = ast.unparse(dec)
        for m in MARKS:
            if f"mark.{m}" in text or text.startswith(f"pytest.{m}"):
                found.add(m)
    return found


def collect(source: Optional[str]) -> Dict[str, Tuple[int, set]]:
    """시험 함수 이름 -> (assert 개수, 표시 집합). 클래스 안 시험은 `Class.name`."""
    if source is None:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: Dict[str, Tuple[int, set]] = {}

    def visit(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                asserts = sum(isinstance(n, ast.Assert) for n in ast.walk(node))
                out[prefix + node.name] = (asserts, _marks(node))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + ".")

    visit(tree.body)
    return out


def all_evaluator_commits(base: str) -> bool:
    log = _git("log", f"{base}..HEAD", "--format=%H%x00%B%x01")
    commits = [c for c in log.split("\x01") if c.strip()]
    if not commits:
        return False
    return all("Agent: evaluator" in c for c in commits)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    args = ap.parse_args(argv)

    if all_evaluator_commits(args.base):
        print(f"시험 삭제·약화 점검 — 기준 {args.base}: 범위의 모든 커밋이 `Agent: evaluator`라 건너뜀")
        return 0

    changed = [p for p in _git("diff", "--name-only", args.base, "HEAD", "--", "tests").splitlines()
               if p.endswith(".py")]
    removed: List[str] = []
    newly_marked: List[str] = []
    weakened: List[str] = []
    for path in changed:
        before = collect(_show(args.base, path))
        after = collect(_show("HEAD", path))
        for name, (asserts, marks) in before.items():
            if name not in after:
                removed.append(f"{path}::{name}")
                continue
            a_asserts, a_marks = after[name]
            if a_marks - marks:
                newly_marked.append(f"{path}::{name} (+{', '.join(sorted(a_marks - marks))})")
            if a_asserts < asserts:
                weakened.append(f"{path}::{name} (assert {asserts} → {a_asserts})")

    print(f"시험 삭제·약화 점검 — 기준 {args.base}, 변경된 시험 파일 {len(changed)}개")
    for title, items in (("삭제된 시험", removed), ("새로 skip·xfail이 붙은 시험", newly_marked)):
        if items:
            print(f"  [실패] {title} {len(items)}개")
            for it in items:
                print(f"    - {it}")
    if weakened:
        print(f"  [경고] assert가 줄어든 시험 {len(weakened)}개(약화 의심, 사람이 확인)")
        for it in weakened:
            print(f"    - {it}")
    if removed or newly_marked:
        print("기존 시험을 지우거나 표시를 바꾸려면 먼저 docs/handoff/requests/로 사유를 올리고 평가 측 승인을 받는다.")
        return 1
    print("  기존 시험의 삭제·표시 변경 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
