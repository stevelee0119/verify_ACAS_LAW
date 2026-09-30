"""사람 판정(검토자의 동의·일부 동의·오탐) 집계(평가 에이전트 소관, 보호 경로).

검토자가 finding마다 남긴 판정(`finding_workflows.decision`)을 엔진·유형·규칙별로 모아, 어디서 오탐이 많이 나는지 본다.
이 집계는 '사람이 실제로 본 결과'라서 고정 시험이 재지 못하는 현장 오탐을 드러낸다. 모은 결과는 인계 티켓의 근거가 된다.

    python scripts/review_feedback_report.py --db-url sqlite:///data/app.db
    python scripts/review_feedback_report.py --db-url $DATABASE_URL --min-decided 10 --json out.json

- 읽기 전용이다. finding의 제목·본문·원문은 읽지도 출력하지도 않는다(개인정보·봉인 원문 보호). 건수와 식별자(엔진, 유형, 규칙 ID)만 쓴다.
- 판정이 없는 finding(UNDECIDED)은 오탐률의 분모에서 뺀다. 분모가 `--min-decided` 미만이면 오탐률을 숫자로 내지 않는다('표본 부족').
- 오탐률 = FALSE_POSITIVE / (AGREED + PARTLY_AGREED + FALSE_POSITIVE). 일부 동의는 오탐으로 세지 않는다.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

DECIDED = ("AGREED", "PARTLY_AGREED", "FALSE_POSITIVE")
QUERY = """
SELECT f.engine, f.type, f.data, COALESCE(w.decision, 'UNDECIDED') AS decision
FROM findings f
LEFT JOIN finding_workflows w ON w.finding_id = f.id
"""


def _rule_id(data: Any) -> str:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return ""
    if not isinstance(data, dict):
        return ""
    features = data.get("confidence_features") or {}
    return str(features.get("rule_id") or data.get("rule_id") or "")


def aggregate(rows: List[Dict[str, Any]], *, min_decided: int = 5) -> List[Dict[str, Any]]:
    """행({engine, type, data, decision}) 목록을 (엔진, 유형, 규칙)별 집계로 바꾼다. 오탐률 내림차순."""
    groups: Dict[tuple, Dict[str, int]] = defaultdict(lambda: {"total": 0, "UNDECIDED": 0, **{d: 0 for d in DECIDED}})
    for row in rows:
        key = (str(row.get("engine") or ""), str(row.get("type") or ""), _rule_id(row.get("data")))
        decision = str(row.get("decision") or "UNDECIDED")
        bucket = groups[key]
        bucket["total"] += 1
        bucket[decision if decision in DECIDED else "UNDECIDED"] += 1
    out = []
    for (engine, ftype, rule), c in groups.items():
        decided = sum(c[d] for d in DECIDED)
        enough = decided >= min_decided
        out.append({"engine": engine, "type": ftype, "rule_id": rule, "total": c["total"], "decided": decided,
                    "agreed": c["AGREED"], "partly_agreed": c["PARTLY_AGREED"], "false_positive": c["FALSE_POSITIVE"],
                    "undecided": c["UNDECIDED"],
                    "false_positive_rate": round(c["FALSE_POSITIVE"] / decided, 3) if enough else None,
                    "sample": "충분" if enough else "표본 부족"})
    out.sort(key=lambda g: (-(g["false_positive_rate"] if g["false_positive_rate"] is not None else -1),
                            -g["decided"], g["engine"], g["type"], g["rule_id"]))
    return out


def fetch(db_url: str) -> List[Dict[str, Any]]:
    from sqlalchemy import create_engine, text
    engine = create_engine(db_url)
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(text(QUERY))]


def render(groups: List[Dict[str, Any]], *, min_decided: int) -> str:
    decided = sum(g["decided"] for g in groups)
    total = sum(g["total"] for g in groups)
    lines = [f"사람 판정 집계 — finding {total}건 중 판정 {decided}건 (오탐률은 판정 {min_decided}건 이상인 묶음만)",
             "", "| 엔진 | 유형 | 규칙 | 판정 | 동의 | 일부 | 오탐 | 오탐률 |", "|---|---|---|---|---|---|---|---|"]
    for g in groups:
        rate = f"{g['false_positive_rate']:.0%}" if g["false_positive_rate"] is not None else "표본 부족"
        lines.append(f"| {g['engine']} | {g['type']} | {g['rule_id'] or '-'} | {g['decided']} | {g['agreed']} | "
                     f"{g['partly_agreed']} | {g['false_positive']} | {rate} |")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-url", required=True, help="SQLAlchemy URL (예: sqlite:///data/app.db)")
    parser.add_argument("--min-decided", type=int, default=5)
    parser.add_argument("--json", type=Path, help="집계를 JSON으로도 저장")
    args = parser.parse_args(argv)
    groups = aggregate(fetch(args.db_url), min_decided=args.min_decided)
    print(render(groups, min_decided=args.min_decided))
    if args.json:
        args.json.write_text(json.dumps(groups, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
