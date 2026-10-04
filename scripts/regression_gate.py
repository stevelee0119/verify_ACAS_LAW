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

기준 쪽 캐시(2026-10-04 사용자 승인 '검증 실행 중복 줄이기'): 기준 커밋은 라운드 내내 고정인데 매번 다시 채점했다.
기준 쪽 probe·성적표 결과를 `artifacts/regression_cache/`에 저장하고, 키가 같으면 다시 쓴다.
키 = 기준 커밋 전체 SHA + 측정 도구(현재 `scripts/*.py`) 해시 + 환경(Python·tesseract·설치 패키지 판) + 명세·입력 파일 내용 해시.
처리 오류가 있거나 빈 결과는 저장하지 않는다. 이 폴더는 저장소에 올리지 않는 로컬 캐시이며(CI는 매번 새로 잰다) `--no-cache`로 끈다.
`--head-scorecard <파일>`: 같은 실행에서 이미 만든 현재 코드의 성적표를 다시 쓴다(verify_all·CI 점수 게이트가 먼저 만든다).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import importlib.metadata
import json
import os
import platform
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
CACHE_DIR = ROOT / "artifacts" / "regression_cache"


def diff_rows(base: Dict[str, bool], head: Dict[str, bool]) -> Tuple[List[str], List[str]]:
    """({기준 통과→현재 실패}, {기준 실패→현재 통과}). 기준에 없는 항목(새 항목)은 비교하지 않는다."""
    regressions = sorted(k for k, v in base.items() if v and not head.get(k, False))
    improved = sorted(k for k, v in base.items() if not v and head.get(k, False))
    return regressions, improved


def failed_tests(output: str) -> Set[str]:
    """`pytest -rf` 출력에서 실패한 시험 id 집합."""
    return {m.group(1).strip() for m in re.finditer(r"^FAILED\s+(\S+)", output, flags=re.M)}


def errored_tests(output: str) -> Set[str]:
    """`pytest -rE` 출력에서 ERROR(수집·setup·teardown 오류)가 난 시험·파일 id 집합."""
    return {m.group(1).strip() for m in re.finditer(r"^ERROR\s+(\S+)", output, flags=re.M)}


def pytest_findings(base: Tuple[Set[str], Set[str], Dict[str, int], int],
                    head: Tuple[Set[str], Set[str], Dict[str, int], int]) -> Tuple[List[str], List[str]]:
    """기준·현재의 (실패 집합, ERROR 집합, 요약 개수, 종료 코드)를 비교한다. (새 실패 목록, 측정 못 함 사유 목록).

    FAILED만 보면 'passed가 조금 있고 ERROR가 있는' 실행이 통과로 보인다(독립 감사 5차 F4). ERROR는 통과도 실패 판정도 아니므로
    양쪽 모두에서 측정 못 함으로 두고, 현재에만 있는 ERROR는 새 실패로 센다."""
    reasons: List[str] = []
    for side, (failed, errored, counts, rc) in (("기준", base), ("현재", head)):
        if rc not in (0, 1) or not counts.get("passed"):
            reasons.append(f"pytest {side}: 종료 코드 {rc}, 통과 {counts.get('passed', 0)}건 — 시험이 제대로 돌지 않았다")
        if errored or counts.get("error"):
            reasons.append(f"pytest {side}: ERROR {max(len(errored), counts.get('error', 0))}건 — ERROR는 통과가 아니다"
                           f"(수집·준비 단계 오류, 예: {sorted(errored)[:3]})")
        if rc == 1 and not failed and not errored:
            reasons.append(f"pytest {side}: 종료 코드 1인데 실패·ERROR 시험을 읽지 못했다(출력 형식 또는 요약 파싱 문제)")
        if counts.get("failed", 0) > len(failed):
            reasons.append(f"pytest {side}: 요약의 실패 {counts['failed']}건 중 {len(failed)}건만 읽었다")
    new_failures = sorted((head[0] - base[0]) | {f"ERROR {e}" for e in head[1] - base[1]})
    base_passed, head_passed = base[2].get("passed", 0), head[2].get("passed", 0)
    if head_passed < base_passed and not new_failures:
        reasons.append(f"pytest 통과 건수 감소(기준 {base_passed} → 현재 {head_passed}) — 시험이 삭제됐거나 실행되지 않았다")
    return new_failures, reasons


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


def _digest(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def tool_fingerprint() -> str:
    """현재 측정 도구의 해시. 기준 쪽 probe도 현재 `probe_document.py`로 채점하므로 도구가 바뀌면 캐시를 쓰지 않는다."""
    return _digest(*[f"{p.name}:{hashlib.sha256(p.read_bytes()).hexdigest()}" for p in sorted((ROOT / "scripts").glob("*.py"))])


def env_fingerprint() -> str:
    try:
        tess = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, shell=False).stdout.splitlines()[:1]
    except OSError:
        tess = ["none"]
    packages = sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions() if d.metadata["Name"])
    return _digest(sys.version, platform.system(), *tess, *packages)


