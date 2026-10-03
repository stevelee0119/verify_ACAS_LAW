"""정규식 리터럴의 입력 길이별 소요 시간을 재어 지수·다항 증가를 구분한다(평가 에이전트 점검 도구, 읽기 전용).

목적: CodeQL "Inefficient regular expression"(지수 ReDoS) 경고의 후보를 코드에서 직접 찾고,
다항(주로 이차) 증가 정규식을 별도로 센다. 제품 코드를 고치지 않는다.

방법: `packages/ apps/ workers/ scripts/`의 `re.*(상수 문자열, ...)` 호출에서 패턴을 뽑아, 정해진 반복 입력 묶음으로 시간을 잰다.
- 지수 의심: 길이 16→24에서 시간이 20배 넘게 늘고 24자에서 0.2초 이상.
- 다항 증가: 길이 4000→8000에서 8000자 시간이 0.5초 이상.
한계: 입력 묶음은 유한하다(숫자·공백·한글·영문·구분자 반복). 묶음에 없는 병적 입력은 놓칠 수 있으므로
"지수 증가 없음"은 이 묶음에 대한 결과일 뿐 정규식 안전의 증명이 아니다. 호출 경로의 입력 정규화·길이 제한은 재지 않는다.

사용: python scripts/probe_regex_complexity.py            (몇 분 걸린다)
"""
from __future__ import annotations

import ast
import re
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("packages", "apps", "workers", "scripts")
RE_FUNCS = {"compile", "match", "search", "fullmatch", "sub", "findall", "finditer", "split"}
FAMILIES = [
    lambda n: "a" * n + "!", lambda n: "1" * n + "x", lambda n: "가" * n + "x", lambda n: "A" * n + "!",
    lambda n: "A-" * n + "!", lambda n: " " * n + "x", lambda n: "1 " * n + "x", lambda n: "1," * n + "x",
    lambda n: "가 " * n + "x", lambda n: "a-" * n + "!", lambda n: "1." * n + "x", lambda n: "제1조" * n + "x",
    lambda n: "갑 제1호증" * n + "x",
]


class _Timeout(Exception):
    pass


def _on_alarm(_signum, _frame):
    raise _Timeout()


def _flags(node: ast.Call) -> int:
    flags = 0
    exprs = [kw.value for kw in node.keywords if kw.arg == "flags"]
    if node.func.attr == "compile" and len(node.args) > 1:
        exprs.append(node.args[1])
    for expr in exprs:
        try:
            flags = eval(compile(ast.Expression(expr), "flags", "eval"), {"re": re})  # noqa: S307 — re.* 상수만
        except Exception:
            pass
    return flags


def literals() -> list[tuple[str, int, str, int]]:
    found = []
    for directory in SCAN_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in RE_FUNCS
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    found.append((str(path.relative_to(ROOT)), node.lineno, node.args[0].value, _flags(node)))
    return found


def timed(rx: re.Pattern, text: str, limit: float) -> float:
    signal.setitimer(signal.ITIMER_REAL, limit)
    start = time.perf_counter()
    try:
        rx.search(text)
        return time.perf_counter() - start
    except _Timeout:
        return limit
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    signal.signal(signal.SIGALRM, _on_alarm)
    patterns = literals()
    exponential, polynomial = [], []
    for path, line, pattern, flags in patterns:
        try:
            rx = re.compile(pattern, flags)
        except re.error:
            continue
        hit = None
        for index, family in enumerate(FAMILIES):
            small, large = timed(rx, family(16), 1.0), timed(rx, family(24), 1.0)
            if large >= 0.2 and large > 20 * max(small, 1e-4):
                hit = (index, small, large)
                break
        if hit:
            exponential.append((path, line, pattern, hit))
            continue
        for index, family in enumerate(FAMILIES):
            half, full = timed(rx, family(4000), 3.0), timed(rx, family(8000), 3.0)
            if full >= 0.5:
                polynomial.append((path, line, pattern, (index, half, full)))
                break
    print(f"정규식 리터럴 {len(patterns)}개 점검(입력 묶음 {len(FAMILIES)}종)")
    print(f"지수 증가 의심: {len(exponential)}건")
    for path, line, pattern, (index, small, large) in exponential:
        print(f"  {path}:{line} 입력묶음={index} n16={small:.4f}s n24={large:.3f}s {pattern[:90]!r}")
    print(f"다항 증가(8000자에서 0.5초 이상): {len(polynomial)}건")
    for path, line, pattern, (index, half, full) in sorted(polynomial, key=lambda row: -row[3][2]):
        print(f"  {path}:{line} 입력묶음={index} n4000={half:.3f}s n8000={full:.3f}s {pattern[:90]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
