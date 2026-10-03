"""구현 측 보고 전 단일 점검 — 수용·원장·성적표·회귀 게이트·하드코딩·시험 삭제·버전·전체 시험을 한 번에 돌린다.

배경(process_review_2026-10-03 6절 B-1): 구현 보고서의 수치가 측정과 자주 달랐다(미커밋 트리로 돌린 회귀 게이트,
환경 차이, 표 합계 오기). 이 도구의 요약을 보고서에 그대로 붙이고, 평가 측은 같은 명령으로 다시 잰다.

사용: python scripts/verify_all.py --base <기준 커밋> [--quick] [--skip-ui] [--out artifacts/verify_all.json]
- --quick: 전체 시험·브라우저 시험을 건너뛴다(중간 확인용, 보고서에는 쓰지 않는다).
- 종료 코드: 0 = 모든 단계 통과, 1 = 실패 단계 있음, 2 = 측정 못 함(미커밋 변경, 기준 커밋 없음, 도구 오류).
수용 시험의 strict XPASS(해결되어 평가 측 승격을 기다리는 표시)는 실패로 세지 않고 따로 적는다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

UI_PATTERNS = ("tests/test_frontend_*.py", "tests/test_analysis_completion.py",
               "tests/test_reasoning_layout.py", "tests/test_drive_rag_relevance.py")
CI_ENV = {"python": "3.11", "tesseract": "5.3.4"}


def _run(cmd: List[str], timeout: int) -> Dict:
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LV_ALLOW_NETWORK": "0"})
        out = (r.stdout or "") + (r.stderr or "")
        code = r.returncode
    except subprocess.TimeoutExpired:
        out, code = "시간 초과", 124
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return {"cmd": " ".join(cmd), "code": code, "tail": lines[-3:], "seconds": round(time.time() - t0, 1)}


def classify_junit(path: str) -> Dict:
    """junit XML에서 실제 실패와 strict XPASS를 나눈다."""
    real: List[str] = []
    strict_xpass: List[str] = []
    passed = 0
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {"error": "junit 결과를 읽지 못함"}
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        bad = [ch for ch in tc if ch.tag in ("failure", "error")]
        if not bad:
            if not any(ch.tag == "skipped" for ch in tc):
                passed += 1
            continue
        msg = " ".join((ch.get("message") or "") for ch in bad)
        (strict_xpass if "XPASS(strict)" in msg else real).append(name)
    return {"passed": passed, "real_failures": real, "strict_xpass": len(strict_xpass)}


def _pytest(args: List[str], timeout: int) -> Dict:
    with tempfile.TemporaryDirectory() as d:
        xml = os.path.join(d, "r.xml")
        res = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
                    f"--junitxml={xml}", *args], timeout)
        res.update(classify_junit(xml))
    res["ok"] = "error" not in res and not res.get("real_failures") and res["code"] in (0, 1)
    return res


def _env() -> Dict:
    tess = shutil.which("tesseract")
    tver = None
    if tess:
        r = subprocess.run([tess, "--version"], capture_output=True, text=True)
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
    ap.add_argument("--out", default="artifacts/verify_all.json")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args(argv)

    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    base_ok = subprocess.run(["git", "cat-file", "-e", f"{a.base}^{{commit}}"], capture_output=True).returncode == 0
    summary: Dict = {"head": head, "base": a.base, "env": _env(), "steps": {}}
    if dirty or not base_ok:
        summary["error"] = "커밋하지 않은 변경이 있다" if dirty else f"기준 커밋 {a.base}을 찾지 못함"
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 2

    s = summary["steps"]
    s["acceptance"] = _pytest(["tests/acceptance"], a.timeout)
    s["regression_ledger"] = _pytest(["tests/regression"], a.timeout)
    sc = _run([sys.executable, "scripts/scorecard.py"], a.timeout)
    gate = _run([sys.executable, "scripts/score_gate.py"], a.timeout)
    s["score_gate"] = {**gate, "scorecard_tail": sc["tail"], "ok": sc["code"] == 0 and gate["code"] == 0}
    for name, script in (("regression_gate", "regression_gate.py"), ("hardcoding_diff", "check_hardcoding_diff.py"),
                         ("test_edits", "check_test_edits.py"), ("version_policy", "check_version_policy.py")):
        r = _run([sys.executable, f"scripts/{script}", "--base", a.base], a.timeout)
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
