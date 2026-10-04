"""구현 측 보고 전 단일 점검 — 수용·원장·성적표·회귀 게이트·하드코딩·시험 삭제·버전·전체 시험을 한 번에 돌린다.

배경(process_review_2026-10-03 6절 B-1): 구현 보고서의 수치가 측정과 자주 달랐다(미커밋 트리로 돌린 회귀 게이트,
환경 차이, 표 합계 오기). 이 도구의 요약을 보고서에 그대로 붙이고, 평가 측은 같은 명령으로 다시 잰다.

사용: python scripts/verify_all.py --base <기준 커밋> [--quick] [--skip-ui] [--allow-env-mismatch] [--out artifacts/verify_all.json]
- --quick: 전체 시험·브라우저 시험을 건너뛴다. 2026-10-04부터 구현 측의 표준 점검이다(전체 시험·브라우저 시험은 같은 SHA의 CI가 돈다).
  전체 모드는 평가 측이 수용 판정 SHA에서 한 번 돈다(사용자 승인 '검증 실행 중복 줄이기', docs/AGENT_ROLES.md 2.1).
- CI 환경(Python 3.11·tesseract 5.3.4)과 다르면 'environment' 단계가 실패한다. --allow-env-mismatch는 그 단계를 경고로 낮추되 보고서에 그 사실을 적어야 한다.
- 종료 코드: 0 = 모든 단계 통과, 1 = 실패 단계 있음, 2 = 측정 못 함(커밋·추적되지 않은 변경, 잘못된 기준 커밋).
시험 결과는 junit XML이 아니라 이 도구가 붙이는 pytest 플러그인이 쓰는 JSON 줄로 집계한다(외부 XML 파서 불필요).
수용 시험의 strict XPASS(해결되어 평가 측 승격을 기다리는 표시)는 실패로 세지 않고 따로 적는다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional

UI_PATTERNS = ("tests/test_frontend_*.py", "tests/test_analysis_completion.py",
               "tests/test_reasoning_layout.py", "tests/test_drive_rag_relevance.py")
CI_ENV = {"python": "3.11", "tesseract": "5.3.4"}


def _run(cmd: List[str], timeout: int, extra_env: Optional[Dict[str, str]] = None) -> Dict:
    """인자 목록으로만 실행한다(shell 미사용). 명령은 이 파일 안에서 정한 것이고 외부 입력은 검증된 --base뿐이다."""
    t0 = time.time()
    try:
        # 감사 완료: 인자 목록·shell=False, 명령은 이 파일에서 정하고 외부 입력(--base)은 BASE_RE로 검증한다
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False,  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                           env={**os.environ, "LV_ALLOW_NETWORK": "0", **(extra_env or {})})
        out = (r.stdout or "") + (r.stderr or "")
        code = r.returncode
    except subprocess.TimeoutExpired:
        out, code = "시간 초과", 124
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return {"cmd": " ".join(cmd), "code": code, "tail": lines[-3:], "seconds": round(time.time() - t0, 1)}


BASE_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._/-]{0,199}")

_PLUGIN = """
import json, os
_OUT = os.environ["VERIFY_ALL_RESULTS"]


