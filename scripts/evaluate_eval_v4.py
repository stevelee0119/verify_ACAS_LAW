# -*- coding: utf-8 -*-
"""eval_v4 채점 CLI (채점기 v2: scripts/eval_v4_scoring.py).

    python scripts/evaluate_eval_v4.py --answer-key <정답지.json> --report reports/verification_v090_eval_v4.json

- 정답지 경로는 인자로 받는다(특정 PC 경로를 코드에 두지 않는다). 정답지는 채점에만 쓰고 구현에 쓰지 않는다.
- 결과는 새 파일로만 쓴다. 같은 이름이 있으면 실패한다(이전 채점 산출물 보존). 기본 파일명에 채점기 버전을 넣는다.
- 이전 채점기(v1, 커밋 8f3bad6)의 점수와 v2 지표는 정의가 달라 증감으로 비교하지 않는다.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.eval_v4_scoring import SCORER_VERSION, iter_markdown, score, write_new  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answer-key", required=True, help="eval_v4 정답지 JSON")
    parser.add_argument("--report", default=str(ROOT / "reports" / "verification_v090_eval_v4.json"),
                        help="검증 파이프라인 결과 JSON")
    parser.add_argument("--out", help="채점 결과 JSON 경로(기본: reports/eval_v4_<채점기 버전>_<시각>.json)")
    args = parser.parse_args(argv)
    answer_key = json.loads(Path(args.answer_key).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = score(answer_key, report)
    result["inputs"] = {"answer_key": Path(args.answer_key).name, "report": str(args.report),
                        "answer_key_version": answer_key.get("version")}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else ROOT / "reports" / f"eval_v4_{SCORER_VERSION}_{stamp}.json"
    write_new(out, result)
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for line in iter_markdown(result):
        print(line, file=stream)
    print(f"저장: {out}", file=stream)
    stream.flush()
    return 0 if result["evaluation_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