def job_input(spec: Path, text: bool) -> Optional[Path]:
    data = json.loads(spec.read_text(encoding="utf-8"))
    source = data.get("text_input" if text else "input")
    return ROOT / source if source else None


def probe_cache_key(base_sha: str, spec: Path, text: bool, tool: str, env: str) -> str:
    source = job_input(spec, text)
    data = source.read_bytes() if source and source.is_file() else b""
    return _digest("probe", base_sha, tool, env, spec.name, spec.read_bytes(), text, hashlib.sha256(data).hexdigest())


def cache_get(key: str) -> Optional[object]:
    path = CACHE_DIR / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["result"]
    except (OSError, ValueError, KeyError):
        return None


def cache_put(key: str, result: object, label: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(json.dumps({"label": label, "result": result}, ensure_ascii=False),
                                              encoding="utf-8")
    except OSError:
        pass


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


def scorecard_run(tree: Path) -> Dict[str, Dict[str, float]]:
    """그 코드 트리의 고정 시험 성적표에서 {집합: {문서: 재현율}}을 읽는다(독립 감사 5차: probe는 TC-06 법원명 손실을 못 봤다)."""
    out = Path(tempfile.mkdtemp(prefix="gate_score_")) / "scorecard.json"
    script = tree / "scripts" / "scorecard.py"
    if not script.is_file():
        raise RuntimeError("성적표 도구가 이 커밋에 없다")
    try:
        proc = subprocess.run([sys.executable, str(script), "--out", str(out)], cwd=tree, capture_output=True, text=True,
                              timeout=900, env=dict(os.environ, LV_ALLOW_NETWORK="0", PYTHONPATH=str(tree)))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"성적표 시간 초과({exc.timeout}s)") from exc
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"성적표 실행 실패(종료 코드 {proc.returncode}) {proc.stderr[-200:]}")
    return scorecard_load(out)


