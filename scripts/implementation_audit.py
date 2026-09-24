"""구현 감사표(v4 P0)를 만든다: 합성 문서를 실제 파이프라인에 넣어 항목마다 확인한다.

확인하는 것(v4 §1-4의 '구현 완료' 네 조건):
1. 파이프라인에서 호출되는가 — 구현 기호가 호출 위치 파일에서 실제로 호출되는지(정의가 아닌 호출) 소스에서 확인
2. finding이 생성되는가 — 합성 문서 실행 결과에서 항목 판정 함수로 확인
3. 보고서(JSON·docx)에 표시되는가 — 해당 finding의 ID가 검증 JSON에, 제목이 docx 본문에 있는지
4. 요약 점수(scores.axes)에 반영되는가 — 그 finding을 빼고 요약 점수를 다시 계산해 값이 달라지는지

사용: python scripts/implementation_audit.py --label "수정 전(0.7.0)" [--out docs/IMPLEMENTATION_AUDIT.md]
같은 label의 절은 새 결과로 바꾸고, 다른 label의 절은 그대로 둔다(수정 전·후 비교).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit.items import ITEMS  # noqa: E402
from scripts.audit.runner import run_synthetic  # noqa: E402

HEADER = ("| 항목 | 내용 | 구현 코드 위치 | 파이프라인 호출 위치 | 단위 테스트 | 합성 문서 실행 시 finding | "
          "보고서(JSON·docx) | 요약 점수(scores.axes) | 상태 |")


def called(call):
    """호출 위치 파일에서 기호가 정의가 아닌 호출·참조로 쓰이는지."""
    rel, symbol = call
    path = ROOT / "packages" / rel if not rel.startswith(("apps/", "scripts/")) else ROOT / rel
    if not path.exists():
        return False, f"{rel} 없음"
    text = path.read_text(encoding="utf-8")
    uses = [m for m in re.finditer(re.escape(symbol), text)
            if not re.match(r"\s*def\s", text[text.rfind("\n", 0, m.start()) + 1:m.start()])]
    return bool(uses), f"{rel}:{symbol}"


def axes_changed(result, finding):
    from packages.verification_engine.scoring import aggregate_scores
    base = json.dumps(aggregate_scores(result).get("axes"), sort_keys=True, default=str)
    holder = next((d.findings for d in result.documents if finding in d.findings), None)
    if holder is None:
        holder = result.project_findings
    index = holder.index(finding)
    holder.pop(index)
    try:
        changed = json.dumps(aggregate_scores(result).get("axes"), sort_keys=True, default=str) != base
    finally:
        holder.insert(index, finding)
    return changed


def in_reports(out, finding):
    payload = json.dumps(out["payload"], ensure_ascii=False, default=str)
    in_json = finding.finding_id in payload
    title = re.sub(r"\s+", " ", finding.title or "")
    probes = [title[:24], title.split(":")[-1].strip()[:20]]
    in_docx = any(p and p in out["docx_text"] for p in probes)
    return in_json, in_docx


def evaluate(out):
    rows = []
    for item in ITEMS:
        is_called, where = called(item["call"])
        flag, hits, note = item["check"](out)
        if flag is None:
            finding_cell, report_cell, axes_cell = f"확인 불가 — {note}", "—", "—"
            status = "완료(단위 테스트)" if is_called else "연결 안 됨"
        else:
            finding_cell = ("생성" if flag else "생성 안 됨") + f" ({note})"
            if item.get("report_na"):
                report_cell = "해당 없음(판정 산출물)"
                reported = True
            elif hits:
                marks = [in_reports(out, f) for f in hits]
                json_ok = all(m[0] for m in marks)
                docx_ok = any(m[1] for m in marks)
                report_cell = f"JSON {'O' if json_ok else 'X'} · docx {'O' if docx_ok else 'X'}"
                reported = json_ok and docx_ok
            else:
                report_cell, reported = "—", False
            if item.get("axes_from_check"):
                axes_ok = bool(flag)
                axes_cell = "반영(legal_citation_accuracy.verified)" if axes_ok else "반영 안 됨"
            elif hits:
                changed = [axes_changed(out["result"], f) for f in hits]
                axes_ok = all(changed)
                axes_cell = "반영" if axes_ok else ("일부 반영" if any(changed) else "반영 안 됨")
            else:
                axes_ok = item.get("report_na", False)
                axes_cell = "해당 없음" if axes_ok else "—"
            if not is_called:
                status = "연결 안 됨"
            elif flag and reported and axes_ok:
                status = "완료"
            elif flag or hits:
                status = "부분"
            else:
                status = "부분(탐지 실패)"
        rows.append({"id": item["id"], "title": item["title"], "code": item["code"], "call": where if is_called else f"{where}(호출 없음)",
                     "tests": item["tests"], "finding": finding_cell, "report": report_cell, "axes": axes_cell, "status": status})
    return rows


def render(label, rows, out):
    manifest = out["result"].run_manifest or {}
    counts = {}
    for row in rows:
        key = row["status"].split("(")[0]
        counts[key] = counts.get(key, 0) + 1
    lines = [f"## {label}", "",
             f"- 실행일: {date.today().isoformat()} · 프로그램 {__import__('packages.common.config', fromlist=['get_settings']).get_settings().version}"
             f" · 규칙 {__import__('packages.common.config', fromlist=['get_settings']).get_settings().rule_version}",
             "- 합성 문서: 민사 준비서면·진단서·소장(txt), 행정 의견서(숨김·구조 경로 인젝션 PDF), 형사 스캔 서면(이미지 PDF). "
             "`scripts/audit/synthetic_docs.py`",
             "- 상태 집계: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
             f"- 실행 매니페스트: 실행하지 않은 엔진 {manifest.get('not_executed', [])}", "",
             HEADER, "|" + "---|" * 9]
    for r in rows:
        cells = [r["id"], r["title"], r["code"], r["call"], r["tests"], r["finding"], r["report"], r["axes"], r["status"]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def write(path: Path, label: str, section: str):
    intro = ("# 구현 여부 감사표 (v4 P0)\n\n"
             "지시서 항목이 '함수가 있다'가 아니라 **실제 파이프라인에서 호출되고, finding을 만들고, 보고서에 표시되고, "
             "요약 점수에 반영되는지**를 합성 문서 실행으로 확인한 표다. `python scripts/implementation_audit.py --label …`로 "
             "다시 만든다.\n\n"
             "- 상태: 완료 / 부분 / 부분(탐지 실패) / 미구현 / 연결 안 됨 / 완료(단위 테스트: 오프라인 합성 실행으로 확인할 수 없어 "
             "단위 테스트·CI 실연동으로 확인)\n"
             "- '보고서 해당 없음'은 finding이 아니라 판정 라벨·산출물로 나타나는 항목이다.\n\n")
    text = path.read_text(encoding="utf-8") if path.exists() else intro
    if not text.startswith("# 구현 여부 감사표"):
        text = intro
    pattern = re.compile(rf"^## {re.escape(label)}\n.*?(?=^## |\Z)", re.S | re.M)
    text = pattern.sub(section + "\n", text) if pattern.search(text) else text.rstrip("\n") + "\n\n" + section
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", default=str(ROOT / "docs" / "IMPLEMENTATION_AUDIT.md"))
    args = parser.parse_args()
    out = run_synthetic()
    rows = evaluate(out)
    section = render(args.label, rows, out)
    write(Path(args.out), args.label, section)
    manifest_path = Path(args.out).with_name("run_manifest_example.json")
    manifest_path.write_text(json.dumps(out["result"].run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(f"{r['id']:5} {r['status']:14} {r['finding'][:90]}")


if __name__ == "__main__":
    main()
