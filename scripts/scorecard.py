"""성적표: 현재 코드로 고정 시험을 채점해 JSON 한 개로 낸다(평가 에이전트 소관, 보호 경로).

    python scripts/scorecard.py                          # 개발 시험 + 홀드아웃, 오프라인
    python scripts/scorecard.py --sealed-dir <경로>       # 저장소 밖에 둔 봉인 시험을 함께 채점(집계 숫자만 출력)
    python scripts/score_gate.py                         # 기준선과 비교해 통과·실패 판정

조건은 항상 같다: 같은 시험문서, 같은 채점기(`scripts/eval_testset.py`), 네트워크 끔(공식 DB·AI 모델 없음).
이 조건의 점수끼리만 증감으로 비교한다. AI 작성 판별·공식 DB 대조·Drive 대조는 이 조건에서 재지 못한다.

봉인 시험은 문서·정답을 저장소에 두지 않는다. 출력에는 종합·재현율·오탐 수만 싣고 문서별·항목별 값은 싣지 않는다.
상세는 봉인 폴더 안 `.sealed_out/`에만 쓴다(사용자만 본다).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
DEV_SET = ROOT / "tests/fixtures/legal_verifier_testset"
HOLDOUT_SET = ROOT / "tests/fixtures/holdout"
SCHEMA = 1


def load_evaluator():
    """`scripts/eval_testset.py`를 모듈로 읽는다(scripts는 패키지가 아니다)."""
    spec = importlib.util.spec_from_file_location("eval_testset", ROOT / "scripts" / "eval_testset.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_testset", module)
    spec.loader.exec_module(module)
    return module


def summarize(report: Dict[str, Any], *, documents: int, sealed: bool) -> Dict[str, Any]:
    """채점 보고서에서 성적표에 싣는 값만 추린다. 봉인이면 문서별 값을 싣지 않는다."""
    injection = report.get("injection_defense")
    out = {
        "documents": documents,
        "overall": report["overall"],
        "weighted_recall": report["weighted_recall"],
        "defect_items": report["defect_items"],
        "false_positives": report["false_positives_total"],
        "fp_trap": report["fp_trap_false_positives"],
        "control_fp": report["control_false_positives"],
        "a_grade_fp": report["a_grade_false_positives"],
        "duplicate_citation_verdicts": report["duplicate_citation_verdicts"],
        "findings_without_document_id": report["findings_without_document_id"],
        "injection_defended": None if injection is None else bool(injection.get("defended")),
    }
    if not sealed:
        out["per_document"] = {doc: value["recall"] for doc, value in report["per_document"].items()}
    return out


def run_set(evaluator, testset: Path, *, sealed: bool) -> Dict[str, Any]:
    result = evaluator.run_pipeline(testset)
    report = evaluator.score(result, testset, db_available=False)
    documents = len(json.loads((testset / "ground_truth.json").read_text(encoding="utf-8"))["documents"])
    summary = summarize(report, documents=documents, sealed=sealed)
    if sealed:
        detail_dir = testset / ".sealed_out"
        detail_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (detail_dir / f"scorecard_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def tesseract_info() -> Dict[str, Any]:
    binary = shutil.which("tesseract")
    if not binary:
        return {"version": None, "langs": []}
    try:
        text = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10).stdout
        version = (text.splitlines() or [""])[0].replace("tesseract", "").strip() or None
        langs = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=10).stdout.split()[4:]
    except (OSError, subprocess.SubprocessError):
        return {"version": None, "langs": []}
    return {"version": version, "langs": sorted(langs)}


def git_info() -> Dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"sha": run("rev-parse", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}


def environment() -> Dict[str, Any]:
    tess = tesseract_info()
    return {"network": os.getenv("LV_ALLOW_NETWORK") != "0", "tesseract": tess["version"],
            "ocr_langs": tess["langs"], "python": platform.python_version()}


def build(sets: Dict[str, Path], sealed_dir: Optional[Path]) -> Dict[str, Any]:
    # 채점은 항상 오프라인. 패키지를 읽기 전에 정한다.
    os.environ["LV_ALLOW_NETWORK"] = "0"
    scratch = tempfile.mkdtemp(prefix="scorecard_")
    os.environ["LV_DATA_DIR"] = scratch
    evaluator = load_evaluator()
    from packages.common.config import get_settings

    settings = get_settings()
    card: Dict[str, Any] = {
        "schema": SCHEMA, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_info(), "version": settings.version, "rule_version": settings.rule_version,
        "environment": environment(), "sets": {},
    }
    try:
        for name, path in sets.items():
            card["sets"][name] = run_set(evaluator, path, sealed=False)
        if sealed_dir is not None:
            card["sets"]["sealed"] = run_set(evaluator, sealed_dir, sealed=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return card


def render(card: Dict[str, Any]) -> str:
    env = card["environment"]
    lines = [f"성적표 — {card['version']} (rule {card['rule_version']}) · {((card['git'] or {}).get('sha') or '?')[:7]}"
             + (" · 미커밋 변경 있음" if (card["git"] or {}).get("dirty") else ""),
             f"조건: 오프라인, OCR {env['tesseract'] or '없음'}, python {env['python']}", ""]
    lines.append(f"{'세트':<10}{'종합':>7}{'재현율':>8}{'오탐':>6}{'A등급':>6}{'인젝션':>8}")
    for name, row in card["sets"].items():
        defended = {True: "방어", False: "실패", None: "-"}[row["injection_defended"]]
        lines.append(f"{name:<10}{row['overall']:>7}{row['weighted_recall']:>8}{row['false_positives']:>6}"
                     f"{row['a_grade_fp']:>6}{defended:>8}")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "scorecard.json"))
    parser.add_argument("--sets", default="dev,holdout", help="쉼표 구분: dev, holdout")
    parser.add_argument("--sealed-dir", default=os.getenv("LV_SEALED_DIR"),
                        help="저장소 밖 봉인 시험 폴더(ground_truth.json, match_spec.json, PDF). 집계만 출력한다")
    args = parser.parse_args(argv)
    known = {"dev": DEV_SET, "holdout": HOLDOUT_SET}
    names = [n.strip() for n in args.sets.split(",") if n.strip()]
    if not names or any(n not in known for n in names):
        print(f"--sets는 {sorted(known)} 중에서 고른다", file=sys.stderr)
        return 2
    sealed_dir = Path(args.sealed_dir).resolve() if args.sealed_dir else None
    if sealed_dir is not None:
        if ROOT in sealed_dir.parents or sealed_dir == ROOT:
            print("봉인 시험 폴더는 저장소 밖에 있어야 한다", file=sys.stderr)
            return 2
        if not (sealed_dir / "ground_truth.json").is_file() or not (sealed_dir / "match_spec.json").is_file():
            print(f"봉인 시험 폴더에 ground_truth.json·match_spec.json이 없다: {sealed_dir}", file=sys.stderr)
            return 2
    card = build({n: known[n] for n in names}, sealed_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(card))
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
