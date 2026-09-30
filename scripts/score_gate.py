"""점수 하락 게이트: 성적표(`scripts/scorecard.py`)를 기준선(`docs/scorecards/baseline.json`)과 비교한다.

    python scripts/scorecard.py && python scripts/score_gate.py
    python scripts/score_gate.py --update-baseline        # 모든 지표가 기준선 이상일 때만 기준선을 올린다(사용자 승인 필요)

실패 조건(세트마다)
- 종합점수가 기준선 − 허용오차(기본 0.5) 미만
- 오탐(FP-TRAP + 대조군)이 기준선보다 많음, A등급 오탐이 기준선보다 많음
- 같은 인용 중복 판정이나 document_id 없는 finding이 기준선보다 많음
- 기준선에서 방어했던 인젝션 시험을 방어하지 못함
- 문서별 재현율이 기준선 − 문서 허용오차(기본 0.05) 미만(개발·홀드아웃만. 한 항목을 잃은 회귀를 잡는다)
- 기준선에 있는 세트가 성적표에 없음

조건(네트워크·OCR)이 기준선과 다르면 비교 불가 경고를 낸다. --strict-env면 실패(종료 코드 3)로 본다.
종료 코드: 0 통과, 1 실패, 2 사용 오류, 3 조건 불일치(--strict-env).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURRENT = ROOT / "artifacts" / "scorecard.json"
DEFAULT_BASELINE = ROOT / "docs" / "scorecards" / "baseline.json"
COUNT_KEYS = ("false_positives", "a_grade_fp", "duplicate_citation_verdicts", "findings_without_document_id")


def env_differences(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    a, b = current.get("environment") or {}, baseline.get("environment") or {}
    diffs = []
    if bool(a.get("network")) != bool(b.get("network")):
        diffs.append(f"네트워크 {b.get('network')} → {a.get('network')}")
    if bool(a.get("tesseract")) != bool(b.get("tesseract")):
        diffs.append(f"OCR {b.get('tesseract') or '없음'} → {a.get('tesseract') or '없음'}")
    return diffs


def compare(current: Dict[str, Any], baseline: Dict[str, Any], *, tolerance: float = 0.5,
            doc_tolerance: float = 0.05) -> Tuple[List[str], List[str], List[str]]:
    """(실패, 경고, 향상) 목록."""
    failures: List[str] = []
    warnings: List[str] = []
    improvements: List[str] = []
    for diff in env_differences(current, baseline):
        warnings.append(f"조건 불일치: {diff}")
    for name, base in (baseline.get("sets") or {}).items():
        now = (current.get("sets") or {}).get(name)
        if now is None:
            failures.append(f"[{name}] 성적표에 없음")
            continue
        if now["overall"] < base["overall"] - tolerance:
            failures.append(f"[{name}] 종합 {base['overall']} → {now['overall']} (허용 −{tolerance})")
        elif now["overall"] > base["overall"] + tolerance:
            improvements.append(f"[{name}] 종합 {base['overall']} → {now['overall']}")
        for key in COUNT_KEYS:
            if now.get(key, 0) > base.get(key, 0):
                failures.append(f"[{name}] {key} {base.get(key, 0)} → {now.get(key, 0)}")
        if base.get("injection_defended") and now.get("injection_defended") is not True:
            failures.append(f"[{name}] 인젝션 방어 실패")
        for doc, recall in (base.get("per_document") or {}).items():
            after = (now.get("per_document") or {}).get(doc)
            if recall is None:
                continue
            if after is None:
                failures.append(f"[{name}] {doc} 문서별 재현율 없음")
            elif after < recall - doc_tolerance:
                failures.append(f"[{name}] {doc} 재현율 {recall} → {after} (허용 −{doc_tolerance})")
    for name in (current.get("sets") or {}):
        if name not in (baseline.get("sets") or {}):
            warnings.append(f"[{name}] 기준선에 없는 세트(비교하지 않음)")
    return failures, warnings, improvements


def can_raise_baseline(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    """기준선을 올려도 되는지(모든 지표가 기준선 이상인지). 막는 사유 목록(비면 가능)."""
    blockers, _, _ = compare(current, baseline, tolerance=0.0, doc_tolerance=0.0)
    for name, base in (baseline.get("sets") or {}).items():
        now = (current.get("sets") or {}).get(name) or {}
        if now.get("overall", 0) < base["overall"]:
            blockers.append(f"[{name}] 종합 {base['overall']} → {now.get('overall')}")
    return sorted(set(blockers))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--current", default=str(DEFAULT_CURRENT))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--tolerance", type=float, default=0.5)
    parser.add_argument("--doc-tolerance", type=float, default=0.05)
    parser.add_argument("--strict-env", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)
    try:
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"입력을 읽지 못했다: {exc}", file=sys.stderr)
        return 2
    if args.update_baseline:
        blockers = can_raise_baseline(current, baseline)
        if blockers:
            print("기준선을 올리지 않았다(기준선보다 낮은 지표):\n  " + "\n  ".join(blockers))
            return 1
        if env_differences(current, baseline):
            print("조건이 기준선과 달라 기준선을 올리지 않았다: " + "; ".join(env_differences(current, baseline)))
            return 3
        Path(args.baseline).write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"기준선을 갱신했다: {args.baseline}")
        return 0
    failures, warnings, improvements = compare(current, baseline, tolerance=args.tolerance,
                                               doc_tolerance=args.doc_tolerance)
    for line in warnings:
        print(f"경고: {line}")
    for line in improvements:
        print(f"향상: {line}  (기준선 갱신은 평가 에이전트가 요청하고 사용자가 승인한다)")
    if failures:
        print("점수 게이트 실패:\n  " + "\n  ".join(failures))
        return 1
    if args.strict_env and env_differences(current, baseline):
        print("조건 불일치로 비교할 수 없다(--strict-env)")
        return 3
    print("점수 게이트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
