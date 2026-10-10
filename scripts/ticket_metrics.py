"""인계 티켓 지표 (평가 측 도구, 2026-10-10 사용자 지시 '티켓 지표를 따로 관리').

티켓 번호는 '발견한 문제 수'다. 해소·회귀·재발은 따로 센다.

    python scripts/ticket_metrics.py            # docs/scorecards/TICKET_METRICS.md·ticket_metrics.json 갱신
    python scripts/ticket_metrics.py --check    # 등록부에 없는 티켓이 있으면 종료 1

입력
- `docs/handoff/TK-*.md`: 발견일 = 머리 8줄 안의 첫 날짜, 종류 = 머리 8줄의 유형 표기(아래 규칙).
- `docs/scorecards/ticket_registry.json`: 티켓별 상태와 날짜. 평가 측이 판정·병합·배포 때 갱신한다.
  status: open(미해결) · accepted(수용, 통합 전) · merged(Steve 병합, 미배포) · deployed(운영 배포) ·
  closed(배포 없이 닫힘: 대체·철회) · known_open(알려진 미해결, 배정 없음)
  선택: kind(regression|existing, 자동 분류를 덮어씀), recurrence_of(같은 원인의 이전 티켓), deployed_on, closed_on, note

종류 자동 분류(머리 8줄)
- '회귀가 아니'·'회귀 아님'이 있으면 existing
- '새로 만든'·'금지 행위'·'회귀(' 등 회귀 표기가 있으면 regression(구현 수정이 새로 만든 결함)
- 그 밖은 existing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs" / "handoff"
REGISTRY = ROOT / "docs" / "scorecards" / "ticket_registry.json"
OUT_MD = ROOT / "docs" / "scorecards" / "TICKET_METRICS.md"
OUT_JSON = ROOT / "docs" / "scorecards" / "ticket_metrics.json"

DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
NOT_REG_RE = re.compile(r"회귀가 아니|회귀 아님")
REG_RE = re.compile(r"새로 만든|금지 행위|회귀\(|회귀,|보안 회귀|기존 기능 회귀|\(회귀|회귀 \*\*")
OPEN_STATES = {"open", "accepted", "merged", "known_open"}
STATES = OPEN_STATES | {"deployed", "closed"}


def read_tickets() -> List[Dict]:
    out = []
    for path in sorted(HANDOFF.glob("TK-*.md")):
        tid = path.name.split("_")[0]
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        found = DATE_RE.search(head)
        if NOT_REG_RE.search(head):
            kind = "existing"
        elif REG_RE.search(head):
            kind = "regression"
        else:
            kind = "existing"
        title = head.splitlines()[0].lstrip("# ").strip() if head else tid
        out.append({"id": tid, "found_on": found.group(0) if found else None, "kind_auto": kind, "title": title,
                    "file": str(path.relative_to(ROOT))})
    return sorted(out, key=lambda t: int(t["id"].split("-")[1]))


def week_of(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def build(tickets: List[Dict], registry: Dict[str, Dict]) -> Dict:
    rows, missing = [], []
    for t in tickets:
        reg = registry.get(t["id"])
        if reg is None:
            missing.append(t["id"])
            reg = {"status": "open"}
        status = reg.get("status", "open")
        if status not in STATES:
            raise SystemExit(f"{t['id']}: 알 수 없는 상태 {status}")
        rows.append({**t, "kind": reg.get("kind") or t["kind_auto"], "status": status,
                     "recurrence_of": reg.get("recurrence_of"), "deployed_on": reg.get("deployed_on"),
                     "closed_on": reg.get("closed_on"), "note": reg.get("note", "")})
    weekly: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["found_on"]:
            wk = week_of(r["found_on"])
            weekly[wk]["found"] += 1
            weekly[wk]["regression"] += r["kind"] == "regression"
            weekly[wk]["recurrence"] += bool(r["recurrence_of"])
        for field, key in (("deployed_on", "deployed"), ("closed_on", "closed")):
            if r[field]:
                weekly[week_of(r[field])][key] += 1
    by_day: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["found_on"]:
            by_day[r["found_on"]]["found"] += 1
            by_day[r["found_on"]]["regression"] += r["kind"] == "regression"
    status_count = Counter(r["status"] for r in rows)
    return {
        "total": len(rows), "status": dict(status_count),
        "open": [r for r in rows if r["status"] in OPEN_STATES],
        "weekly": {k: dict(v) for k, v in sorted(weekly.items())},
        "daily_found": {k: dict(v) for k, v in sorted(by_day.items())},
        "regression_total": sum(r["kind"] == "regression" for r in rows),
        "unregistered": missing, "rows": rows,
    }


def render(m: Dict) -> str:
    st = m["status"]
    lines = [
        "# 티켓 지표",
        "",
        "`python scripts/ticket_metrics.py`가 만든다. 손으로 고치지 않는다. 상태는 `ticket_registry.json`(평가 측 갱신)을 따른다.",
        "티켓 번호는 발견한 문제 수다. 해소 여부·회귀(구현 수정이 새로 만든 결함)·재발은 아래처럼 따로 센다.",
        "",
        f"- 전체 {m['total']}건 · 회귀 {m['regression_total']}건 · 미해결(open·accepted·merged·known_open) {len(m['open'])}건",
        "- 상태별: " + " · ".join(f"{k} {st.get(k, 0)}" for k in ("open", "accepted", "merged", "known_open", "deployed", "closed")),
        "- 해소일(deployed_on·closed_on)은 2026-10-10 이후 기록분만 있다. 그 전 해소 건은 날짜 미상이라 주간 해소 수에 들어가지 않는다.",
        "",
        "## 주별",
        "| 주(ISO) | 발견 | 그중 회귀 | 회귀 비율 | 재발 | 배포로 해소 | 배포 없이 닫힘 |",
        "|---|---|---|---|---|---|---|",
    ]
    for wk, c in m["weekly"].items():
        found = c.get("found", 0)
        ratio = f"{c.get('regression', 0) / found:.0%}" if found else "-"
        lines.append(f"| {wk} | {found} | {c.get('regression', 0)} | {ratio} | {c.get('recurrence', 0)} | "
                     f"{c.get('deployed', 0)} | {c.get('closed', 0)} |")
    lines += ["", "## 일별 발견", "| 날짜 | 발견 | 그중 회귀 |", "|---|---|---|"]
    for day, c in m["daily_found"].items():
        lines.append(f"| {day} | {c.get('found', 0)} | {c.get('regression', 0)} |")
    lines += ["", "## 미해결 목록", "| 티켓 | 상태 | 종류 | 발견일 | 메모 |", "|---|---|---|---|---|"]
    for r in m["open"]:
        lines.append(f"| {r['id']} | {r['status']} | {r['kind']} | {r['found_on'] or '-'} | {r['note']} |")
    if m["unregistered"]:
        lines += ["", "## 등록부에 없는 티켓(open으로 셈)", ", ".join(m["unregistered"])]
    lines += ["", "## 읽는 법",
              "- 회귀 비율이 줄면 수정 과정의 품질 관리가 나아지는 것이다. 성능(처음 보는 문서의 탐지율)은 고정 비공개 벤치마크로 따로 본다(`FIXED_BENCHMARK.md`).",
              "- 종류는 티켓 머리의 유형 표기로 자동 분류한다(오차 가능). 틀리면 등록부의 `kind`로 바로잡는다."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="등록부에 없는 티켓이 있으면 종료 1(파일은 쓰지 않음)")
    a = ap.parse_args(argv)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))["tickets"] if REGISTRY.exists() else {}
    m = build(read_tickets(), registry)
    if a.check:
        if m["unregistered"]:
            print("등록부에 없는 티켓: " + ", ".join(m["unregistered"]))
            return 1
        print(f"티켓 {m['total']}건 모두 등록됨")
        return 0
    OUT_MD.write_text(render(m), encoding="utf-8")
    slim = {k: v for k, v in m.items() if k != "rows"}
    slim["open"] = [{k: r[k] for k in ("id", "status", "kind", "found_on", "note")} for r in m["open"]]
    OUT_JSON.write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"티켓 {m['total']}건 · 회귀 {m['regression_total']} · 미해결 {len(m['open'])} → {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
