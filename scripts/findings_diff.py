"""정답지 없는 문서 묶음(블라인드 등)을 한 사건으로 검증하고, 두 버전의 결과를 finding 단위로 비교한다.

    # 검증: 폴더 안 PDF를 한 사건으로 묶어 파이프라인 결과(to_payload 형식)를 저장한다
    python scripts/findings_diff.py run 폴더 --out 결과.json [--root 다른_버전_작업트리]
    # 비교: 이전 결과 대비 새로 생긴 finding / 없어진 finding
    python scripts/findings_diff.py diff 이전.json 현재.json [--out 비교.md] [--json 비교.json]

finding은 (문서, 유형, 규칙·결함 코드, 제목의 숫자·식별자를 뺀 형태)로 맞춘다. 정답지를 쓰지 않으므로
'새로 생긴 finding'이 정탐인지 오탐인지는 판정하지 않는다. 없어진 결함 주장 finding은 회귀 후보로 보고한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFECT_STATUSES = {"NOT_FOUND", "CONTRADICTED", "SUSPICIOUS", "INVALID_FORMAT", "INVALID"}
DEFECT_SEVERITIES = {"MEDIUM", "HIGH", "CRITICAL"}


def run(folder: Path, root: Path) -> Dict[str, Any]:
    sys.path.insert(0, str(root))
    from packages.audit_engine import AuditChain
    from packages.common.storage import sha256_file
    from packages.report_engine.exporters import to_payload
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline
    from packages.verification_engine.ground_truth_filter import is_ground_truth_filename

    files = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf" and not is_ground_truth_filename(p.name))
    documents = [DocumentInput(document_id=p.stem.split("_")[0], path=str(p), filename=p.name,
                               mime_type="application/pdf", sha256=sha256_file(p)) for p in files]
    result = VerificationPipeline(audit=AuditChain()).run(f"diff_{datetime.utcnow():%Y%m%d%H%M%S}",
                                                          ProjectContext(project_id="diff"), documents)
    payload = to_payload(result)
    payload["scores"] = result.scores
    payload["run_manifest"] = result.run_manifest
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


_VOLATILE = re.compile(r"(CIT|F|FND|DOC)_[0-9a-f]{6,}|[0-9a-f]{12,}")


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", _VOLATILE.sub("#", title or "")).strip()


def is_defect(f: Dict[str, Any]) -> bool:
    if f.get("advisory_only"):
        return False
    status = str(f.get("verification_status") or f.get("status") or "")
    return status in DEFECT_STATUSES or str(f.get("severity") or "") in DEFECT_SEVERITIES


def finding_keys(result: Dict[str, Any]) -> Counter:
    keys: Counter = Counter()
    for document in result.get("documents") or []:
        doc = (document.get("filename") or document.get("document_id") or "").split("_")[0]
        for f in document.get("findings") or []:
            code = f.get("rule_id") or (f.get("confidence_features") or {}).get("defect_code") or ""
            keys[(doc, str(f.get("type")), str(code), _norm_title(f.get("title")), is_defect(f))] += 1
    for f in result.get("project_findings") or []:
        code = f.get("rule_id") or (f.get("confidence_features") or {}).get("defect_code") or ""
        keys[("(문서 간)", str(f.get("type")), str(code), _norm_title(f.get("title")), is_defect(f))] += 1
    return keys


def diff(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    before, after = finding_keys(previous), finding_keys(current)
    added = [(k, after[k] - before.get(k, 0)) for k in after if after[k] > before.get(k, 0)]
    removed = [(k, before[k] - after.get(k, 0)) for k in before if before[k] > after.get(k, 0)]

    def rows(items: List[Tuple[Tuple, int]]) -> List[Dict[str, Any]]:
        return [{"doc": k[0], "type": k[1], "code": k[2], "title": k[3], "defect_claim": k[4], "count": n}
                for k, n in sorted(items)]

    added_rows, removed_rows = rows(added), rows(removed)
    reworded = _pair_reworded(removed_rows, added_rows)
    lost_defects = [r for r in removed_rows if r["defect_claim"] and r["count"] > 0]
    prev_manifest = previous.get("run_manifest") or {}
    curr_manifest = current.get("run_manifest") or {}
    warning = curr_manifest.get("warning") or prev_manifest.get("warning")

    return {"summary": {"findings": [sum(before.values()), sum(after.values())],
                        "defect_claims": [sum(n for k, n in before.items() if k[4]), sum(n for k, n in after.items() if k[4])],
                        "release_gate": [(previous.get("summary") or {}).get("release_gate"),
                                         (current.get("summary") or {}).get("release_gate")]},
            "warning": warning,
            "added": [r for r in added_rows if r["count"] > 0], "removed": [r for r in removed_rows if r["count"] > 0],
            "reworded": reworded, "lost_defect_claims": lost_defects,
            "regression_candidates": sum(r["count"] for r in lost_defects)}


def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    def core(text: str) -> str:
        # 경로 표시·판정 이름 괄호·발췌 인용부는 버전마다 달라진다. 앞부분(판정 종류)과 발췌 글자를 함께 본다.
        return re.sub(r"\s+|—\s*경로:.*$", "", text)
    return SequenceMatcher(None, core(a), core(b)).ratio()


def _pair_reworded(removed: List[Dict[str, Any]], added: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 문서·같은 유형에서 제목이 비슷한(0.6 이상) 없어진 finding과 새 finding을 '문구 변경'으로 짝짓는다.
    짝지은 건수만큼 양쪽 건수에서 뺀다. 결함 주장 여부가 달라지면 짝짓지 않는다."""
    pairs = []
    for r in removed:
        for a in added:
            if not r["count"] or not a["count"]:
                continue
            if (r["doc"], r["type"], r["defect_claim"]) != (a["doc"], a["type"], a["defect_claim"]):
                continue
            score = _similar(r["title"], a["title"])
            if score >= 0.6:
                n = min(r["count"], a["count"])
                r["count"] -= n
                a["count"] -= n
                pairs.append({"doc": r["doc"], "type": r["type"], "before": r["title"], "after": a["title"],
                              "similarity": round(score, 2), "count": n, "defect_claim": r["defect_claim"]})
    return pairs


