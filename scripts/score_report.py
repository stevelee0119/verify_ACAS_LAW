"""온라인 검증 보고서(JSON)를 정답 명세로 채점한다(평가 에이전트 소관, 보호 경로).

사용자는 새 서면을 실제 환경(네트워크·모델·Drive)에서 돌려 보고서 JSON을 준다. 오프라인 점검(`probe_document.py`)이 재지 못하는
AI 작성 판정·공식 DB 대조·Drive 대조·모델 경로를 이 도구가 같은 명세 형식으로 잰다. 보고서에는 그 보고서를 만든 커밋이 들어 있으므로
'어느 코드가 낸 점수인지'가 기록된다. 입력 조건이 사용자 환경이라 오프라인 점수와 섞어 증감을 비교하지 않는다.

    python scripts/score_report.py --report <보고서.json> --spec tests/fixtures/probes/case7_suspension_online.json
    python scripts/score_report.py --report ... --spec ... --record --note "서면7 수신 직후"   # docs/scorecards/first_touch_log.jsonl에 한 줄

명세 항목(kind)
- finding       : 조건에 맞는 finding이 있다(probe_document와 같은 조건: types, min_severity, statuses, text_all, text_any)
- no_finding    : 조건에 맞는 finding이 없다
- pii_kind      : 마스킹 요약(masked_preview.kinds)에 kind가 1건 이상 있다(종류 단위. 항목별 마스킹 여부는 보고서에 없다)
- ai_verdict    : 문서별 AI 작성 판정이 any_of 중 하나다
- ai_models     : 모델 의견 중 min_score 이상이면서 AI 쪽(verdict가 AI_로 시작)인 것이 at_least개 이상이다
- rag_relationship : Drive 대조 의견(engine_data.rag.observations) 중 relationship이 같고 claim_quote에 text가 든 것이 있다
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "scorecards" / "first_touch_log.jsonl"
KINDS = {"finding", "no_finding", "pii_kind", "ai_verdict", "ai_models", "rag_relationship"}


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document", ROOT / "scripts" / "probe_document.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document", module)
    spec.loader.exec_module(module)
    return module


def load_spec(path: Path) -> Dict[str, Any]:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [c["id"] for c in spec["checks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("명세의 항목 id가 겹친다")
    for check in spec["checks"]:
        if check["kind"] not in KINDS:
            raise ValueError(f"알 수 없는 kind: {check['kind']}")
    return spec


def observe_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """보고서 JSON에서 채점에 쓰는 관찰값만 뽑는다. 모든 문서를 합친다."""
    findings: List[Dict[str, str]] = []
    pii_kinds: Dict[str, int] = {}
    verdicts: List[str] = []
    models: List[Dict[str, Any]] = []
    rag: List[Dict[str, Any]] = []
    for doc in report.get("documents", []):
        for f in doc.get("findings", []):
            findings.append({"type": str(f.get("type")), "severity": str(f.get("severity")),
                             "status": str(f.get("status")), "text": json.dumps(f, ensure_ascii=False, default=str)})
        for kind, count in ((doc.get("masked_preview") or {}).get("kinds") or {}).items():
            pii_kinds[kind] = pii_kinds.get(kind, 0) + int(count)
        detector = doc.get("ai_detector_result") or {}
        models.extend(detector.get("model_opinions") or [])
        rag.extend(((doc.get("engine_data") or {}).get("rag") or {}).get("observations") or [])
    for f in report.get("project_findings") or []:
        findings.append({"type": str(f.get("type")), "severity": str(f.get("severity")),
                         "status": str(f.get("status")), "text": json.dumps(f, ensure_ascii=False, default=str)})
    for entry in ((report.get("scores") or {}).get("axes") or {}).get("ai_authorship", {}).get("documents", []):
        verdicts.append(str(entry.get("verdict")))
    manifest = report.get("run_manifest") or {}
    return {"findings": findings, "pii_kinds": pii_kinds, "ai_verdicts": verdicts, "ai_models": models, "rag": rag,
            "commit": ((manifest.get("implementation") or {}).get("git_commit") or "")[:12],
            "versions": manifest.get("versions") or {},
            "network": bool(((manifest.get("environment") or {}).get("network"))),
            "run_id": report.get("run_id"), "started_at": report.get("started_at")}


def evaluate(spec: Dict[str, Any], obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    probe = _probe()
    rows = []
    for check in spec["checks"]:
        kind = check["kind"]
        if kind in ("finding", "no_finding"):
            hit = any(probe._finding_matches(f, check) for f in obs["findings"])
            passed = hit if kind == "finding" else not hit
        elif kind == "pii_kind":
            passed = obs["pii_kinds"].get(check["kind_name"], 0) >= 1
        elif kind == "ai_verdict":
            passed = any(v in check["any_of"] for v in obs["ai_verdicts"])
        elif kind == "ai_models":
            ai = [m for m in obs["ai_models"]
                  if float(m.get("score") or 0) >= float(check.get("min_score", 0))
                  and str(m.get("verdict", "")).startswith("AI_")]
            passed = len(ai) >= int(check.get("at_least", 1))
        else:  # rag_relationship
            passed = any(o.get("relationship") == check["relationship"] and check["text"] in str(o.get("claim_quote", ""))
                         for o in obs["rag"])
        rows.append({"id": check["id"], "label": check.get("label", ""), "passed": bool(passed)})
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def score(report_path: Path, spec_path: Path) -> Dict[str, Any]:
    spec = load_spec(spec_path)
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    obs = observe_report(report)
    rows = evaluate(spec, obs)
    failed = [r["id"] for r in rows if not r["passed"]]
    return {"spec": spec["name"], "rows": rows, "total": len(rows), "passed": len(rows) - len(failed), "failed": failed,
            "commit": obs["commit"], "versions": obs["versions"], "network": obs["network"], "run_id": obs["run_id"],
            "report_sha256": sha256_file(Path(report_path))}


def render(result: Dict[str, Any]) -> str:
    lines = [f"{result['spec']} — 온라인 보고서 {result['passed']}/{result['total']} "
             f"(커밋 {result['commit'] or '?'}, 네트워크 {'켬' if result['network'] else '끔'}, run {result['run_id']})"]
    for row in result["rows"]:
        lines.append(f"  {'통과' if row['passed'] else '실패'}  {row['id']:<8} {row['label']}")
    return "\n".join(lines)


def record(result: Dict[str, Any], note: str, log: Path = LOG) -> None:
    entry = {"recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha": result["commit"],
             "measured_commit": result["commit"], "backfilled": False, "spec": result["spec"], "input": "online_report",
             "passed": result["passed"], "total": result["total"], "failed": result["failed"], "note": note,
             "condition": "online(사용자 환경: 네트워크·모델·Drive), 보고서 JSON 채점",
             "report_sha256": result["report_sha256"], "run_id": result["run_id"], "versions": result["versions"]}
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = score(args.report, args.spec)
    print(json.dumps(result, ensure_ascii=False) if args.json else render(result))
    if args.record:
        record(result, args.note, args.log)
        print(f"기록: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