def _write(rec):
    with open(_OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\\n")


def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        longrepr = str(report.longrepr) if report.failed else ""
        _write({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                "strict_xpass": report.failed and "XPASS(strict)" in longrepr})


def pytest_collectreport(report):
    if report.failed:
        _write({"nodeid": report.nodeid or "<collection>", "when": "collect", "outcome": "failed", "strict_xpass": False})
"""


def classify_results(path: str) -> Dict:
    """플러그인이 쓴 JSON 줄에서 통과·실제 실패·strict XPASS를 나눈다."""
    real: List[str] = []
    strict_xpass = 0
    passed = 0
    try:
        with open(path, encoding="utf-8") as f:
            recs = [json.loads(ln) for ln in f if ln.strip()]
    except (OSError, ValueError):
        return {"error": "시험 결과를 읽지 못함"}
    if not recs:
        return {"error": "수집된 시험이 없음"}
    for r in recs:
        if r.get("outcome") == "failed":
            if r.get("strict_xpass"):
                strict_xpass += 1
            else:
                real.append(f"{r.get('nodeid')} ({r.get('when')})")
        elif r.get("outcome") == "passed" and r.get("when") == "call":
            passed += 1
    return {"passed": passed, "real_failures": real, "strict_xpass": strict_xpass}


def _pytest(args: List[str], timeout: int) -> Dict:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "verify_all_plugin.py"), "w", encoding="utf-8") as f:
            f.write(_PLUGIN)
        results = os.path.join(d, "results.jsonl")
        extra_env = {"VERIFY_ALL_RESULTS": results,
                     "PYTHONPATH": d + os.pathsep + os.environ.get("PYTHONPATH", "")}
        res = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "verify_all_plugin",
                    "--tb=no", *args], timeout, extra_env)
        res.update(classify_results(results))
    # pytest 종료 코드 0(통과)·1(실패 있음)만 정상 실행으로 본다. 2~5는 중단·내부 오류·사용 오류·수집 0건
    res["ok"] = "error" not in res and not res.get("real_failures") and res["code"] in (0, 1)
    return res


def _env() -> Dict:
    tver = None
    if shutil.which("tesseract"):
        r = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, shell=False)
        first = ((r.stdout or r.stderr).splitlines() or [""])[0]
        tver = first.split()[-1] if first else None
    env = {"python": platform.python_version(), "os": platform.platform(), "tesseract": tver}
    env["matches_ci"] = env["python"].startswith(CI_ENV["python"]) and (tver or "").startswith(CI_ENV["tesseract"])
    return env


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="비교 기준 커밋(라운드 시작 SHA)")
    ap.add_argument("--quick", action="store_true", help="전체 시험·브라우저 시험 건너뜀(보고서용 아님)")
    ap.add_argument("--skip-ui", action="store_true", help="브라우저 시험만 건너뜀")
    ap.add_argument("--allow-env-mismatch", action="store_true", help="CI 환경 불일치를 경고로 낮춤(보고서에 적을 것)")
    ap.add_argument("--out", default="artifacts/verify_all.json")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args(argv)

    if not BASE_RE.fullmatch(a.base):
        print(json.dumps({"error": f"기준 커밋 표기가 올바르지 않음: {a.base!r}"}, ensure_ascii=False))
        return 2
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, shell=False).stdout.strip()
    # 추적되지 않은 파일도 측정 대상 코드·시험에 영향을 줄 수 있으므로 거부한다(.gitignore 대상은 제외)
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, shell=False).stdout.strip()
    base_ok = subprocess.run(["git", "cat-file", "-e", f"{a.base}^{{commit}}"], capture_output=True, shell=False).returncode == 0
    summary: Dict = {"head": head, "base": a.base, "env": _env(), "steps": {}}
    if dirty or not base_ok:
        summary["error"] = "커밋하지 않았거나 추적되지 않은 변경이 있다" if dirty else f"기준 커밋 {a.base}을 찾지 못함"
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 2

    s = summary["steps"]
    env_ok = summary["env"]["matches_ci"]
    s["environment"] = {"ok": env_ok or a.allow_env_mismatch, "matches_ci": env_ok,
                        "tail": [f"python {summary['env']['python']}, tesseract {summary['env']['tesseract']}"
                                 + ("" if env_ok else " — CI와 다름" + (" (--allow-env-mismatch)" if a.allow_env_mismatch else ""))]}
    s["acceptance"] = _pytest(["tests/acceptance"], a.timeout)
    s["regression_ledger"] = _pytest(["tests/regression"], a.timeout)
    card = os.path.join("artifacts", "scorecard.json")
    sc = _run([sys.executable, "scripts/scorecard.py", "--out", card], a.timeout)
    gate_cmd = [sys.executable, "scripts/score_gate.py", "--current", card] + ([] if a.allow_env_mismatch else ["--strict-env"])
    gate = _run(gate_cmd, a.timeout)
    s["score_gate"] = {**gate, "scorecard_tail": sc["tail"], "ok": sc["code"] == 0 and gate["code"] == 0}
    # 회귀 게이트는 방금 만든 현재 성적표를 다시 쓴다(같은 코드를 두 번 채점하지 않는다, 2026-10-04)
    reuse = ["--head-scorecard", card] if sc["code"] == 0 else []
    for name, script in (("regression_gate", "regression_gate.py"), ("hardcoding_diff", "check_hardcoding_diff.py"),
                         ("test_edits", "check_test_edits.py"), ("protected_paths", "check_protected_paths.py"),
                         ("version_policy", "check_version_policy.py")):
        r = _run([sys.executable, f"scripts/{script}", "--base", a.base] + (reuse if name == "regression_gate" else []), a.timeout)
        r["ok"] = r["code"] == 0
        s[name] = r
    if not a.quick:
        ui_files = sorted({f for p in UI_PATTERNS for f in glob.glob(p)})
        ignore = ["--ignore=tests/acceptance"] + [f"--ignore={f}" for f in ui_files]
        s["full_tests"] = _pytest(ignore, a.timeout)
        if not a.skip_ui and ui_files:
            s["browser_tests"] = _pytest(ui_files, a.timeout)

    failed = [k for k, v in s.items() if not v.get("ok")]
    summary["failed_steps"] = failed
    summary["mode"] = "quick" if a.quick else ("skip-ui" if a.skip_ui else "full")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    env = summary["env"]
    print(f"verify_all — HEAD {head}, 기준 {a.base}, 모드 {summary['mode']}")
    print(f"  환경: python {env['python']}, tesseract {env['tesseract']}, {env['os']}"
          + ("" if env["matches_ci"] else f"  [주의] CI 환경(python {CI_ENV['python']}, tesseract {CI_ENV['tesseract']})과 다름"))
    for k, v in s.items():
        extra = ""
        if "real_failures" in v:
            extra = f" 통과 {v.get('passed')}, 실제 실패 {len(v['real_failures'])}, strict XPASS {v.get('strict_xpass')}"
            for t in v["real_failures"][:20]:
                extra += f"\n      - {t}"
        elif v.get("tail"):
            extra = " " + v["tail"][-1][:120]
        print(f"  [{'통과' if v.get('ok') else '실패'}] {k}:{extra}")
    print(f"요약 저장: {a.out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