def render(title: str, d: Dict[str, Any]) -> str:
    s = d["summary"]
    lines = []
    if d.get("warning"):
        lines += [
            "================================================================================",
            f"⚠️  [경고] {d['warning']}",
            "================================================================================",
            "",
        ]
    lines += [f"### {title}", "",
              f"- finding {s['findings'][0]} → {s['findings'][1]}, 결함 주장 finding {s['defect_claims'][0]} → {s['defect_claims'][1]}",
              f"- **회귀 후보(없어진 결함 주장) {d['regression_candidates']}건**", ""]
    lines += [f"**문구만 바뀐 finding(같은 결함)** ({sum(r['count'] for r in d['reworded'])}건)", ""]
    if d["reworded"]:
        lines += ["| 문서 | 유형 | 이전 제목 | 현재 제목 | 유사도 |", "|---|---|---|---|---|"]
        for r in d["reworded"]:
            lines.append(f"| {r['doc']} | {r['type']} | {r['before'].replace('|', '/')[:70]} | "
                         f"{r['after'].replace('|', '/')[:70]} | {r['similarity']} |")
        lines.append("")
    else:
        lines += ["없음", ""]
    for name, key in (("새로 생긴 finding", "added"), ("없어진 finding", "removed")):
        lines += [f"**{name}** ({sum(r['count'] for r in d[key])}건)", ""]
        if not d[key]:
            lines += ["없음", ""]
            continue
        lines += ["| 문서 | 유형 | 코드 | 제목 | 결함 주장 | 건수 |", "|---|---|---|---|---|---|"]
        for r in d[key]:
            t = r["title"].replace("|", "\\|")[:90]
            lines.append(f"| {r['doc']} | {r['type']} | {r['code']} | {t} | {'예' if r['defect_claim'] else '아니오'} | {r['count']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("folder")
    r.add_argument("--out", required=True)
    r.add_argument("--root", default=str(ROOT))
    c = sub.add_parser("diff")
    c.add_argument("previous")
    c.add_argument("current")
    c.add_argument("--title", default="finding 비교")
    c.add_argument("--out")
    c.add_argument("--json")
    args = parser.parse_args()
    if args.cmd == "run":
        payload = run(Path(args.folder), Path(args.root))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"결과: {args.out} (문서 {len(payload.get('documents') or [])}건)")
        return 0
    d = diff(json.loads(Path(args.previous).read_text(encoding="utf-8")),
             json.loads(Path(args.current).read_text(encoding="utf-8")))
    text = render(args.title, d)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