def scorecard_load(path: Path) -> Dict[str, Dict[str, float]]:
    """성적표 파일에서 {집합: {문서: 재현율}}을 읽는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # 값이 없는(채점하지 않은) 문서는 비교 대상에서 뺀다. 기준에 값이 있던 문서가 현재에 없으면 scorecard_diff가 측정 못 함으로 센다.
    return {name: {str(k): float(v) for k, v in (st.get("per_document") or {}).items() if v is not None}
            for name, st in data.get("sets", {}).items()}


def scorecard_diff(base: Dict[str, Dict[str, float]], head: Dict[str, Dict[str, float]]) -> Tuple[List[str], List[str]]:
    """문서별 재현율이 내려갔으면 회귀. 기준 문서·집합이 현재에 없거나 비어 있으면 측정 못 함."""
    regressions: List[str] = []
    reasons: List[str] = []
    if not base or not any(base.values()):
        reasons.append("성적표(기준)에 문서별 값이 없다")
    for name, docs in base.items():
        for doc, value in docs.items():
            now = head.get(name, {}).get(doc)
            if now is None:
                reasons.append(f"성적표 {name}/{doc}: 현재에 없다(문서·집합 누락)")
            elif now < value - 1e-9:
                regressions.append(f"성적표 {name}/{doc}: {value} → {now}")
    return regressions, reasons


def run_pytest(tree: Path) -> Tuple[Set[str], Set[str], Dict[str, int], int]:
    """(실패한 시험 id 집합, ERROR id 집합, 요약 개수, 종료 코드). 시간 초과는 예외로 올린다.

    저장소 `pytest.ini`의 `addopts = -q`와 여기의 `-q`가 겹치면 `-qq`가 되어 마지막 요약 줄이 나오지 않아 개수를 읽지 못한다(평가 측 점검에서 발견).
    그래서 `-o addopts=`로 비우고 `-q` 한 번만 준다."""
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--ignore=tests/acceptance", "-p", "no:cacheprovider",
                               "--tb=no", "-rfE", "-o", "addopts="], cwd=tree, capture_output=True, text=True, timeout=3000,
                              env=dict(os.environ, LV_ALLOW_NETWORK="0", PYTHONPATH=str(tree)))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pytest 시간 초과({exc.timeout}s)") from exc
    return failed_tests(proc.stdout), errored_tests(proc.stdout), pytest_counts(proc.stdout), proc.returncode


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="비교 기준 커밋(예: HEAD~1, origin/main, 커밋 해시)")
    parser.add_argument("--pytest", action="store_true", help="전체 시험의 새 실패까지 비교(느림)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="기준 쪽 캐시를 쓰지도 저장하지도 않는다")
    parser.add_argument("--head-scorecard", help="이미 만든 현재 코드의 성적표 파일(같은 실행에서 만든 것만)")
    args = parser.parse_args(argv)
    try:
        base_ref = subprocess.run(["git", "rev-parse", "--short", args.base], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        base_sha = subprocess.run(["git", "rev-parse", f"{args.base}^{{commit}}"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"기준 커밋을 열 수 없다: {exc}", file=sys.stderr)
        return 2
    head_ref = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "packages", "apps", "workers", "config"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    report: Dict[str, object] = {"base": base_ref, "head": head_ref + ("+미커밋" if dirty else ""), "specs": [],
                                 "regressions": [], "improved": [], "new_test_failures": [], "unmeasured": []}
    unmeasured_reasons: List[str] = report["unmeasured"]  # type: ignore[assignment]
    work, missing = jobs()
    unmeasured_reasons += missing
    if not work:
        unmeasured_reasons.append("측정할 명세·입력이 하나도 없다")
    use_cache = not args.no_cache
    tool, env = (tool_fingerprint(), env_fingerprint()) if use_cache else ("", "")
    probe_keys = {j: probe_cache_key(base_sha, j[0], j[1], tool, env) for j in work} if use_cache else {}
    score_key = _digest("scorecard", base_sha, env) if use_cache else ""
    cached = {j: cache_get(k) for j, k in probe_keys.items()}
    cached_score = cache_get(score_key) if use_cache else None
    hits = sum(v is not None for v in cached.values()) + (cached_score is not None)
    report["base_cache_hits"] = f"{hits}/{len(work) + 1}" if use_cache else "꺼짐"
    need_tree = args.pytest or not use_cache or cached_score is None or any(v is None for v in cached.values())
    try:
        base_tree = worktree(args.base) if need_tree else None
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"기준 커밋을 열 수 없다: {exc}", file=sys.stderr)
        return 2

    def base_probe(job: Tuple[Path, bool]) -> Tuple[Dict[str, bool], List[str]]:
        hit = cached.get(job)
        if hit is not None:
            return {str(k): bool(v) for k, v in hit["rows"].items()}, list(hit["errors"])
        rows, errors = probe_run(job[0], job[1], base_tree)
        if use_cache and rows and not errors:
            cache_put(probe_keys[job], {"rows": rows, "errors": errors}, f"{base_ref} {job[0].name} {'text' if job[1] else 'primary'}")
        return rows, errors

    def base_scorecard() -> Dict[str, Dict[str, float]]:
        if cached_score is not None:
            return cached_score  # type: ignore[return-value]
        result = scorecard_run(base_tree)  # type: ignore[arg-type]
        if use_cache and result and any(result.values()):
            cache_put(score_key, result, f"{base_ref} scorecard")
        return result

    def head_scorecard() -> Dict[str, Dict[str, float]]:
        return scorecard_load(Path(args.head_scorecard)) if args.head_scorecard else scorecard_run(ROOT)

    try:
        with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            base_futures = {j: pool.submit(base_probe, j) for j in work}
            head_futures = {j: pool.submit(probe_run, j[0], j[1], None) for j in work}
            pytest_futures = ({"base": pool.submit(run_pytest, base_tree), "head": pool.submit(run_pytest, ROOT)}
                              if args.pytest else {})
            score_futures = {"base": pool.submit(base_scorecard), "head": pool.submit(head_scorecard)}
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
            try:
                score_regressions, score_reasons = scorecard_diff(score_futures["base"].result(), score_futures["head"].result())
            except (RuntimeError, ValueError, KeyError, OSError, TypeError) as exc:
                unmeasured_reasons.append(f"성적표 비교 못 함: {exc}")
            else:
                report["regressions"] += score_regressions
                unmeasured_reasons += score_reasons
            if args.pytest:
                try:
                    base_run, head_run = pytest_futures["base"].result(), pytest_futures["head"].result()
                except RuntimeError as exc:
                    unmeasured_reasons.append(str(exc))
                else:
                    new_failures, reasons = pytest_findings(base_run, head_run)
                    unmeasured_reasons += reasons
                    report["pytest"] = {"base": base_run[2], "head": head_run[2]}
                    report["new_test_failures"] = new_failures
                    report["fixed_test_failures"] = sorted(base_run[0] - head_run[0])
    finally:
        if base_tree is not None:
            remove_worktree(base_tree)
    bad = bool(report["regressions"] or report["new_test_failures"])
    code = 1 if bad else (2 if unmeasured_reasons else 0)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return code
    print(f"회귀 게이트 — 기준 {report['base']} → 현재 {report['head']} (오프라인, 기준 캐시 {report['base_cache_hits']})")
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
