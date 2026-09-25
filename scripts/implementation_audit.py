"""구현 감사표(v4 P0)를 만든다: 합성 PDF 사건 묶음을 실제 파이프라인에 넣어 항목마다 확인한다.

항목마다 확인하는 것
1. 파이프라인 호출 — 구현 기호가 호출 위치 파일에서 정의가 아닌 호출로 쓰이는지(소스 확인)
2. 준비한 결함 수 / 탐지 수 / 오탐 수 — 심어 둔 결함(scripts/audit/items.py)마다 대응 finding이 있는지,
   그 항목의 finding 가운데 어느 결함에도 대응하지 않는 것(오탐)이 몇 건인지
3. 보고서 반영 — 대응 finding의 ID가 검증 JSON에, 제목이 docx 본문에 있는지
4. 요약 점수 반영 — 그 finding을 빼고 scores.axes를 다시 계산하면 값이 달라지는지
완료 기준: 호출·보고서·요약 점수 반영, 탐지율 90% 이상, 오탐 0건.
실연동 항목(live)은 docs/live_integration_results.json(CI '실연동 통합 테스트' 결과)이 통과로 기록될 때까지 '미확인'이다.

사용: python scripts/implementation_audit.py --label "수정 후 (0.8.0)"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit import items as I  # noqa: E402
from scripts.audit.runner import run_synthetic  # noqa: E402

LIVE_RESULTS = ROOT / "docs" / "live_integration_results.json"
HEADER = ("| 항목 | 내용 | 구현 코드 위치 | 파이프라인 호출 위치 | 단위·통합 테스트 | 준비한 결함 수 | 탐지 수 | 오탐 수 | "
          "보고서(JSON·docx) | 요약 점수(scores.axes) | 상태 |")


def called(call):
    rel, symbol = call
    path = ROOT / rel if rel.startswith(("apps/", "scripts/")) else ROOT / "packages" / rel
    if not path.exists():
        return False, f"{rel} 없음"
    text = path.read_text(encoding="utf-8")
    uses = [m for m in re.finditer(re.escape(symbol), text)
            if not re.match(r"\s*def\s", text[text.rfind("\n", 0, m.start()) + 1:m.start()])]
    return bool(uses), f"{rel}:{symbol}"


def axes_changed(result, finding):
    from packages.verification_engine.scoring import aggregate_scores
    base = json.dumps(aggregate_scores(result).get("axes"), sort_keys=True, default=str)
    holder = next((d.findings for d in result.documents if finding in d.findings), result.project_findings)
    index = holder.index(finding)
    holder.pop(index)
    try:
        return json.dumps(aggregate_scores(result).get("axes"), sort_keys=True, default=str) != base
    finally:
        holder.insert(index, finding)


def in_reports(out, finding):
    payload = json.dumps(out["payload"], ensure_ascii=False, default=str)
    title = re.sub(r"\s+", " ", finding.title or "")
    probes = [title[:24], title.split(":")[-1].strip()[:20]]
    return finding.finding_id in payload, any(p and p in out["docx_text"] for p in probes)


def live_results():
    try:
        return json.loads(LIVE_RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def evaluate(out):
    findings = I.all_findings(out)
    live = live_results()
    rows, details = [], {}
    by_id = {}
    for item in I.ITEMS:
        if item.get("same_as"):
            continue
        is_called, where = called(item["call"])
        detail = []
        matched = []
        prepared = detected = 0
        if item.get("r2"):
            r2 = I.r2_binding(out)
            prepared, detected = r2["total"], r2["ok"]
            detail = [f"{r['case']}: 기대 {'인용문 있음' if r['expected'] else '인용문 없음'} / 결과 "
                      f"{['있음' if a else '없음' for a in r['actual']] or '인용 미추출'} → {'성공' if r['ok'] else '실패'}"
                      for r in r2["rows"]]
        for defect in item.get("defects", []):
            prepared += 1
            if defect["check"] is not None:
                ok = bool(defect["check"](out))
                hits = []
            else:
                hits = [f for f in findings if defect["match"](f)]
                if defect.get("doc"):
                    hits = [f for f in hits if I.doc_of(out, f) == defect["doc"]]
                if item.get("doc_scope"):
                    hits = [f for f in hits if I.doc_of(out, f) == item["doc_scope"]]
                ok = bool(hits)
            detected += ok
            matched += hits
            detail.append(f"{defect['id']} {defect['desc']}: {'탐지' if ok else '미탐지'}"
                          + (f" — {hits[0].title[:90]}" if hits else ""))
        # 오탐: 항목 finding 가운데 어느 결함에도 대응하지 않는 것 + 별도 오탐 판정
        false_positive = 0
        if item.get("family"):
            family = [f for f in findings if item["family"](f)]
            if item.get("doc_scope"):
                family = [f for f in family if I.doc_of(out, f) == item["doc_scope"]]
            if item.get("family_docs"):
                family = [f for f in family if I.doc_of(out, f) in item["family_docs"]]
            if item.get("fp_doc_exclude"):
                family = [f for f in family if I.doc_of(out, f) not in item["fp_doc_exclude"]]
                matched_ids = set()
            else:
                matched_ids = {id(f) for f in matched}
            extra = [f for f in family if id(f) not in matched_ids]
            false_positive += len(extra)
            detail += [f"오탐: {f.title[:90]} ({I.doc_of(out, f)})" for f in extra[:5]]
        if item.get("fp_check"):
            count = int(item["fp_check"](out))
            false_positive += count
            if count:
                detail.append(f"오탐(별도 판정): {count}건")

        if item.get("live"):
            record = live.get(item["id"]) or {}
            passed = record.get("passed") is True
            status = "완료(실연동)" if passed and is_called else "미확인"
            note = record.get("summary") or "실연동 통합 테스트 결과 없음"
            if prepared:
                note = f"{note}; 오프라인 합성 {detected}/{prepared}"
            rows.append(dict(id=item["id"], title=item["title"], code=item["code"], call=where if is_called else f"{where}(호출 없음)",
                             tests=item["tests"], prepared=record.get("prepared", prepared or "—"),
                             detected=record.get("detected", detected if prepared else "—"),
                             fp=record.get("false_positive", "—"), report="—", axes="—", status=status))
            details[item["id"]] = [note, *detail]
            by_id[item["id"]] = rows[-1]
            continue

        if item.get("report_na") or not matched:
            report_cell, reported = ("해당 없음(판정 산출물)" if item.get("report_na") else "—"), bool(item.get("report_na"))
            axes_cell, axes_ok = ("해당 없음" if item.get("report_na") else "—"), bool(item.get("report_na"))
        else:
            marks = [in_reports(out, f) for f in matched]
            json_ok, docx_ok = all(m[0] for m in marks), all(m[1] for m in marks)
            report_cell = f"JSON {'O' if json_ok else 'X'} · docx {'O' if docx_ok else 'X'}"
            reported = json_ok and docx_ok
            changed = [axes_changed(out["result"], f) for f in matched]
            axes_ok = all(changed)
            axes_cell = "반영" if axes_ok else ("일부 반영" if any(changed) else "반영 안 됨")
        rate = detected / prepared if prepared else 0.0
        if not is_called:
            status = "연결 안 됨"
        elif not prepared:
            status = "미확인"
        elif detected == 0:
            status = "미구현" if not matched else "부분(탐지 실패)"
        elif rate >= 0.9 and false_positive == 0 and reported and axes_ok:
            status = "완료"
        else:
            reasons = []
            if rate < 0.9:
                reasons.append(f"탐지율 {rate:.0%}")
            if false_positive:
                reasons.append(f"오탐 {false_positive}")
            if not reported:
                reasons.append("보고서 누락")
            if not axes_ok:
                reasons.append("요약 점수 미반영")
            status = "부분(" + ", ".join(reasons) + ")"
        row = dict(id=item["id"], title=item["title"], code=item["code"], call=where if is_called else f"{where}(호출 없음)",
                   tests=item["tests"], prepared=prepared, detected=detected, fp=false_positive,
                   report=report_cell, axes=axes_cell, status=status)
        rows.append(row)
        by_id[item["id"]] = row
        details[item["id"]] = detail
    for item in I.ITEMS:
        if item.get("same_as") and item["same_as"] in by_id:
            base = dict(by_id[item["same_as"]])
            base.update(id=item["id"], title=item["title"], tests=item["tests"])
            rows.insert([r["id"] for r in rows].index(item["same_as"]) + 1, base) if False else rows.append(base)
            details[item["id"]] = [f"{item['same_as']}와 같은 결함 집합으로 판정"] + details.get(item["same_as"], [])
    return rows, details


def render(label, rows, details, out):
    from packages.common.config import get_settings
    settings = get_settings()
    manifest = out["result"].run_manifest or {}
    counts = {}
    for row in rows:
        key = row["status"].split("(")[0]
        counts[key] = counts.get(key, 0) + 1
    prepared = sum(r["prepared"] for r in rows if isinstance(r["prepared"], int))
    detected = sum(r["detected"] for r in rows if isinstance(r["detected"], int))
    fps = sum(r["fp"] for r in rows if isinstance(r["fp"], int))
    lines = [f"## {label}", "",
             f"- 실행일: {date.today().isoformat()} · 프로그램 {settings.version} · 규칙 {settings.rule_version}",
             "- 합성 문서(모두 PDF, 표·여러 쪽·머리글/바닥글): 민사 준비서면·진단서, 행정 의견서(숨김·구조 경로 인젝션)·손상 문서, "
             "형사 변론요지서(3쪽 스캔·4쪽 회전 스캔), 가사 소장·답변서 — `scripts/audit/corpus.py`",
             "- 완료 기준: 파이프라인 호출·보고서·요약 점수 반영, 탐지율 90% 이상, 오탐 0건. 실연동 항목은 CI 실연동 통합 테스트 통과 전 '미확인'",
             f"- 합계: 준비한 결함 {prepared} · 탐지 {detected} · 오탐 {fps}",
             "- 상태 집계: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
             f"- 실행 매니페스트: 실행하지 않은 엔진 {manifest.get('not_executed', [])} (예시 전문: `docs/run_manifest_example.json`)", "",
             HEADER, "|" + "---|" * 11]
    for r in rows:
        cells = [r["id"], r["title"], r["code"], r["call"], r["tests"], r["prepared"], r["detected"], r["fp"], r["report"], r["axes"], r["status"]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    lines += ["", "<details><summary>결함별 탐지 내역</summary>", ""]
    for r in rows:
        items = details.get(r["id"]) or []
        if items:
            lines.append(f"- **{r['id']}** " + "; ".join(i.replace("|", "\\|") for i in items))
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def write(path: Path, label: str, section: str):
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^## {re.escape(label)}\n.*?(?=^## |\Z)", re.S | re.M)
    text = pattern.sub(lambda m: section + "\n", text) if pattern.search(text) else text.rstrip("\n") + "\n\n" + section
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", default=str(ROOT / "docs" / "IMPLEMENTATION_AUDIT.md"))
    parser.add_argument("--dry-run", action="store_true", help="문서를 고치지 않고 결과만 출력")
    args = parser.parse_args()
    out = run_synthetic()
    rows, details = evaluate(out)
    if not args.dry_run:
        write(Path(args.out), args.label, render(args.label, rows, details, out))
        Path(args.out).with_name("run_manifest_example.json").write_text(
            json.dumps(out["result"].run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(f"{r['id']:5} {str(r['prepared']):>3}/{str(r['detected']):<3} fp={str(r['fp']):<3} {r['status']}")
        if "--verbose" in sys.argv or r["status"] not in ("완료", "완료(실연동)"):
            for line in details.get(r["id"], [])[:20]:
                print("      ", line)


if __name__ == "__main__":
    main()
