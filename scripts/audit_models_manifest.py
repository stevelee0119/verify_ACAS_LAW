"""AI 공급자를 켠 상태로 합성 감사 코퍼스를 돌려 실행 매니페스트를 남긴다(v4 검토 5항).

semantic_review(판례 의미·적용 검토)와 model_fact_reconcile(모델의 사실 모순 지적 재검증)이 실제로 실행됐는지,
입력·결과 건수·건너뛴 사유를 매니페스트로 제출한다. API 키가 있는 CI(실연동 통합 테스트 워크플로)에서 실행한다.

    python scripts/audit_models_manifest.py --out docs/run_manifest_with_models.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "run_manifest_with_models.json"))
    args = parser.parse_args()
    from scripts.audit.runner import run_synthetic
    from packages.report_engine.serialize import to_jsonable

    out = run_synthetic(models=True)
    result = out["result"]
    manifest = result.run_manifest or {}
    engines = manifest.get("engines") or {}
    executions = [to_jsonable(e) for e in (result.model_executions or [])]
    semantic = [{"document": d.filename, "reviews": [
        {"citation": next((c.get("raw_text") for c in d.citations if c.get("citation_id") == r.get("citation_id")), r.get("citation_id")),
         "model_executed": r.get("model_executed", False), "source_quotes_validated": r.get("source_quotes_validated", False),
         "reason": str(r.get("reason") or "")[:300], "evidence_quotes": [q[:200] for q in r.get("evidence_quotes") or []][:3]}
        for r in d.engine_data.get("semantic_reviews", [])]} for d in result.documents]
    # 결정론 판정으로 확인된 지적(그 판정의 근거로 붙음)과 사람 확인으로 남은 지적을 나눠 적는다.
    confirmed = [{"document": d.filename, "rule_id": (f.confidence_features or {}).get("rule_id"), "verdict": f.title,
                  "model_remarks": list((f.confidence_features or {}).get("model_remarks") or [])}
                 for d in result.documents for f in d.findings if (f.confidence_features or {}).get("model_remarks")]
    remarks = [{"document": d.filename, "title": f.title, "status": str(f.status),
                "reconciled": (f.confidence_features or {}).get("reconciled"),
                "confirmed_by": (f.confidence_features or {}).get("confirmed_by"),
                "unconfirmed_sentences": (f.confidence_features or {}).get("unconfirmed_sentences")}
               for d in result.documents for f in d.findings if str(f.type).endswith("MODEL_FACT_REMARK")]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "합성 감사 코퍼스(scripts/audit/corpus.py)를 AI 공급자를 켠 상태로 실행한 매니페스트. "
                "문서·판례·법령은 모두 합성이다.",
        "providers_used": sorted({e.get("provider") for e in executions if isinstance(e, dict) and e.get("provider")}),
        "model_calls": {"total": len(executions),
                        "succeeded": sum(1 for e in executions if isinstance(e, dict) and not e.get("error")),
                        "failed": [{"provider": e.get("provider"), "error": str(e.get("error"))[:160]}
                                   for e in executions if isinstance(e, dict) and e.get("error")][:20]},
        "semantic_review": {**{k: engines.get("semantic_review", {}).get(k) for k in
                               ("executed", "runs", "inputs", "input_unit", "findings", "skip_reasons", "errors")},
                            "notes": [e.get("note") for e in engines.get("semantic_review", {}).get("documents", [])
                                      if e.get("note")],
                            "per_document": semantic},
        "model_fact_reconcile": {**{k: engines.get("model_fact_reconcile", {}).get(k) for k in
                                    ("executed", "runs", "inputs", "input_unit", "findings", "skip_reasons", "errors")},
                                 "per_document": [{k: e.get(k) for k in ("document_id", "inputs", "findings", "note",
                                                                         "skipped")}
                                                  for e in engines.get("model_fact_reconcile", {}).get("documents", [])],
                                 "confirmed_by_deterministic": confirmed,
                                 "left_for_human_review": remarks},
        "manifest": manifest,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("providers_used", "model_calls")}, ensure_ascii=False))
    print("semantic_review:", json.dumps(payload["semantic_review"], ensure_ascii=False)[:400])
    print("model_fact_reconcile:", json.dumps(payload["model_fact_reconcile"], ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
