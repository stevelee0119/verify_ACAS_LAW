"""두 평가 결과(eval_testset.py가 만든 eval_*.json)를 항목 단위로 비교한다.

    python scripts/eval_compare.py 이전.json 현재.json [--out 비교.md] [--json 비교.json]

항목은 (문서, 결함 유형, 위치, 대상)으로 맞춘다. 점수(credit)가
- 0 → 양수: 새로 잡은 것
- 양수 → 0: 놓치게 된 것(회귀)
- 둘 다 양수인데 달라짐: 판정 방식 변화(예: 시스템 판정 1.0 ↔ 참고 신호 0.5)
정상 함정(FP-TRAP) 오탐은 새로 생긴 것과 없어진 것을 따로 센다. 판정 방식이 낮아진 것도 회귀로 센다.
정답지는 읽지 않는다. 채점이 끝난 두 결과 파일만 쓴다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _key(item: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (item.get("doc", ""), item.get("type", ""), item.get("location", ""), item.get("target", ""))


def _fp_key(detail: str) -> str:
    # "문서 FP-TRAP '대상' ← [등급] 유형: 제목 — 설명" 중 문서·대상·유형·제목까지로 맞춘다(설명 문구 변화는 무시)
    return detail.split(" — ", 1)[0]


def compare(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    before = {_key(i): i for i in previous.get("items") or []}
    after = {_key(i): i for i in current.get("items") or []}
    newly, lost, down, up, unmatched = [], [], [], [], []
    for key, item in after.items():
        old = before.get(key)
        if old is None:
            unmatched.append({"key": list(key), "note": "이전 결과에 없는 항목(정답지 변경)"})
            continue
        a, b = float(old.get("credit") or 0), float(item.get("credit") or 0)
        row = {"doc": key[0], "type": key[1], "location": key[2], "target": key[3],
               "before": {"credit": a, "how": old.get("how")}, "after": {"credit": b, "how": item.get("how")},
               "evidence": (item.get("evidence") or old.get("evidence") or [])[:2]}
        if a == 0 and b > 0:
            newly.append(row)
        elif a > 0 and b == 0:
            lost.append(row)
        elif b < a:
            down.append(row)
        elif b > a:
            up.append(row)
    for key in before.keys() - after.keys():
        unmatched.append({"key": list(key), "note": "현재 결과에 없는 항목(정답지 변경)"})
    fp_before = {_fp_key(d) for d in previous.get("fp_details") or []}
    fp_after = {_fp_key(d) for d in current.get("fp_details") or []}
    summary = {
        "overall": [previous.get("overall"), current.get("overall")],
        "weighted_recall": [previous.get("weighted_recall"), current.get("weighted_recall")],
        "fp_trap_false_positives": [previous.get("fp_trap_false_positives"), current.get("fp_trap_false_positives")],
        "a_grade_false_positives": [previous.get("a_grade_false_positives"), current.get("a_grade_false_positives")],
        "db_available": [previous.get("db_available"), current.get("db_available")],
        "injection_defended": [(previous.get("injection_defense") or {}).get("defended"),
                               (current.get("injection_defense") or {}).get("defended")],
    }
    regressions = len(lost) + len(down) + len(fp_after - fp_before)
    return {"summary": summary, "newly_caught": newly, "lost": lost, "credit_down": down, "credit_up": up,
            "new_false_positives": sorted(fp_after - fp_before), "removed_false_positives": sorted(fp_before - fp_after),
            "item_set_changes": unmatched, "regressions": regressions}


def render(title: str, diff: Dict[str, Any]) -> str:
    s = diff["summary"]
    lines = [f"### {title}", "",
             f"- 종합점수 {s['overall'][0]} → {s['overall'][1]}, 가중 재현율 {s['weighted_recall'][0]} → {s['weighted_recall'][1]}",
             f"- 정상 함정 오탐 {s['fp_trap_false_positives'][0]} → {s['fp_trap_false_positives'][1]}, "
             f"A등급 오탐 {s['a_grade_false_positives'][0]} → {s['a_grade_false_positives'][1]}, "
             f"공식 DB 조회 {s['db_available'][0]} → {s['db_available'][1]}, 인젝션 방어 {s['injection_defended'][0]} → {s['injection_defended'][1]}",
             f"- **회귀 {diff['regressions']}건**(놓치게 된 것 {len(diff['lost'])}, 판정 방식 하락 {len(diff['credit_down'])}, "
             f"새 오탐 {len(diff['new_false_positives'])})", ""]

    def table(name, rows):
        lines.append(f"**{name}** ({len(rows)}건)")
        lines.append("")
        if not rows:
            lines.extend(["없음", ""])
            return
        lines.extend(["| 문서 | 유형 | 위치 | 대상 | 이전 | 현재 |", "|---|---|---|---|---|---|"])
        for r in rows:
            target = (r["target"] or "").replace("|", "\\|")[:60]
            lines.append(f"| {r['doc']} | {r['type']} | {r['location']} | {target} | "
                         f"{r['before']['credit']} {r['before']['how']} | {r['after']['credit']} {r['after']['how']} |")
        lines.append("")

    table("새로 잡은 것", diff["newly_caught"])
    table("놓치게 된 것", diff["lost"])
    table("판정 방식 하락(점수는 남음)", diff["credit_down"])
    table("판정 방식 상승", diff["credit_up"])
    lines.append(f"**새 오탐** ({len(diff['new_false_positives'])}건)")
    lines += [""] + ([f"- {d}" for d in diff["new_false_positives"]] or ["없음"]) + [""]
    lines.append(f"**없어진 오탐** ({len(diff['removed_false_positives'])}건)")
    lines += [""] + ([f"- {d}" for d in diff["removed_false_positives"]] or ["없음"]) + [""]
    if diff["item_set_changes"]:
        lines += [f"정답지 항목 변화 {len(diff['item_set_changes'])}건(비교 제외)", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("previous")
    parser.add_argument("current")
    parser.add_argument("--title", default="평가 비교")
    parser.add_argument("--out")
    parser.add_argument("--json")
    args = parser.parse_args()
    diff = compare(json.loads(Path(args.previous).read_text(encoding="utf-8")),
                   json.loads(Path(args.current).read_text(encoding="utf-8")))
    text = render(args.title, diff)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(diff, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
