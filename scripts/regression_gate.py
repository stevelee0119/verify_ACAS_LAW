"""회귀 게이트(평가 에이전트 소관, 보호 경로). 기준 커밋 대비 '전에 되던 것이 지금 안 되는' 항목을 찾는다.

고정 시험 점수(scorecard)는 합계만 보고, 서면 한 건의 점수는 새 서면에서 올라도 기존 항목이 조용히 떨어지는 것을 가리지 못한다.
이 도구는 같은 문서·같은 명세를 **기준 커밋의 코드**와 **현재 코드**로 각각 돌려 항목 단위로 비교한다(합계가 올라도 항목 하나가 떨어지면 실패).

    python scripts/regression_gate.py --base HEAD~1                 # 직전 커밋 대비 (푸시 전에 항상)
    python scripts/regression_gate.py --base origin/main --pytest   # 전체 시험의 '새로 실패하는 시험'까지 비교(느림, 평가·푸시 직전)
    python scripts/regression_gate.py --base de243cc --json

대상: tests/fixtures/probes/*.json 중 온라인 명세를 뺀 모든 명세 × 입력 방식(PDF·docx 원본, 원문 텍스트).
- 회귀(REGRESSION): 기준에서 통과, 현재 실패 → 종료 코드 1
- 개선(IMPROVED): 기준에서 실패, 현재 통과 (참고)
--pytest: `pytest -q --ignore=tests/acceptance`를 두 코드에서 돌려 현재에만 있는 실패를 센다(시험이 새로 생겨 실패하는 것도 센다).
종료 코드: 0 회귀 없음 · 1 회귀 또는 새 시험 실패 · 2 **측정하지 못함**(처리 오류·빈 결과·누락된 입력·시간 초과·시험 수집 0건). 2는 통과가 아니다.
양쪽이 같은 오류를 내거나 시험이 하나도 돌지 않아도 '회귀 없음'으로 보이는 것을 막기 위해(독립 감사 Astra 4차의 지적) 측정 못 한 것은 항상 실패로 센다.
측정 조건은 오프라인(LV_ALLOW_NETWORK=0)이다. AI 작성 판별·공식 DB 대조·Drive 대조는 재지 못한다.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "probe_document.py"
SPECS = ROOT / "tests" / "fixtures" / "probes"


def diff_rows(base: Dict[str, bool], head: Dict[str, bool]) -> Tuple[List[str], List[str]]:
    """({기준 통과→현재 실패}, {기준 실패→현재 통과}). 기준에 없는 항목(새 항목)은 비교하지 않는다."""
    regressions = sorted(k for k, v in base.items() if v and not head.get(k, False))
    improved = sorted(k for k, v in base.items() if not v and head.get(k, False))
    return regressions, improved


def failed_tests(output: str) -> Set[str]:
    """`pytest -rf` 출력에서 실패한 시험 id 집합."""
    return {m.group(1).strip() for m in re.finditer(r"^FAILED\s+(\S+)", output, flags=re.M)}


def pytest_counts(output: str) -> Dict[str, int]:
    """`pytest -q` 마지막 요약 줄에서 {passed, failed, error, skipped, xfailed, xpassed}를 읽는다. 읽지 못하면 빈 딕셔너리."""
    counts: Dict[str, int] = {}
    for line in reversed(output.strip().splitlines()):
        found = re.findall(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)", line)
        if found:
            for number, key in found:
                counts["error" if key.startswith("error") else key] = int(number)
            return counts
    return counts


def worktree(ref: str) -> Path:
    tree = Path(tempfile.mkdtemp(prefix="regress_tree_"))
    shutil.rmtree(tree)
    subprocess.run(["git", "worktree", "add", "--detach", "-q", str(tree), ref], cwd=ROOT, check=True)
    return tree


def remove_worktree(tree: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)


def probe_run(spec: Path, text: bool, tree: Optional[Path]) -> Tuple[Dict[str, bool], List[str]]:
    """({항목 id: 통과 여부}, 처리 오류 목록). 하위 프로세스 실패·시간 초과는 예외로 올린다."""
    cmd = [sys.executable, str(PROBE), "run", "--spec", str(spec), "--json"] + (["--text"] if text else [])
    env = dict(os.environ, LV_ALLOW_NETWORK="0")
    cwd = ROOT
    if tree is not None:
        cmd += ["--tree", str(tree)]
        cwd = tree
        env.update(PYTHONPATH=str(tree), PROBE_DOC_ROOT=str(ROOT))
    label = f"{spec.name} {'text' if text else 'primary'}"
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label}: 시간 초과({exc.timeout}s)") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"{label}: {proc.stderr[-300:]}")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    rows = {r["id"]: bool(r["passed"]) for r in payload["rows"]}
    return rows, [str(e) for e in payload.get("errors", [])]


def unmeasured(label: str, base: Tuple[Dict[str, bool], List[str]], head: Tuple[Dict[str, bool], List[str]]) -> List[str]:
    """측정하지 못한 사유. 빈 결과나 처리 오류가 있으면 '회귀 없음'으로 볼 수 없다."""
    reasons = []
    for side, (rows, errors) in (("기준", base), ("현재", head)):
        if not rows:
            reasons.append(f"{label} {side}: 항목 결과가 비어 있다")
        for error in errors:
            reasons.append(f"{label} {side}: 처리 오류 {error}")
    return reasons


def jobs() -> Tuple[List[Tuple[Path, bool]], List[str]]:
    """(측정할 (명세, 텍스트 입력 여부) 목록, 입력 파일이 없어 측정하지 못한 항목 목록)."""
    out: List[Tuple[Path, bool]] = []
    missing: List[str] = []
    for spec in sorted(SPECS.glob("*.json")):
        if spec.stem.endswith("_online"):
            continue
        data = json.loads(spec.read_text(encoding="utf-8"))
        if "checks" not in data:
            continue
        for text in (False, True):
            key = "text_input" if text else "input"
            source = data.get(key)
            if not source:
                continue
            if (ROOT / source).is_file():
                out.append((spec, text))
            else:
                missing.append(f"{spec.stem}/{'text' if text else 'primary'}: 입력 파일 없음 {source}")
    return out, missing


def run_pytest(tree: Path) -> Tuple[Set[str], Dict[str, int], int]:
    """(실패한 시험 id 집합, 요약 개수, 종료 코드). 시간 초과는 예외로 올린다."""
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--ignore=tests/acceptance", "-p", "no:cacheprovider",
                               "--tb=no", "-rf"], cwd=tree, capture_output=True, text=True, timeout=3000,
                              env=dict(os.environ, LV_ALLOW_NETWORK="0", PYTHONPATH=str(tree)))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pytest 시간 초과({exc.timeout}s)") from exc
    return failed_tests(proc.stdout), pytest_counts(proc.stdout), proc.returncode


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="비교 기준 커밋(예: HEAD~1, origin/main, 커밋 해시)")
    parser.add_argument("--pytest", action="store_true", help="전체 시험의 새 실패까지 비교(느림)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        base_ref = subprocess.run(["git", "rev-parse", "--short", args.base], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        base_tree = worktree(args.base)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"기준 커밋을 열 수 없다: {exc}", file=sys.stderr)
        return 2
    head_ref = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "packages", "apps", "workers", "config"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    report: Dict[str, object] = {"base": base_ref, "head": head_ref + ("+미커밋" if dirty else ""), "specs": [],
                                 "regressions": [], "improved": [], "new_test_failures": [], "unmeasured": []}
    unmeasured_reasons: List[str] = report["unmeasured"]  # type: ignore[assignment]
    try:
        work, missing = jobs()
        unmeasured_reasons += missing
        if not work:
            unmeasured_reasons.append("측정할 명세·입력이 하나도 없다")
        with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            base_futures = {j: pool.submit(probe_run, j[0], j[1], base_tree) for j in work}
            head_futures = {j: pool.submit(probe_run, j[0], j[1], None) for j in work}
            pytest_futures = ({"base": pool.submit(run_pytest, base_tree), "head": pool.submit(run_pytest, ROOT)}
                              if args.pytest else {})
            for j in work:
                spec, text = j
                label = f"{spec.stem}/{'text' if text else 'primary'}"
                try:
                    base_result, head_result = base_futures[j].result(), head_futures[j].result()
                except (RuntimeError, ValueError, KeyError, OSError) as exc:
                    unmeasured_reasons.append(f"{label}: 측정 실패 {exc}")
                    continue
                unmeasured_reasons += unmeasured(label, base_result, head_result)
                base_rows, head_rows = base_result[0], head_result[0]
                regressions, improved = diff_rows(base_rows, head_rows)
                report["specs"].append({"spec": label, "base": f"{sum(base_rows.values())}/{len(base_rows)}",
                                        "head": f"{sum(head_rows.values())}/{len(head_rows)}"})
                report["regressions"] += [f"{label}:{i}" for i in regressions]
                report["improved"] += [f"{label}:{i}" for i in improved]
            if args.pytest:
                try:
                    (base_failed, base_counts, base_rc), (head_failed, head_counts, head_rc) = (
                        pytest_futures["base"].result(), pytest_futures["head"].result())
                except RuntimeError as exc:
                    unmeasured_reasons.append(str(exc))
                else:
                    for side, counts, rc in (("기준", base_counts, base_rc), ("현재", head_counts, head_rc)):
                        if rc not in (0, 1) or not counts.get("passed"):
                            unmeasured_reasons.append(f"pytest {side}: 종료 코드 {rc}, 통과 {counts.get('passed', 0)}건 — 시험이 제대로 돌지 않았다")
                    report["pytest"] = {"base": base_counts, "head": head_counts}
                    report["new_test_failures"] = sorted(head_failed - base_failed)
                    report["fixed_test_failures"] = sorted(base_failed - head_failed)
    finally:
        remove_worktree(base_tree)
    bad = bool(report["regressions"] or report["new_test_failures"])
    code = 1 if bad else (2 if unmeasured_reasons else 0)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return code
    print(f"회귀 게이트 — 기준 {report['base']} → 현재 {report['head']} (오프라인)")
    for row in report["specs"]:
        print(f"  {row['spec']:<45} {row['base']:>7} → {row['head']:<7}")
    for item in report["regressions"]:
        print(f"  [회귀] {item}")
    for item in report["improved"]:
        print(f"  [개선] {item}")
    if args.pytest:
        for item in report["new_test_failures"]:
            print(f"  [새 시험 실패] {item}")
        if "pytest" in report:
            print(f"  pytest 기준 {report['pytest']['base']} → 현재 {report['pytest']['head']}")
        print(f"  (기준에서 실패하던 시험 중 해결: {len(report.get('fixed_test_failures', []))}건)")
    for reason in unmeasured_reasons:
        print(f"  [측정 못 함] {reason}")
    print("회귀 있음" if bad else ("측정하지 못한 항목이 있다 — 회귀 없음으로 볼 수 없다" if unmeasured_reasons else "회귀 없음"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
