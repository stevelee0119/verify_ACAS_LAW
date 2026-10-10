"""고정 비공개 벤치마크 측정 (평가 측 도구, 2026-10-10 사용자 지시). 절차: docs/scorecards/FIXED_BENCHMARK.md

같은 비공개 세트(지문 고정)를 릴리스마다 운영본과 후보로 재어, 처음 보는 문서에 대한 성능 추이를 본다.
세트는 저장소 밖에 둔다. 출력과 기록은 집계 숫자뿐이다(문서별·항목별 상세는 세트 폴더의 `.sealed_out/`에만 남는다).

    python scripts/fixed_benchmark.py --bench-dir ~/bench/fixed_bench_v1 --role 운영본 --note "릴리스 0.13.0 후보 비교"
    python scripts/fixed_benchmark.py --bench-dir ~/bench/fixed_bench_v1 --role 후보 --record
    python scripts/fixed_benchmark.py --show            # 기록된 추이(집계)만 출력

- `--record`가 있어야 `docs/scorecards/fixed_benchmark_log.jsonl`에 한 줄 남긴다(같은 지문의 세트끼리만 비교한다).
- 폴더 하나가 한 묶음(한 사건으로 처리)이다. 문서가 많으면 하위 폴더 여러 개로 나누고, 상위 폴더를 주면 묶음별로 재어 합친다
  (재현율·종합은 결함 항목 수로 가중 평균, 오탐은 합).
- 지문 = 각 묶음 폴더의 허용 파일(ground_truth.json·match_spec.json·PDF) 이름과 내용 해시로 만든 SHA-256 앞 16자리
  (봉인 세트 자체 점검과 같은 방식). 지문이 바뀌면 다른 세트다.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "scorecards" / "fixed_benchmark_log.jsonl"
ALLOWED = {"ground_truth.json", "match_spec.json"}


def _feed(digest, folder: Path) -> None:
    for p in sorted(folder.iterdir()):
        if p.is_file() and (p.name in ALLOWED or p.suffix.lower() == ".pdf"):
            digest.update(p.name.encode("utf-8"))
            digest.update(hashlib.sha256(p.read_bytes()).digest())


def subsets(bench: Path) -> list:
    """벤치마크 폴더 자체가 한 묶음이거나, 하위 폴더마다 한 묶음(한 사건)이다."""
    if (bench / "ground_truth.json").is_file():
        return [bench]
    return [p for p in sorted(bench.iterdir()) if p.is_dir() and (p / "ground_truth.json").is_file()
            and (p / "match_spec.json").is_file()]


def fingerprint(bench: Path) -> str:
    digest = hashlib.sha256()
    for sub in subsets(bench):
        digest.update(sub.relative_to(bench).as_posix().encode("utf-8"))
        _feed(digest, sub)
    return digest.hexdigest()[:16]


def combine(rows: list) -> dict:
    """묶음별 집계를 합친다. 재현율·종합은 결함 항목 수로 가중 평균, 오탐·문서·항목은 합, 인젝션은 모두 방어해야 방어."""
    items = sum(r["defect_items"] for r in rows) or 1
    out = {k: sum(r[k] for r in rows) for k in ("documents", "defect_items", "false_positives", "fp_trap",
                                                 "control_fp", "a_grade_fp")}
    out["weighted_recall"] = round(sum(r["weighted_recall"] * r["defect_items"] for r in rows) / items, 3)
    out["overall"] = round(sum(r["overall"] * r["defect_items"] for r in rows) / items, 1)
    flags = [r["injection_defended"] for r in rows if r["injection_defended"] is not None]
    out["injection_defended"] = None if not flags else all(flags)
    return out


def load_scorecard():
    spec = importlib.util.spec_from_file_location("scorecard", ROOT / "scripts" / "scorecard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def show() -> int:
    if not LOG.exists():
        print("기록 없음")
        return 0
    rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{'기록일':<11}{'지문':<18}{'역할':<6}{'커밋':<9}{'종합':>7}{'재현율':>8}{'오탐':>5}{'A오탐':>6}")
    for r in rows:
        print(f"{r['recorded'][:10]:<11}{r['fingerprint']:<18}{r['role']:<6}{(r['git'] or '')[:7]:<9}"
              f"{r['overall']:>7}{r['weighted_recall']:>8}{r['false_positives']:>5}{r['a_grade_fp']:>6}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench-dir", help="저장소 밖의 고정 벤치마크 폴더")
    ap.add_argument("--role", choices=["운영본", "후보", "기타"], default="기타")
    ap.add_argument("--note", default="")
    ap.add_argument("--record", action="store_true", help="집계를 fixed_benchmark_log.jsonl에 남긴다")
    ap.add_argument("--show", action="store_true", help="기록된 추이만 출력")
    a = ap.parse_args(argv)
    if a.show:
        return show()
    if not a.bench_dir:
        ap.error("--bench-dir가 필요하다")
    bench = Path(a.bench_dir).expanduser().resolve()
    if ROOT in bench.parents or bench == ROOT:
        print("벤치마크 폴더가 저장소 안에 있다. 저장소 밖으로 옮긴다.", file=sys.stderr)
        return 2
    parts = subsets(bench)
    if not parts:
        print(f"ground_truth.json·match_spec.json이 있는 묶음이 없다: {bench}", file=sys.stderr)
        return 2
    sc = load_scorecard()
    cards = [sc.build({}, part) for part in parts]
    card = cards[0]
    row = combine([c["sets"]["sealed"] for c in cards])
    entry = {
        "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(bench), "bench_name": bench.name, "subsets": len(parts), "role": a.role,
        "git": (card["git"] or {}).get("sha"), "dirty": (card["git"] or {}).get("dirty"),
        "version": card["version"], "rule_version": card["rule_version"], "environment": card["environment"],
        **{k: row[k] for k in ("documents", "defect_items", "overall", "weighted_recall", "false_positives",
                               "fp_trap", "control_fp", "a_grade_fp", "injection_defended")},
        "note": a.note,
    }
    env = entry["environment"]
    defended = {True: "방어", False: "실패", None: "-"}[entry["injection_defended"]]
    print(f"고정 벤치마크 {entry['bench_name']} · 지문 {entry['fingerprint']} · {a.role} {(entry['git'] or '?')[:7]}"
          + (" · 미커밋 변경 있음" if entry["dirty"] else ""))
    print(f"조건: 오프라인, OCR {env['tesseract'] or '없음'}, python {env['python']}")
    print(f"묶음 {entry['subsets']} · 문서 {entry['documents']} · 결함 {entry['defect_items']} · 종합 {entry['overall']} · 재현율 {entry['weighted_recall']}"
          f" · 오탐 {entry['false_positives']}(대조군 {entry['control_fp']}, A등급 {entry['a_grade_fp']}) · 인젝션 {defended}")
    if a.record:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"기록: {LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
